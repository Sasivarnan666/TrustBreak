"""Tests for the provider-agnostic AI adapter (Gemini primary, mock, Anthropic legacy).

No real Gemini/Anthropic call is ever made: the Gemini SDK is either replaced by a
fake client or driven over an in-process httpx MockTransport. Synthetic data only.
Run from backend/:  python -m unittest discover -s tests -t . -v
"""

import json
import os
import unittest
from types import SimpleNamespace
from unittest import mock

try:
    import httpx
    from google import genai  # noqa: F401

    HAVE_SDK = True
except ImportError:  # pragma: no cover
    HAVE_SDK = False

from app import config
from app.services.message_analysis import ExtractionError, ExtractionValidationError, analyze_message, validate_extraction
from app.services.message_analysis.providers import (
    AnthropicProvider,
    GeminiProvider,
    MockProvider,
    ProviderError,
    build_provider,
)
from app.services.message_analysis.providers import gemini as gemini_module
from app.services.message_analysis.schema import extraction_json_schema
from app.services.message_analysis.service import AISettings, load_settings

from .test_message_analysis import CEO_MESSAGE, good_reply

SECRET = "AIza-SECRET-KEY-DO-NOT-LEAK"
ENV_KEYS = (
    "TRUSTBREAK_AI_PROVIDER",
    "TRUSTBREAK_AI_MODE",
    "TRUSTBREAK_AI_MODEL",
    "TRUSTBREAK_AI_TIMEOUT_SECONDS",
    "GEMINI_API_KEY",
    "ANTHROPIC_API_KEY",
)


def settings(provider="gemini", mode="auto", key=SECRET, model="gemini-test-flash"):
    return AISettings(mode=mode, api_key=key, model=model, timeout=5, provider=provider)


class CleanEnv(unittest.TestCase):
    def setUp(self):
        self._saved = {k: os.environ.pop(k, None) for k in ENV_KEYS}

    def tearDown(self):
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


class FakeGeminiClient:
    """Stands in for google.genai.Client; records the request, never touches a network."""

    def __init__(self, text=None, error=None, response=None):
        self.calls = []
        self.models = SimpleNamespace(generate_content=self._generate)
        self._text, self._error, self._response = text, error, response

    def _generate(self, model, contents, config):
        self.calls.append({"model": model, "contents": contents, "config": config})
        if self._error:
            raise self._error
        if self._response is not None:
            return self._response
        text = self._text if isinstance(self._text, str) or self._text is None else json.dumps(self._text)
        return SimpleNamespace(text=text)


def gemini_with(fake, **kw):
    return GeminiProvider(SECRET, kw.get("model", "gemini-test-flash"), 5, client=fake)


# --------------------------------------------------------------------------- #
# 1. Gemini provider configuration / 8. provider selection
# --------------------------------------------------------------------------- #
class ProviderSelectionTests(CleanEnv):
    def test_default_provider_is_gemini_with_no_key(self):
        self.assertEqual(config.get_ai_provider(), "gemini")
        self.assertIsNone(config.get_ai_api_key())

    def test_explicit_provider_values(self):
        for name in ("gemini", "anthropic", "mock"):
            os.environ["TRUSTBREAK_AI_PROVIDER"] = name.upper()
            self.assertEqual(config.get_ai_provider(), name)

    def test_invalid_provider_is_ignored(self):
        os.environ["TRUSTBREAK_AI_PROVIDER"] = "openai"
        self.assertEqual(config.get_ai_provider(), "gemini")

    def test_legacy_anthropic_key_alone_selects_anthropic(self):
        os.environ["ANTHROPIC_API_KEY"] = "legacy"
        self.assertEqual(config.get_ai_provider(), "anthropic")
        self.assertEqual(config.get_ai_api_key(), "legacy")

    def test_gemini_key_wins_over_legacy_anthropic_key_when_provider_unset(self):
        os.environ["ANTHROPIC_API_KEY"] = "legacy"
        os.environ["GEMINI_API_KEY"] = SECRET
        self.assertEqual(config.get_ai_provider(), "gemini")

    def test_explicit_provider_wins_over_keys(self):
        os.environ.update(TRUSTBREAK_AI_PROVIDER="anthropic", GEMINI_API_KEY=SECRET, ANTHROPIC_API_KEY="legacy")
        self.assertEqual(config.get_ai_provider(), "anthropic")
        self.assertEqual(config.get_ai_api_key(), "legacy")

    def test_legacy_mode_mock_forces_offline_even_with_provider_and_key(self):
        os.environ.update(TRUSTBREAK_AI_MODE="mock", TRUSTBREAK_AI_PROVIDER="gemini", GEMINI_API_KEY=SECRET)
        self.assertEqual(config.get_ai_provider(), "mock")
        result = analyze_message(CEO_MESSAGE)
        self.assertEqual((result.mode, result.provider, result.is_fallback), ("mock", "mock", False))

    def test_provider_mock_needs_no_key(self):
        os.environ["TRUSTBREAK_AI_PROVIDER"] = "mock"
        result = analyze_message(CEO_MESSAGE)
        self.assertEqual((result.mode, result.provider, result.model, result.is_fallback), ("mock", "mock", None, False))
        self.assertIn("TRUSTBREAK_AI_PROVIDER=mock", result.fallback_reason)

    def test_model_default_and_override(self):
        self.assertEqual(config.get_ai_model("gemini"), config.DEFAULT_AI_MODELS["gemini"])
        self.assertTrue(config.DEFAULT_AI_MODELS["gemini"].startswith("gemini-"))
        os.environ["TRUSTBREAK_AI_MODEL"] = "gemini-custom-flash"
        self.assertEqual(config.get_ai_model("gemini"), "gemini-custom-flash")
        self.assertEqual(load_settings().model, "gemini-custom-flash")

    def test_load_settings_reads_gemini_environment(self):
        os.environ.update(TRUSTBREAK_AI_PROVIDER="gemini", GEMINI_API_KEY=SECRET, TRUSTBREAK_AI_MODEL="m1")
        s = load_settings()
        self.assertEqual((s.provider, s.api_key, s.model, s.mode), ("gemini", SECRET, "m1", "auto"))

    def test_build_provider_types(self):
        self.assertIsInstance(build_provider("gemini", SECRET, "m", 5), GeminiProvider)
        self.assertIsInstance(build_provider("anthropic", "k", "m", 5), AnthropicProvider)
        self.assertIsInstance(build_provider("mock", None, "m", 5), MockProvider)
        self.assertIsNone(build_provider("gemini", None, "m", 5))
        with self.assertRaises(ValueError):
            build_provider("bogus", "k", "m", 5)

    def test_model_name_is_not_hard_coded_outside_config(self):
        from pathlib import Path

        root = Path(config.__file__).parent
        offenders = [
            str(p.relative_to(root))
            for p in root.rglob("*.py")
            if p.name != "config.py" and "gemini-3" in p.read_text(encoding="utf-8")
        ]
        self.assertEqual(offenders, [])


# --------------------------------------------------------------------------- #
# 2. Missing key
# --------------------------------------------------------------------------- #
class MissingKeyTests(CleanEnv):
    def test_missing_gemini_key_falls_back_with_honest_label(self):
        result = analyze_message(CEO_MESSAGE, settings=settings(key=None))
        self.assertEqual((result.mode, result.provider, result.requested_provider), ("mock", "mock", "gemini"))
        self.assertTrue(result.is_fallback)
        self.assertIsNone(result.model)
        self.assertIn("GEMINI_API_KEY", result.fallback_reason)
        self.assertIn("No AI API key", result.fallback_reason)
        self.assertIn("demo/mock", result.fallback_reason)

    def test_missing_key_in_ai_only_mode_is_an_error_not_a_fallback(self):
        with self.assertRaises(ExtractionError) as ctx:
            analyze_message(CEO_MESSAGE, settings=settings(key=None, mode="ai"))
        self.assertEqual(ctx.exception.code, "ai_not_configured")
        self.assertIn("GEMINI_API_KEY", ctx.exception.message)


# --------------------------------------------------------------------------- #
# 3. Valid structured response
# --------------------------------------------------------------------------- #
class GeminiValidResponseTests(CleanEnv):
    def test_valid_structured_reply_is_accepted_and_labelled_gemini(self):
        fake = FakeGeminiClient(text=good_reply())
        with mock.patch.object(gemini_module, "_load_sdk", wraps=gemini_module._load_sdk):
            provider = gemini_with(fake)
            extraction = provider.analyze_message(CEO_MESSAGE)
        self.assertEqual(extraction.payment_amount, 1850000)
        self.assertEqual(extraction.currency, "INR")
        self.assertEqual(extraction.beneficiary, "new vendor account")
        self.assertEqual(extraction.urgency_level, "high")
        self.assertTrue(extraction.secrecy_indicator)
        self.assertEqual(extraction.financial_intent, "payment_transfer")

    def test_service_result_provenance_for_gemini(self):
        fake = FakeGeminiClient(text=good_reply())
        with mock.patch("app.services.message_analysis.service.build_provider", return_value=gemini_with(fake)):
            result = analyze_message(CEO_MESSAGE, settings=settings())
        self.assertEqual((result.mode, result.provider, result.requested_provider), ("ai", "gemini", "gemini"))
        self.assertEqual(result.model, "gemini-test-flash")
        self.assertFalse(result.is_fallback)
        self.assertIsNone(result.fallback_reason)
        self.assertFalse(result.is_final_decision)

    def test_request_is_text_only_with_structured_output_and_no_tools(self):
        fake = FakeGeminiClient(text=good_reply())
        gemini_with(fake).analyze_message(CEO_MESSAGE)
        call = fake.calls[0]
        cfg = call["config"]
        self.assertEqual(call["model"], "gemini-test-flash")
        self.assertIsInstance(call["contents"], str)  # text only: no files, no attachment bytes
        self.assertIn(CEO_MESSAGE, call["contents"])
        self.assertIn("BEGIN MSG-", call["contents"])  # delimited untrusted data
        self.assertNotIn(CEO_MESSAGE, cfg.system_instruction)  # message never reaches the system prompt
        self.assertEqual(cfg.response_mime_type, "application/json")
        self.assertEqual(cfg.response_json_schema, extraction_json_schema())
        self.assertIsNone(cfg.tools)
        self.assertIsNone(cfg.tool_config)
        self.assertEqual(cfg.temperature, 0)

    def test_automatic_function_calling_is_explicitly_disabled(self):
        fake = FakeGeminiClient(text=good_reply())
        gemini_with(fake).analyze_message(CEO_MESSAGE)
        cfg = fake.calls[0]["config"]
        self.assertIsNone(cfg.tools)
        self.assertIsNotNone(cfg.automatic_function_calling)
        self.assertTrue(cfg.automatic_function_calling.disable)

    def test_json_schema_matches_the_validator(self):
        from app.services.message_analysis.schema import EXTRACTION_KEYS

        schema = extraction_json_schema()
        self.assertEqual(set(schema["properties"]), set(EXTRACTION_KEYS))
        self.assertEqual(set(schema["required"]), set(EXTRACTION_KEYS))
        self.assertFalse(schema["additionalProperties"])
        validate_extraction(good_reply())  # the example the schema describes is accepted

    def test_fenced_json_is_still_accepted(self):
        fake = FakeGeminiClient(text="```json\n" + json.dumps(good_reply()) + "\n```")
        self.assertEqual(gemini_with(fake).analyze_message(CEO_MESSAGE).payment_amount, 1850000)


# --------------------------------------------------------------------------- #
# 4/5/6. Malformed JSON, schema failure, timeout/failure -> labelled fallback
# --------------------------------------------------------------------------- #
class GeminiFailureTests(CleanEnv):
    def run_service(self, fake, mode="auto"):
        with mock.patch("app.services.message_analysis.service.build_provider", return_value=gemini_with(fake)):
            return analyze_message(CEO_MESSAGE, settings=settings(mode=mode))

    def assert_labelled_fallback(self, result, fragment):
        self.assertEqual((result.mode, result.provider, result.requested_provider), ("mock", "mock", "gemini"))
        self.assertTrue(result.is_fallback)
        self.assertIsNone(result.model)  # mock output is never attributed to a model
        self.assertIn("Gemini analysis failed", result.fallback_reason)
        self.assertIn("demo/mock extraction", result.fallback_reason)
        self.assertIn(fragment, result.fallback_reason)
        self.assertNotIn(SECRET, json.dumps(result.to_dict()))

    def test_malformed_json_falls_back(self):
        for text in ("not json at all", "[1, 2]", "{" * 40, '{"claimed_authority": "CEO"'):
            self.assert_labelled_fallback(self.run_service(FakeGeminiClient(text=text)), "rejected by validation")

    def test_malformed_json_in_ai_only_mode_errors(self):
        with self.assertRaises(ExtractionError) as ctx:
            self.run_service(FakeGeminiClient(text="garbage"), mode="ai")
        self.assertEqual(ctx.exception.code, "ai_invalid_response")

    def test_schema_validation_failure_falls_back(self):
        bad = [
            good_reply(urgency_level="critical"),
            good_reply(payment_amount="18,50,000"),
            good_reply(confidence=2),
            good_reply(risk_level="safe"),  # injected verdict field is rejected, not trusted
            good_reply(extracted_entities=[{"type": "command", "value": "rm -rf /"}]),
        ]
        for reply in bad:
            result = self.run_service(FakeGeminiClient(text=reply))
            self.assert_labelled_fallback(result, "rejected by validation")
            self.assertFalse(hasattr(result.extraction, "risk_level"))

    def test_missing_field_falls_back(self):
        reply = good_reply()
        del reply["financial_intent"]
        self.assert_labelled_fallback(self.run_service(FakeGeminiClient(text=reply)), "missing fields")

    def test_timeout_falls_back(self):
        self.assert_labelled_fallback(self.run_service(FakeGeminiClient(error=TimeoutError("slow"))), "timed out")

    def test_sdk_error_with_code_reports_status_only_and_never_the_error_text(self):
        class FakeApiError(Exception):
            code = 429

        fake = FakeGeminiClient(error=FakeApiError(f"quota exceeded for key {SECRET}"))
        result = self.run_service(fake)
        self.assert_labelled_fallback(result, "HTTP 429")
        self.assertNotIn("quota", result.fallback_reason)

    def test_http_503_becomes_ai_unavailable_and_is_never_labelled_ai(self):
        class FakeApiError(Exception):
            code = 503

        fake = FakeGeminiClient(error=FakeApiError(f"overloaded {SECRET}"))
        with self.assertRaises(ExtractionError) as ctx:
            self.run_service(fake, mode="ai")
        self.assertEqual(ctx.exception.code, "ai_unavailable")
        self.assertIn("HTTP 503", ctx.exception.message)
        self.assertNotIn(SECRET, ctx.exception.message)
        self.assertNotIn("overloaded", ctx.exception.message)
        result = self.run_service(fake, mode="auto")  # auto: labelled demo fallback, never "ai"
        self.assert_labelled_fallback(result, "HTTP 503")
        self.assertNotEqual(result.mode, "ai")

    def test_unknown_failure_falls_back_without_leaking(self):
        result = self.run_service(FakeGeminiClient(error=RuntimeError(f"boom {SECRET}")))
        self.assert_labelled_fallback(result, "could not be reached")

    def test_empty_or_blocked_response_falls_back(self):
        self.assert_labelled_fallback(self.run_service(FakeGeminiClient(text=None)), "empty or blocked")

    def test_provider_failure_in_ai_only_mode_errors(self):
        with self.assertRaises(ExtractionError) as ctx:
            self.run_service(FakeGeminiClient(error=TimeoutError()), mode="ai")
        self.assertEqual(ctx.exception.code, "ai_unavailable")

    def test_missing_sdk_falls_back(self):
        with mock.patch.object(gemini_module, "_load_sdk", side_effect=ProviderError("The google-genai package is not installed")):
            with mock.patch("app.services.message_analysis.service.build_provider", return_value=GeminiProvider(SECRET, "m", 5)):
                result = analyze_message(CEO_MESSAGE, settings=settings())
        self.assert_labelled_fallback(result, "not installed")


# --------------------------------------------------------------------------- #
# Real google-genai SDK over a mocked HTTP transport (no network)
# --------------------------------------------------------------------------- #
@unittest.skipUnless(HAVE_SDK, "google-genai / httpx not installed")
class GeminiSdkOverMockTransportTests(CleanEnv):
    def provider(self, handler):
        client = httpx.Client(transport=httpx.MockTransport(handler))
        return GeminiProvider(SECRET, "gemini-test-flash", 5, httpx_client=client)

    @staticmethod
    def ok(text):
        return httpx.Response(200, json={"candidates": [{"content": {"role": "model", "parts": [{"text": text}]}, "finishReason": "STOP"}]})

    def test_request_shape_and_valid_response(self):
        seen = {}

        def handler(request):
            seen["url"], seen["headers"] = str(request.url), request.headers
            seen["body"] = json.loads(request.content)
            return self.ok(json.dumps(good_reply()))

        extraction = self.provider(handler).analyze_message(CEO_MESSAGE)
        self.assertEqual(extraction.payment_amount, 1850000)
        body = seen["body"]
        self.assertIn("generativelanguage.googleapis.com", seen["url"])
        self.assertIn("gemini-test-flash:generateContent", seen["url"])
        self.assertEqual(seen["headers"].get("x-goog-api-key"), SECRET)  # header only
        self.assertNotIn(SECRET, json.dumps(body))
        self.assertNotIn("tools", body)
        self.assertNotIn("toolConfig", body)
        gen = body["generationConfig"]
        self.assertEqual(gen["responseMimeType"], "application/json")
        self.assertIn("responseJsonSchema", gen)
        self.assertEqual(gen["responseJsonSchema"]["required"], extraction_json_schema()["required"])
        parts = body["contents"][0]["parts"]
        self.assertEqual([list(p) for p in parts], [["text"]])  # text only, nothing else
        self.assertIn(CEO_MESSAGE, parts[0]["text"])

    def test_request_body_has_no_function_calling_fields(self):
        seen = {}

        def handler(request):
            seen["body"] = json.loads(request.content)
            return self.ok(json.dumps(good_reply()))

        self.provider(handler).analyze_message(CEO_MESSAGE)
        body = seen["body"]
        # Structural check (the prompt text itself says "you have no tools").
        self.assertEqual(set(body), {"contents", "systemInstruction", "generationConfig"})
        forbidden = {"tools", "toolConfig", "functionDeclarations", "automaticFunctionCalling", "googleSearch", "codeExecution"}
        self.assertFalse(forbidden & set(body))
        self.assertFalse(forbidden & set(body["generationConfig"]))

    def test_sdk_does_not_log_the_afc_warning(self):
        from google.genai import models as genai_models

        genai_models.Models._logged_afc_warning = False  # the SDK logs it once per process
        with self.assertNoLogs("google_genai", level="WARNING"):
            self.provider(lambda r: self.ok(json.dumps(good_reply()))).analyze_message(CEO_MESSAGE)

    def test_final_503_after_sdk_retries_becomes_ai_unavailable(self):
        hits = []

        def handler(request):
            hits.append(1)
            return httpx.Response(503, json={"error": {"code": 503, "message": f"unavailable {SECRET}", "status": "UNAVAILABLE"}})

        provider = self.provider(handler)
        with mock.patch("tenacity.nap.time.sleep"):  # keep the SDK's backoff instant in tests
            with self.assertRaises(ExtractionError) as ctx:
                with mock.patch("app.services.message_analysis.service.build_provider", return_value=provider):
                    analyze_message(CEO_MESSAGE, settings=settings(mode="ai"))
        self.assertEqual(ctx.exception.code, "ai_unavailable")
        self.assertIn("HTTP 503", ctx.exception.message)
        self.assertNotIn(SECRET, ctx.exception.message)
        self.assertEqual(len(hits), gemini_module.RETRY_ATTEMPTS)  # bounded, SDK-native retry only

    def test_transient_503_then_success_is_accepted(self):
        hits = []

        def handler(request):
            hits.append(1)
            if len(hits) == 1:
                return httpx.Response(503, json={"error": {"code": 503, "message": "busy", "status": "UNAVAILABLE"}})
            return self.ok(json.dumps(good_reply()))

        with mock.patch("tenacity.nap.time.sleep"):
            extraction = self.provider(handler).analyze_message(CEO_MESSAGE)
        self.assertEqual(extraction.payment_amount, 1850000)
        self.assertEqual(len(hits), 2)

    def test_quota_429_is_not_retried(self):
        hits = []

        def handler(request):
            hits.append(1)
            return httpx.Response(429, json={"error": {"code": 429, "message": "quota", "status": "RESOURCE_EXHAUSTED"}})

        with self.assertRaises(ProviderError) as ctx:
            self.provider(handler).analyze_message(CEO_MESSAGE)
        self.assertIn("HTTP 429", str(ctx.exception))
        self.assertEqual(len(hits), 1)

    def test_http_error_body_is_not_echoed(self):
        def handler(request):
            return httpx.Response(403, json={"error": {"code": 403, "message": f"key {SECRET} rejected", "status": "PERMISSION_DENIED"}})

        with self.assertRaises(ProviderError) as ctx:
            self.provider(handler).analyze_message(CEO_MESSAGE)
        self.assertIn("HTTP 403", str(ctx.exception))
        self.assertNotIn(SECRET, str(ctx.exception))

    def test_transport_timeout_becomes_provider_error(self):
        def handler(request):
            raise httpx.ReadTimeout("slow", request=request)

        with mock.patch("tenacity.nap.time.sleep"):
            with self.assertRaises(ProviderError) as ctx:
                self.provider(handler).analyze_message(CEO_MESSAGE)
        self.assertIn("timed out", str(ctx.exception))

    def test_blocked_prompt_without_candidates_becomes_provider_error(self):
        def handler(request):
            return httpx.Response(200, json={"promptFeedback": {"blockReason": "SAFETY"}})

        with self.assertRaises(ProviderError):
            self.provider(handler).analyze_message(CEO_MESSAGE)

    def test_malformed_json_text_is_rejected_by_validation(self):
        with self.assertRaises(ExtractionValidationError):
            self.provider(lambda r: self.ok("Sure! Here is the analysis: ...")).analyze_message(CEO_MESSAGE)


# --------------------------------------------------------------------------- #
# 7. Mock provider
# --------------------------------------------------------------------------- #
class MockProviderTests(CleanEnv):
    def test_mock_provider_extracts_deterministically_without_network(self):
        provider = MockProvider()
        a, b = provider.analyze_message(CEO_MESSAGE), provider.analyze_message(CEO_MESSAGE)
        self.assertEqual(a, b)
        self.assertEqual((provider.name, provider.model), ("mock", None))
        self.assertEqual((a.payment_amount, a.currency, a.urgency_level, a.secrecy_indicator), (1850000, "INR", "high", True))

    def test_mock_result_is_never_labelled_as_ai(self):
        result = analyze_message(CEO_MESSAGE, settings=settings(provider="mock", key=None))
        self.assertEqual((result.mode, result.provider, result.model), ("mock", "mock", None))
        self.assertFalse(result.is_fallback)
        self.assertTrue(any("NOT from an AI model" in n for n in result.notes))

    def test_skipped_for_empty_message(self):
        result = analyze_message("   ", settings=settings())
        self.assertEqual((result.mode, result.provider), ("skipped", None))


# --------------------------------------------------------------------------- #
# Risk engine stays authoritative and independent of the provider
# --------------------------------------------------------------------------- #
class RiskEngineIndependenceTests(CleanEnv):
    def assess(self, analysis):
        from app.services.risk_correlation.service import assess_incident_risk

        incident = SimpleNamespace(
            message=CEO_MESSAGE,
            channel="Email",
            sender=SimpleNamespace(name="Arvind Rao", role="CEO"),
            payment=SimpleNamespace(amount=1850000, beneficiary_name="New Vendor X"),
        )
        with mock.patch("app.services.risk_correlation.service.analyze_message", return_value=analysis):
            return assess_incident_risk(incident).to_dict()

    def test_same_structured_evidence_gives_same_risk_from_gemini_and_mock(self):
        extraction = validate_extraction(good_reply())
        from app.services.message_analysis.schema import MessageAnalysis

        gemini = MessageAnalysis(mode="ai", model="m", extraction=extraction, provider="gemini", requested_provider="gemini")
        demo = MessageAnalysis(mode="mock", model=None, extraction=extraction, provider="mock", requested_provider="mock")
        a, b = self.assess(gemini), self.assess(demo)
        for key in ("risk_score", "risk_level", "recommended_action", "signals", "category_points"):
            self.assertEqual(a.get(key), b.get(key), key)
        self.assertIn(a["risk_level"], ("HIGH", "CRITICAL"))

    def test_engine_and_workflow_do_not_import_providers(self):
        import ast
        from pathlib import Path

        root = Path(config.__file__).parent / "services"
        for rel in ("risk_correlation", "behaviour", "attachment_analysis"):
            for path in (root / rel).rglob("*.py"):
                tree = ast.parse(path.read_text(encoding="utf-8"))
                for node in ast.walk(tree):
                    names = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""] if isinstance(node, ast.ImportFrom) else []
                    for name in names:
                        self.assertNotIn("providers", name, f"{path.name} imports {name}")
                        self.assertNotIn("google", name, f"{path.name} imports {name}")


# --------------------------------------------------------------------------- #
# HTTP: provenance fields reach the API consumer
# --------------------------------------------------------------------------- #
try:
    from fastapi.testclient import TestClient

    HAVE_FASTAPI = True
except ImportError:  # pragma: no cover
    HAVE_FASTAPI = False


@unittest.skipUnless(HAVE_FASTAPI, "fastapi/httpx not installed")
class ProviderApiTests(CleanEnv):
    def setUp(self):
        super().setUp()
        import tempfile
        from pathlib import Path

        self._tmp = tempfile.TemporaryDirectory()
        self._db = (os.environ.get("TRUSTBREAK_DB_PATH"), os.environ.get("TRUSTBREAK_SEED_DEMO"))
        os.environ["TRUSTBREAK_DB_PATH"] = str(Path(self._tmp.name) / "p.db")
        os.environ["TRUSTBREAK_SEED_DEMO"] = "1"
        from app.main import create_app

        self._cm = TestClient(create_app())
        self.client = self._cm.__enter__()

    def tearDown(self):
        self._cm.__exit__(None, None, None)
        for key, old in zip(("TRUSTBREAK_DB_PATH", "TRUSTBREAK_SEED_DEMO"), self._db):
            if old is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old
        self._tmp.cleanup()
        super().tearDown()

    def test_gemini_success_is_labelled_ai_gemini(self):
        os.environ.update(TRUSTBREAK_AI_PROVIDER="gemini", GEMINI_API_KEY=SECRET)
        fake = FakeGeminiClient(text=good_reply())
        with mock.patch("app.services.message_analysis.service.build_provider", return_value=gemini_with(fake)):
            data = self.client.post("/api/incidents/1/analyze-message").json()["data"]
        self.assertEqual((data["mode"], data["provider"], data["is_fallback"]), ("ai", "gemini", False))
        self.assertEqual(data["extraction"]["payment_amount"], 1850000)
        self.assertFalse(data["is_final_decision"])

    def test_gemini_failure_is_labelled_fallback_and_never_ai(self):
        os.environ.update(TRUSTBREAK_AI_PROVIDER="gemini", GEMINI_API_KEY=SECRET)
        fake = FakeGeminiClient(error=TimeoutError())
        with mock.patch("app.services.message_analysis.service.build_provider", return_value=gemini_with(fake)):
            res = self.client.post("/api/incidents/1/analyze-message")
        data = res.json()["data"]
        self.assertEqual(res.status_code, 200)
        self.assertEqual((data["mode"], data["provider"], data["requested_provider"], data["is_fallback"]), ("mock", "mock", "gemini", True))
        self.assertIsNone(data["model"])
        self.assertIn("Gemini analysis failed", data["fallback_reason"])
        self.assertNotIn(SECRET, res.text)

    def test_missing_key_default_config_is_labelled_fallback(self):
        data = self.client.post("/api/incidents/1/analyze-message").json()["data"]
        self.assertEqual((data["mode"], data["is_fallback"], data["requested_provider"]), ("mock", True, "gemini"))
        self.assertIn("GEMINI_API_KEY", data["fallback_reason"])


if __name__ == "__main__":
    unittest.main()
