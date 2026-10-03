"""Message analysis service: the only entry point other modules should use.

    analyze_message(message) -> MessageAnalysis

Callers (the API router today, a risk engine later) get validated structured
data and never touch the LLM directly. Modes:

  ai    a real model answered and its JSON passed strict validation
  mock  deterministic demo rules (no key configured, or AI failed in `auto`)
  skipped  nothing to analyze (empty message); no extractor ran
"""

import json
import re
from dataclasses import dataclass
from typing import Optional, Protocol

from ... import config
from . import mock_extractor, prompt
from .ai_provider import AnthropicClient, ProviderError
from .schema import ExtractionValidationError, MessageAnalysis, empty_extraction, validate_extraction

MAX_MESSAGE_CHARS = 5000  # same ceiling as the incident form
MAX_MODEL_REPLY_CHARS = 20_000

MOCK_NOTES = [
    "Demo mode: these values come from simple keyword rules, NOT from an AI model.",
    "Confidence in demo mode only reflects how many fields the rules could fill.",
]
AI_NOTES = ["Extracted by an AI model and validated against a strict schema. Extraction only - not a fraud decision."]


class ExtractionError(Exception):
    """Analysis could not be produced. `code` is stable for API clients."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class CompletionClient(Protocol):
    model: str

    def complete(self, system: str, user: str) -> str: ...


@dataclass(frozen=True)
class AISettings:
    mode: str  # auto | ai | mock
    api_key: Optional[str]
    model: str
    timeout: float


def load_settings() -> AISettings:
    return AISettings(
        mode=config.get_ai_mode(),
        api_key=config.get_ai_api_key(),
        model=config.get_ai_model(),
        timeout=config.get_ai_timeout(),
    )


def parse_model_reply(text: str) -> dict:
    """Turn the model's reply into a dict, or raise ExtractionValidationError."""
    if not isinstance(text, str) or not text.strip():
        raise ExtractionValidationError("empty AI reply")
    if len(text) > MAX_MODEL_REPLY_CHARS:
        raise ExtractionValidationError("AI reply too long")
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.IGNORECASE)
    try:
        parsed = json.loads(cleaned)
    except ValueError:
        raise ExtractionValidationError("AI reply is not valid JSON") from None
    if not isinstance(parsed, dict):
        raise ExtractionValidationError("AI reply is not a JSON object")
    return parsed


def _mock_result(text: str, notes: list, fallback_reason: Optional[str]) -> MessageAnalysis:
    return MessageAnalysis(
        mode="mock",
        model=None,
        extraction=mock_extractor.extract(text),
        notes=MOCK_NOTES + notes,
        fallback_reason=fallback_reason,
    )


def analyze_message(
    message: str,
    *,
    settings: Optional[AISettings] = None,
    client: Optional[CompletionClient] = None,
) -> MessageAnalysis:
    """Extract structured entities and financial intent from one message.

    `settings` and `client` exist for tests/dependency injection; production
    callers use `analyze_message(message)`.
    """
    if not isinstance(message, str):
        raise TypeError("message must be a string")
    settings = settings or load_settings()

    text = message.strip()
    if not text:
        return MessageAnalysis(
            mode="skipped",
            model=None,
            extraction=empty_extraction(),
            notes=["The message is empty, so nothing was analyzed."],
        )
    notes = []
    if len(text) > MAX_MESSAGE_CHARS:
        text = text[:MAX_MESSAGE_CHARS]
        notes.append(f"Message was truncated to {MAX_MESSAGE_CHARS} characters before analysis.")

    if settings.mode == "mock":
        return _mock_result(text, notes, "Demo mode was selected (TRUSTBREAK_AI_MODE=mock).")

    if client is None and settings.api_key:
        client = AnthropicClient(settings.api_key, settings.model, settings.timeout)
    if client is None:
        if settings.mode == "ai":
            raise ExtractionError("ai_not_configured", "AI mode is required but no API key is configured.")
        return _mock_result(text, notes, "No AI API key is configured.")

    delimiter = prompt.new_delimiter()
    try:
        reply = client.complete(prompt.SYSTEM_PROMPT, prompt.build_user_content(text, delimiter))
        extraction = validate_extraction(parse_model_reply(reply))
    except ProviderError as exc:
        code, reason = "ai_unavailable", str(exc)
    except ExtractionValidationError as exc:
        code, reason = "ai_invalid_response", f"AI reply was rejected by validation ({exc})"
    else:
        return MessageAnalysis(mode="ai", model=getattr(client, "model", None), extraction=extraction, notes=AI_NOTES + notes)

    if settings.mode == "ai":
        raise ExtractionError(code, reason)
    return _mock_result(text, notes, f"{reason}; showing the demo rule-based result instead.")
