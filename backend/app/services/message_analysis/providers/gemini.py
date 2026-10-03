"""Gemini provider (official `google-genai` SDK).

Security shape of the request: ONE text-only `generate_content` call.
  - no tools, no function calling, no URL context, no search grounding, no code execution
  - no files or attachment bytes - only the (delimited, untrusted) message text
  - automatic function calling (AFC) is explicitly DISABLED. The SDK enables its AFC code
    path by default even when no tools are supplied (it then logs "Direct use of automatic
    function calling ... is not recommended"); `AutomaticFunctionCallingConfig(disable=True)`
    switches that path off, so the warning disappears and the intent is explicit
  - structured JSON output is requested (`response_mime_type` + `response_json_schema`),
    but the reply is still validated by `validate_extraction`; the schema hint is a
    request, never a guarantee
  - transient 5xx replies are retried by the SDK's own retry support (small, bounded:
    RETRY_ATTEMPTS total tries); there is no custom retry loop. A final 503 becomes a
    ProviderError -> `ai_unavailable`, never a successful analysis
  - the API key comes from the environment (GEMINI_API_KEY) via the service; it is never
    logged, returned or placed in an error message (errors carry a status code only)
"""

from typing import Any, Optional

from ..schema import extraction_json_schema
from .base import LLMProvider, ProviderError

MAX_OUTPUT_TOKENS = 4096  # headroom for models that spend part of the budget on thinking

# The SDK does NOT retry unless `retry_options` is set. Keep it small and bounded; quota
# errors (429) are deliberately not retried.
RETRY_ATTEMPTS = 3  # including the first request
RETRY_STATUS_CODES = [500, 502, 503, 504]


def _load_sdk():
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        raise ProviderError("The google-genai package is not installed") from None
    return genai, types


def _is_timeout(exc: BaseException) -> bool:
    seen = 0
    while exc is not None and seen < 5:
        if isinstance(exc, TimeoutError) or "timeout" in type(exc).__name__.lower():
            return True
        exc = exc.__cause__ or exc.__context__
        seen += 1
    return False


class GeminiProvider(LLMProvider):
    name = "gemini"

    def __init__(self, api_key: str, model: str, timeout: float = 20.0, *, client: Any = None, httpx_client: Any = None) -> None:
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self._client = client  # injectable for tests; built lazily from the SDK otherwise
        self._httpx_client = httpx_client  # test seam for the real SDK over a mocked transport

    def _get_client(self, types: Any, genai: Any):
        if self._client is None:
            retry = types.HttpRetryOptions(
                attempts=RETRY_ATTEMPTS, initial_delay=1.0, max_delay=4.0, http_status_codes=RETRY_STATUS_CODES
            )
            options = types.HttpOptions(
                timeout=int(self.timeout * 1000), httpx_client=self._httpx_client, retry_options=retry
            )
            self._client = genai.Client(api_key=self.api_key, http_options=options)
        return self._client

    def complete(self, system: str, user: str) -> str:
        genai, types = _load_sdk()
        config = types.GenerateContentConfig(
            system_instruction=system,
            temperature=0,
            max_output_tokens=MAX_OUTPUT_TOKENS,
            response_mime_type="application/json",
            response_json_schema=extraction_json_schema(),
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        try:
            client = self._get_client(types, genai)
            response = client.models.generate_content(model=self.model, contents=user, config=config)
        except ProviderError:
            raise
        except Exception as exc:  # noqa: BLE001 - SDK raises many types; never echo their text
            if _is_timeout(exc):
                raise ProviderError("Gemini request timed out") from None
            code = getattr(exc, "code", None)
            if isinstance(code, int):
                raise ProviderError(f"Gemini returned HTTP {code}") from None
            raise ProviderError("Gemini could not be reached") from None

        try:
            text: Optional[str] = response.text
        except Exception:  # noqa: BLE001
            text = None
        if not isinstance(text, str) or not text.strip():
            raise ProviderError("Gemini returned an empty or blocked response")
        return text
