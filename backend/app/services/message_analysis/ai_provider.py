"""Anthropic Messages API client (standard library only, no extra dependency).

Nothing here interprets the message. The model gets no tools, and its reply is
returned as plain text for the caller to parse and validate.
"""

import json
import urllib.error
import urllib.request

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"
MAX_RESPONSE_BYTES = 200_000


class ProviderError(Exception):
    """The AI provider could not be reached or returned an unusable reply."""


class AnthropicClient:
    def __init__(self, api_key: str, model: str, timeout: float = 20.0) -> None:
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def complete(self, system: str, user: str) -> str:
        body = json.dumps(
            {
                "model": self.model,
                "max_tokens": 900,
                "temperature": 0,
                "system": system,
                "messages": [{"role": "user", "content": user}],
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            API_URL,
            data=body,
            method="POST",
            headers={
                "content-type": "application/json",
                "x-api-key": self.api_key,
                "anthropic-version": API_VERSION,
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:  # noqa: S310 - fixed https URL
                raw = response.read(MAX_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as exc:
            # Status code only: never echo headers or bodies that may hold secrets.
            raise ProviderError(f"AI provider returned HTTP {exc.code}") from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise ProviderError("AI provider could not be reached") from None

        if len(raw) > MAX_RESPONSE_BYTES:
            raise ProviderError("AI provider response was too large")
        try:
            payload = json.loads(raw)
            blocks = payload["content"]
            return "".join(b["text"] for b in blocks if isinstance(b, dict) and b.get("type") == "text")
        except (ValueError, KeyError, TypeError):
            raise ProviderError("AI provider response had an unexpected shape") from None
