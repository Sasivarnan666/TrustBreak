"""Message-extraction providers: Gemini (primary), Anthropic (legacy), mock (offline)."""

from typing import Optional

from .anthropic import AnthropicProvider
from .base import CompletionProvider, LLMProvider, MessageProvider, ProviderError, parse_model_reply
from .gemini import GeminiProvider
from .mock import MockProvider

PROVIDER_LABELS = {"gemini": "Gemini", "anthropic": "Anthropic", "mock": "Demo"}


def build_provider(name: str, api_key: Optional[str], model: str, timeout: float) -> Optional[MessageProvider]:
    """Create the provider for `name`, or None when it needs a key and none is configured."""
    if name == "mock":
        return MockProvider()
    if not api_key:
        return None
    if name == "gemini":
        return GeminiProvider(api_key, model, timeout)
    if name == "anthropic":
        return AnthropicProvider(api_key, model, timeout)
    raise ValueError(f"unknown provider: {name}")


__all__ = [
    "AnthropicProvider",
    "CompletionProvider",
    "GeminiProvider",
    "LLMProvider",
    "MessageProvider",
    "MockProvider",
    "PROVIDER_LABELS",
    "ProviderError",
    "build_provider",
    "parse_model_reply",
]
