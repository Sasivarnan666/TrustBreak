"""Message analysis service: the only entry point other modules should use.

    analyze_message(message) -> MessageAnalysis

Callers (the API router, the risk assessment) get validated structured data and
never touch an LLM directly. The flow is:

    message -> provider adapter (Gemini | Anthropic | mock) -> validated extraction

Result `mode` (always labelled, never blurred):

  ai       a real model answered and its JSON passed strict validation
  mock     deterministic demo rules (offline mode, no key, or the provider failed in `auto`)
  skipped  nothing to analyze (empty message); no extractor ran

`provider` says which backend produced the extraction; `is_fallback` is True only
when an AI provider was wanted but the demo extractor was used instead.
"""

from dataclasses import dataclass
from typing import Optional, Protocol

from ... import config
from .providers import PROVIDER_LABELS, CompletionProvider, MockProvider, ProviderError, build_provider
from .providers.base import parse_model_reply  # noqa: F401 - re-exported for existing importers
from .schema import ExtractionValidationError, MessageAnalysis, empty_extraction

MAX_MESSAGE_CHARS = 5000  # same ceiling as the incident form

MOCK_NOTES = [
    "Demo mode: these values come from simple keyword rules, NOT from an AI model.",
    "Confidence in demo mode only reflects how many fields the rules could fill.",
]
AI_NOTES = [
    "Extracted by an AI model and validated against a strict schema. Extraction only - not a fraud decision "
    "and not the risk score; the deterministic risk engine decides risk."
]


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
    mode: str  # auto | ai | mock  (failure policy; `mock` forces offline)
    api_key: Optional[str]
    model: str
    timeout: float
    provider: str = "gemini"  # gemini | anthropic | mock


def load_settings() -> AISettings:
    provider = config.get_ai_provider()
    return AISettings(
        mode=config.get_ai_mode(),
        api_key=config.get_ai_api_key(provider),
        model=config.get_ai_model(provider),
        timeout=config.get_ai_timeout(),
        provider=provider,
    )


def _label(provider: str) -> str:
    return PROVIDER_LABELS.get(provider, provider.capitalize())


def _mock_result(
    text: str,
    notes: list,
    fallback_reason: Optional[str],
    *,
    requested: str,
    is_fallback: bool,
) -> MessageAnalysis:
    return MessageAnalysis(
        mode="mock",
        model=None,
        extraction=MockProvider().analyze_message(text),
        notes=MOCK_NOTES + notes,
        fallback_reason=fallback_reason,
        provider="mock",
        requested_provider=requested,
        is_fallback=is_fallback,
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
    requested = settings.provider if settings.mode != "mock" else "mock"

    text = message.strip()
    if not text:
        return MessageAnalysis(
            mode="skipped",
            model=None,
            extraction=empty_extraction(),
            notes=["The message is empty, so nothing was analyzed."],
            requested_provider=requested,
        )
    notes = []
    if len(text) > MAX_MESSAGE_CHARS:
        text = text[:MAX_MESSAGE_CHARS]
        notes.append(f"Message was truncated to {MAX_MESSAGE_CHARS} characters before analysis.")

    # Offline / demo selected on purpose: no network, not a fallback.
    if settings.mode == "mock":
        return _mock_result(text, notes, "Demo mode was selected (TRUSTBREAK_AI_MODE=mock).", requested="mock", is_fallback=False)
    if settings.provider == "mock":
        return _mock_result(text, notes, "Demo mode was selected (TRUSTBREAK_AI_PROVIDER=mock).", requested="mock", is_fallback=False)

    label = _label(settings.provider)
    if client is not None:
        provider = CompletionProvider(client, settings.provider)
    else:
        provider = build_provider(settings.provider, settings.api_key, settings.model, settings.timeout)
    if provider is None:
        key_var = config.AI_KEY_ENV_VARS.get(settings.provider, "an API key")
        if settings.mode == "ai":
            raise ExtractionError("ai_not_configured", f"AI mode is required but no API key is configured ({key_var}).")
        return _mock_result(
            text,
            notes,
            f"No AI API key is configured ({key_var} is not set); {label} was not called. Using demo/mock extraction.",
            requested=settings.provider,
            is_fallback=True,
        )

    try:
        extraction = provider.analyze_message(text)
    except ProviderError as exc:
        code, reason = "ai_unavailable", str(exc)
    except ExtractionValidationError as exc:
        code, reason = "ai_invalid_response", f"AI reply was rejected by validation ({exc})"
    else:
        return MessageAnalysis(
            mode="ai",
            model=getattr(provider, "model", None),
            extraction=extraction,
            notes=AI_NOTES + notes,
            provider=provider.name,
            requested_provider=settings.provider,
        )

    if settings.mode == "ai":
        raise ExtractionError(code, reason)
    return _mock_result(
        text,
        notes,
        f"{label} analysis failed: {reason}. Using demo/mock extraction (not AI).",
        requested=settings.provider,
        is_fallback=True,
    )
