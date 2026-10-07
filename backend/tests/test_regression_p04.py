"""P0.4 - regression tests for gaps found by the coverage audit (branch coverage run on a fresh venv).

Each class names the code that had no test. No real network call; synthetic data only.
"""

import io
import json
import sys
import unittest
import urllib.error
import zipfile
from types import SimpleNamespace
from unittest import mock

from app import risk_repository
from app.services.attachment_analysis import analyze_attachment
from app.services.attachment_analysis.analyzer import detect_type
from app.services.behaviour.analyzer import BehaviourInput, analyze_behaviour
from app.services.behaviour.profile import BehaviourProfile
from app.services.message_analysis import ExtractionError, ExtractionValidationError, analyze_message, validate_extraction
from app.services.message_analysis.providers import AnthropicProvider, GeminiProvider, ProviderError
from app.services.message_analysis.providers import anthropic as anthropic_module
from app.services.message_analysis.providers import gemini as gemini_module
from app.services.message_analysis.service import AISettings

from .test_ai_providers import SECRET, CleanEnv, FakeGeminiClient, gemini_with, settings
from .test_message_analysis import CEO_MESSAGE, good_reply


class FakeHttpResponse:
    def __init__(self, body: bytes):
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, n=-1):
        return self._body if n < 0 else self._body[:n]


def anthropic_reply(text):
    return FakeHttpResponse(json.dumps({"content": [{"type": "text", "text": text}]}).encode())


def http_error(code):
    return urllib.error.HTTPError("https://example.invalid", code, f"body has {SECRET}", {}, io.BytesIO(f"secret {SECRET}".encode()))


class AnthropicProviderTests(CleanEnv):
    """The legacy provider's HTTP path had 42% coverage and no failure-kind tests."""

    def call(self, **kw):
        return AnthropicProvider(SECRET, "claude-test", 5).complete("sys", "user")

    def test_success_joins_text_blocks_and_sends_the_key_only_as_a_header(self):
        body = FakeHttpResponse(json.dumps({"content": [{"type": "text", "text": "a"}, {"type": "tool_use"}, {"type": "text", "text": "b"}]}).encode())
        with mock.patch.object(anthropic_module.urllib.request, "urlopen", return_value=body) as m:
            self.assertEqual(self.call(), "ab")
        request = m.call_args.args[0]
        self.assertEqual(request.get_header("X-api-key"), SECRET)
        self.assertNotIn(SECRET.encode(), request.data)

    def test_http_status_maps_to_failure_kind_without_leaking(self):
        for code, kind in ((429, "quota_exhausted"), (401, "auth_error"), (403, "auth_error"), (404, "model_not_found"), (500, "service_unavailable"), (400, "http_error")):
            with self.subTest(code):
                with mock.patch.object(anthropic_module.urllib.request, "urlopen", side_effect=http_error(code)):
                    with self.assertRaises(ProviderError) as ctx:
                        self.call()
                self.assertEqual(ctx.exception.kind, kind)
                self.assertIn(f"HTTP {code}", str(ctx.exception))
                self.assertNotIn(SECRET, str(ctx.exception))

    def test_timeouts_are_timeouts_not_unreachable(self):
        for err in (TimeoutError("slow"), urllib.error.URLError(TimeoutError("slow"))):
            with self.subTest(type(err).__name__):
                with mock.patch.object(anthropic_module.urllib.request, "urlopen", side_effect=err):
                    with self.assertRaises(ProviderError) as ctx:
                        self.call()
                self.assertEqual(ctx.exception.kind, "timeout")

    def test_network_failure_is_unreachable(self):
        with mock.patch.object(anthropic_module.urllib.request, "urlopen", side_effect=urllib.error.URLError("dns")):
            with self.assertRaises(ProviderError) as ctx:
                self.call()
        self.assertEqual(ctx.exception.kind, "unreachable")

    def test_oversized_and_misshapen_replies_are_invalid_responses(self):
        too_big = FakeHttpResponse(b"x" * (anthropic_module.MAX_RESPONSE_BYTES + 5))
        for body in (too_big, FakeHttpResponse(b"not json"), FakeHttpResponse(b'{"nope": 1}'), FakeHttpResponse(b'{"content": 5}')):
            with mock.patch.object(anthropic_module.urllib.request, "urlopen", return_value=body):
                with self.assertRaises(ProviderError) as ctx:
                    self.call()
            self.assertEqual(ctx.exception.kind, "invalid_response")

    def test_service_falls_back_in_auto_and_errors_in_ai_mode(self):
        cfg = AISettings(mode="auto", api_key=SECRET, model="claude-test", timeout=5, provider="anthropic")
        with mock.patch.object(anthropic_module.urllib.request, "urlopen", side_effect=http_error(429)):
            r = analyze_message(CEO_MESSAGE, settings=cfg)
            self.assertEqual((r.analysis_state, r.failure_kind, r.requested_provider), ("fallback", "quota_exhausted", "anthropic"))
            self.assertNotIn(SECRET, json.dumps(r.to_dict()))
            with self.assertRaises(ExtractionError) as ctx:
                analyze_message(CEO_MESSAGE, settings=AISettings("ai", SECRET, "claude-test", 5, "anthropic"))
        self.assertEqual(ctx.exception.failure_kind, "quota_exhausted")

    def test_valid_reply_end_to_end_is_labelled_anthropic_ai(self):
        cfg = AISettings(mode="auto", api_key=SECRET, model="claude-test", timeout=5, provider="anthropic")
        with mock.patch.object(anthropic_module.urllib.request, "urlopen", return_value=anthropic_reply(json.dumps(good_reply()))):
            r = analyze_message(CEO_MESSAGE, settings=cfg)
        self.assertEqual((r.analysis_state, r.provider, r.mode), ("ai", "anthropic", "ai"))


class GeminiEdgeTests(CleanEnv):
    def test_response_text_property_raising_is_an_empty_response(self):
        class Boom:
            @property
            def text(self):
                raise ValueError("blocked")

        fake = FakeGeminiClient(response=Boom())
        with mock.patch("app.services.message_analysis.service.build_provider", return_value=gemini_with(fake)):
            result = analyze_message(CEO_MESSAGE, settings=settings())
        self.assertEqual((result.analysis_state, result.failure_kind), ("fallback", "empty_response"))

    def test_missing_google_genai_package_is_sdk_missing(self):
        with mock.patch.dict(sys.modules, {"google": None, "google.genai": None}):
            with self.assertRaises(ProviderError) as ctx:
                gemini_module._load_sdk()
        self.assertEqual(ctx.exception.kind, "sdk_missing")

    def test_provider_error_raised_inside_the_client_is_passed_through_with_its_kind(self):
        provider = GeminiProvider(SECRET, "m", 5, client=SimpleNamespace(models=SimpleNamespace(generate_content=mock.Mock(side_effect=ProviderError("custom", "timeout")))))
        with self.assertRaises(ProviderError) as ctx:
            provider.complete("s", "u")
        self.assertEqual(ctx.exception.kind, "timeout")


class ExtractionValidationBranches(unittest.TestCase):
    """Schema branches that rejected hostile model output but were never exercised."""

    def rejected(self, **over):
        with self.assertRaises(ExtractionValidationError):
            validate_extraction(good_reply(**over))

    def test_non_object(self):
        for bad in ([], "x", None, 5):
            with self.assertRaises(ExtractionValidationError):
                validate_extraction(bad)

    def test_text_fields(self):
        self.rejected(beneficiary=5)
        self.rejected(beneficiary="New\x00Vendor")
        self.rejected(beneficiary="x" * 5000)

    def test_numbers(self):
        self.rejected(confidence=float("nan"))
        self.rejected(confidence=float("inf"))
        self.rejected(payment_amount=True)
        self.rejected(payment_amount=10.5)
        self.rejected(payment_amount=0)

    def test_entities(self):
        self.rejected(extracted_entities=[{"type": "person", "value": "a"}] * 500)
        self.rejected(extracted_entities=[{"type": "person", "value": "   "}])
        self.rejected(extracted_entities=[{"type": "person"}])
        self.rejected(extracted_entities="not a list")

    def test_blank_text_becomes_none(self):
        self.assertIsNone(validate_extraction(good_reply(beneficiary="   ")).beneficiary)


class AttachmentSignatureAndLimits(unittest.TestCase):
    SIGNATURES = {
        b"\x7fELF\x02\x01": "elf_executable",
        b"\x89PNG\r\n\x1a\n....": "png",
        b"\xff\xd8\xff\xe0": "jpeg",
        b"GIF89a..": "gif",
        b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1": "ole_document",
        b"Rar!\x1a\x07\x00": "rar",
        b"7z\xbc\xaf\x27\x1c": "7z",
        b"\x1f\x8b\x08": "gzip",
        b"plain text": "unknown",
        b"": "unknown",
    }

    def test_detect_type_by_signature_not_name(self):
        for data, expected in self.SIGNATURES.items():
            with self.subTest(expected=expected):
                self.assertEqual(detect_type(data), expected)

    def test_unsupported_formats_are_reported_not_opened(self):
        for data, name in ((b"7z\xbc\xaf\x27\x1c" + b"0" * 20, "a.7z"), (b"\x1f\x8b\x08" + b"0" * 20, "a.gz")):
            r = analyze_attachment(name, data, "application/octet-stream")
            self.assertTrue(any(f["type"] == "archive_not_inspected" for f in r["findings"]), name)

    def test_shortcut_extension_is_flagged(self):
        r = analyze_attachment("Statement.lnk", b"L\x00\x00\x00", "application/octet-stream")
        self.assertTrue(r["findings"])
        self.assertFalse(r["is_final_decision"])

    def test_total_declared_size_warning_without_high_ratio(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:
            z.writestr("a.txt", b"hello")
        data = bytearray(buf.getvalue())
        with mock.patch("app.services.attachment_analysis.analyzer.config.TOTAL_UNCOMPRESSED_WARN", 1):
            r = analyze_attachment("a.zip", bytes(data), "application/zip")
        self.assertTrue(any(f["type"] == "large_uncompressed_size" for f in r["findings"]))
        self.assertFalse(any(f["type"] == "high_compression_ratio" for f in r["findings"]))


class BehaviourNoHistory(unittest.TestCase):
    def test_profile_without_payment_history_skips_the_amount_check(self):
        profile = BehaviourProfile("X-1", "No History", "Clerk", ("email",), ("vendor a",), ())
        r = analyze_behaviour(BehaviourInput(channel="Email", amount=500000, beneficiary="Vendor A"), profile)
        self.assertEqual(r["checks"]["amount"]["status"], "not_evaluated")
        self.assertFalse(r["amount_anomaly"])
        self.assertFalse(r["is_final_decision"])


class ConsistencyGuardEdges(unittest.TestCase):
    base = {"signals": [{"points": 10, "category": "c"}], "raw_points": 10, "risk_score": 10, "max_score": 100,
            "risk_level": "LOW", "recommended_action": "PROCEED"}

    def test_signals_must_be_a_list(self):
        with self.assertRaises(ValueError):
            risk_repository.check_result_consistent({**self.base, "signals": "oops"})

    def test_optional_fields_may_be_absent(self):
        self.assertIsNone(risk_repository.check_result_consistent(dict(self.base)))

    def test_threshold_mismatch_is_refused(self):
        with self.assertRaises(ValueError):
            risk_repository.check_result_consistent({**self.base, "thresholds": [{"min_score": 0, "level": "LOW"}, {"min_score": 5, "level": "HIGH"}]})


class ApiPersistRace(unittest.TestCase):
    def test_incident_deleted_between_read_and_save_is_a_404(self):
        try:
            from fastapi.testclient import TestClient
        except ImportError:  # pragma: no cover
            self.skipTest("fastapi/httpx not installed")
        import os
        import tempfile
        from pathlib import Path

        saved = {k: os.environ.get(k) for k in ("TRUSTBREAK_DB_PATH", "TRUSTBREAK_SEED_DEMO", "TRUSTBREAK_AI_MODE")}
        with tempfile.TemporaryDirectory() as tmp:
            os.environ.update(TRUSTBREAK_DB_PATH=str(Path(tmp) / "r.db"), TRUSTBREAK_SEED_DEMO="1", TRUSTBREAK_AI_MODE="mock")
            try:
                from app.main import create_app

                with TestClient(create_app()) as c:
                    with mock.patch("app.routers.incidents.risk_repository.save_risk_assessment", side_effect=risk_repository.IncidentNotFound("gone")):
                        res = c.post("/api/incidents/1/analyze-risk")
                self.assertEqual((res.status_code, res.json()["error"]["code"]), (404, "not_found"))
            finally:
                for k, v in saved.items():
                    os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)


class SizeFormatting(unittest.TestCase):
    def test_bytes_kb_mb(self):
        from app.services.analysis import _format_bytes

        self.assertEqual([_format_bytes(n) for n in (5, 2048, 3 * 1024**2)], ["5 B", "2.0 KB", "3.0 MB"])


if __name__ == "__main__":
    unittest.main()
