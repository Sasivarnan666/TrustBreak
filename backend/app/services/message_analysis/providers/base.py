"""Provider contract shared by every message-extraction backend.

A provider turns ONE untrusted message into a validated `MessageExtraction`:

    provider.analyze_message(text) -> MessageExtraction

LLM-backed providers only implement `complete(system, user) -> str` (a plain
text round trip with no tools); prompt building, reply parsing and strict
schema validation live here once, so no provider duplicates analysis logic and
no provider can hand unvalidated model output to the rest of the application.
"""

import json
import re
from typing import Optional, Protocol

from .. import prompt
from ..schema import SOCIAL_SIGNALS_KEY, ExtractionValidationError, MessageExtraction, validate_extraction

MAX_MODEL_REPLY_CHARS = 20_000


# Stable, machine-readable failure categories (no secrets, no provider text).
FAILURE_KINDS = (
    "quota_exhausted",  # HTTP 429: free-tier / rate limit reached
    "auth_error",  # HTTP 401/403: key missing permission or rejected
    "model_not_found",  # HTTP 404: model name retired or wrong
    "timeout",
    "service_unavailable",  # HTTP 5xx after the SDK's bounded retries
    "unreachable",  # network / DNS / connection failure
    "http_error",  # any other HTTP status
    "empty_response",  # empty, blocked or filtered reply
    "invalid_response",  # reply failed JSON / schema validation
    "not_configured",  # no API key
    "sdk_missing",
    "unexpected",  # anything else; text is never echoed
)


def kind_for_status(code: int) -> str:
    if code == 429:
        return "quota_exhausted"
    if code in (401, 403):
        return "auth_error"
    if code == 404:
        return "model_not_found"
    if code in (408, 504):
        return "timeout"
    if code >= 500:
        return "service_unavailable"
    return "http_error"


class ProviderError(Exception):
    """The AI provider could not be reached or returned an unusable reply.

    Messages must never contain API keys, request bodies or raw model output.
    `kind` is one of FAILURE_KINDS.
    """

    def __init__(self, message: str, kind: str = "unexpected") -> None:
        super().__init__(message)
        self.kind = kind


class MessageProvider(Protocol):
    name: str  # "gemini" | "anthropic" | "mock"
    model: Optional[str]  # None for the mock provider

    def analyze_message(self, text: str) -> MessageExtraction: ...


def parse_model_reply(text: str) -> dict:
    """Turn a model reply into a dict, or raise ExtractionValidationError."""
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


class LLMProvider:
    """Base for providers that call a language model for text analysis only."""

    name = "llm"
    model: Optional[str] = None

    def complete(self, system: str, user: str) -> str:  # pragma: no cover - interface
        raise NotImplementedError

    def analyze_message_with_signals(self, text: str) -> tuple:
        """Return (validated extraction, RAW optional social-engineering list). The list is untrusted: the service
        validates and grounds it against the message. The extraction itself is validated exactly as before."""
        delimiter = prompt.new_delimiter()
        reply = self.complete(prompt.SYSTEM_PROMPT, prompt.build_user_content(text, delimiter))
        parsed = parse_model_reply(reply)
        raw_signals = parsed.pop(SOCIAL_SIGNALS_KEY, None)
        return validate_extraction(parsed), raw_signals

    def analyze_message(self, text: str) -> MessageExtraction:
        return self.analyze_message_with_signals(text)[0]


class CompletionProvider(LLMProvider):
    """Adapts any object with `complete(system, user)` (e.g. a test double)."""

    def __init__(self, client, name: str) -> None:
        self._client = client
        self.name = name
        self.model = getattr(client, "model", None)

    def complete(self, system: str, user: str) -> str:
        return self._client.complete(system, user)
