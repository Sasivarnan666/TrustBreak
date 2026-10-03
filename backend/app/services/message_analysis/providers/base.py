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
from ..schema import ExtractionValidationError, MessageExtraction, validate_extraction

MAX_MODEL_REPLY_CHARS = 20_000


class ProviderError(Exception):
    """The AI provider could not be reached or returned an unusable reply.

    Messages must never contain API keys, request bodies or raw model output.
    """


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

    def analyze_message(self, text: str) -> MessageExtraction:
        delimiter = prompt.new_delimiter()
        reply = self.complete(prompt.SYSTEM_PROMPT, prompt.build_user_content(text, delimiter))
        return validate_extraction(parse_model_reply(reply))


class CompletionProvider(LLMProvider):
    """Adapts any object with `complete(system, user)` (e.g. a test double)."""

    def __init__(self, client, name: str) -> None:
        self._client = client
        self.name = name
        self.model = getattr(client, "model", None)

    def complete(self, system: str, user: str) -> str:
        return self._client.complete(system, user)
