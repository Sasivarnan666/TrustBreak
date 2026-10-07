"""P0.1 - Gemini resilience: every AI failure mode ends in a labelled state, never a crash,
never a falsely-AI result, and never a different risk score.

No real Gemini call is made: the SDK client is a fake. Synthetic data only.
"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from app.services.message_analysis import ExtractionError, analyze_message
from app.services.message_analysis.providers import FAILURE_KINDS, GeminiProvider, ProviderError
from app.services.message_analysis.providers import gemini as gemini_module
from app.services.message_analysis.providers.base import kind_for_status
from app.services.risk_correlation.service import assess_incident_risk

from .test_ai_providers import SECRET, CleanEnv, FakeGeminiClient, gemini_with, settings
from .test_message_analysis import CEO_MESSAGE, good_reply

try:
    from fastapi.testclient import TestClient

    HAVE_FASTAPI = True
except ImportError:  # pragma: no cover
    HAVE_FASTAPI = False


def http_error(code):
    class FakeApiError(Exception):
        pass

    err = FakeApiError(f"provider says no, key={SECRET}")
    err.code = code
    return err


def run(fake, mode="auto"):
    with mock.patch("app.services.message_analysis.service.build_provider", return_value=gemini_with(fake)):
        return analyze_message(CEO_MESSAGE, settings=settings(mode=mode))


class FailureModeTable(CleanEnv):
    """(label, client, expected failure_kind) - one row per failure mode in the P0.1 brief."""

    CASES = [
        ("429 quota exhausted", lambda: FakeGeminiClient(error=http_error(429)), "quota_exhausted"),
        ("401 auth", lambda: FakeGeminiClient(error=http_error(401)), "auth_error"),
        ("403 auth", lambda: FakeGeminiClient(error=http_error(403)), "auth_error"),
        ("404 model", lambda: FakeGeminiClient(error=http_error(404)), "model_not_found"),
        ("500", lambda: FakeGeminiClient(error=http_error(500)), "service_unavailable"),
        ("503", lambda: FakeGeminiClient(error=http_error(503)), "service_unavailable"),
        ("400 other", lambda: FakeGeminiClient(error=http_error(400)), "http_error"),
        ("timeout", lambda: FakeGeminiClient(error=TimeoutError("slow")), "timeout"),
        ("network", lambda: FakeGeminiClient(error=ConnectionError(f"dns {SECRET}")), "unreachable"),
        ("empty/blocked", lambda: FakeGeminiClient(text=None), "empty_response"),
        ("not json", lambda: FakeGeminiClient(text="not json"), "invalid_response"),
        ("schema violation", lambda: FakeGeminiClient(text=good_reply(urgency_level="critical")), "invalid_response"),
        ("injected verdict", lambda: FakeGeminiClient(text=good_reply(risk_level="safe")), "invalid_response"),
    ]

    def test_auto_mode_always_falls_back_with_a_labelled_state(self):
        for label, make, kind in self.CASES:
            with self.subTest(label):
                r = run(make())
                self.assertEqual(r.mode, "mock", label)
                self.assertEqual(r.analysis_state, "fallback", label)
                self.assertTrue(r.is_fallback)
                self.assertEqual((r.provider, r.requested_provider), ("mock", "gemini"))
                self.assertIsNone(r.model)  # never attributed to a model
                self.assertEqual(r.failure_kind, kind)
                self.assertIn("not AI", r.fallback_reason)
                self.assertNotIn(SECRET, json.dumps(r.to_dict()))
                self.assertEqual(r.extraction.payment_amount, 1850000)  # workflow still gets evidence
                self.assertFalse(r.is_final_decision)

    def test_ai_only_mode_errors_with_the_same_kind_and_no_substitute(self):
        for label, make, kind in self.CASES:
            with self.subTest(label):
                with self.assertRaises(ExtractionError) as ctx:
                    run(make(), mode="ai")
                self.assertEqual(ctx.exception.failure_kind, kind)
                self.assertIn(ctx.exception.code, ("ai_unavailable", "ai_invalid_response"))
                self.assertNotIn(SECRET, ctx.exception.message)

    def test_every_kind_used_is_a_declared_kind(self):
        self.assertTrue({k for _, _, k in self.CASES} <= set(FAILURE_KINDS))

    def test_status_code_mapping(self):
        self.assertEqual(
            [kind_for_status(c) for c in (401, 403, 404, 408, 429, 400, 500, 504)],
            ["auth_error", "auth_error", "model_not_found", "timeout", "quota_exhausted", "http_error", "service_unavailable", "timeout"],
        )

    def test_reason_gives_a_hint_without_leaking_provider_text(self):
        quota = run(FakeGeminiClient(error=http_error(429))).fallback_reason
        auth = run(FakeGeminiClient(error=http_error(401))).fallback_reason
        self.assertIn("HTTP 429", quota)
        self.assertIn("resets", quota)
        self.assertIn("API key", auth)
        for text in (quota, auth):
            self.assertNotIn("provider says no", text)
            self.assertNotIn(SECRET, text)

    def test_missing_key_and_missing_sdk(self):
        r = analyze_message(CEO_MESSAGE, settings=settings(key=None))
        self.assertEqual((r.analysis_state, r.failure_kind), ("fallback", "not_configured"))
        with self.assertRaises(ExtractionError) as ctx:
            analyze_message(CEO_MESSAGE, settings=settings(key=None, mode="ai"))
        self.assertEqual(ctx.exception.failure_kind, "not_configured")
        with mock.patch.object(gemini_module, "_load_sdk", side_effect=ProviderError("The google-genai package is not installed", "sdk_missing")):
            with mock.patch("app.services.message_analysis.service.build_provider", return_value=GeminiProvider(SECRET, "m", 5)):
                r = analyze_message(CEO_MESSAGE, settings=settings())
        self.assertEqual((r.analysis_state, r.failure_kind), ("fallback", "sdk_missing"))

    def test_unexpected_provider_bug_does_not_break_the_workflow(self):
        class Boom:
            model = "x"

            def complete(self, system, user):
                raise KeyError(f"bug {SECRET}")

        r = analyze_message(CEO_MESSAGE, settings=settings(), client=Boom())
        self.assertEqual((r.analysis_state, r.failure_kind, r.mode), ("fallback", "unexpected", "mock"))
        self.assertNotIn(SECRET, json.dumps(r.to_dict()))
        with self.assertRaises(ExtractionError) as ctx:
            analyze_message(CEO_MESSAGE, settings=settings(mode="ai"), client=Boom())
        self.assertEqual(ctx.exception.failure_kind, "unexpected")


class StateLabels(CleanEnv):
    def test_four_states_are_distinct(self):
        ai = run(FakeGeminiClient(text=good_reply()))
        fb = run(FakeGeminiClient(error=http_error(429)))
        mk = analyze_message(CEO_MESSAGE, settings=settings(provider="mock"))
        sk = analyze_message("   ", settings=settings())
        self.assertEqual([x.analysis_state for x in (ai, fb, mk, sk)], ["ai", "fallback", "mock", "skipped"])
        self.assertEqual((ai.mode, ai.provider, ai.failure_kind, ai.is_fallback), ("ai", "gemini", None, False))
        self.assertFalse(mk.is_fallback)
        self.assertIsNone(mk.failure_kind)

    def test_only_a_validated_model_reply_is_ever_state_ai(self):
        for _, make, _ in FailureModeTable.CASES:
            self.assertNotEqual(run(make()).analysis_state, "ai")


class DerivedState(CleanEnv):
    def test_directly_built_analyses_derive_their_state(self):
        from app.services.message_analysis.schema import MessageAnalysis, empty_extraction

        e = empty_extraction()
        self.assertEqual(MessageAnalysis(mode="ai", model="m", extraction=e).analysis_state, "ai")
        self.assertEqual(MessageAnalysis(mode="mock", model=None, extraction=e).analysis_state, "mock")
        self.assertEqual(MessageAnalysis(mode="mock", model=None, extraction=e, is_fallback=True).analysis_state, "fallback")
        self.assertEqual(MessageAnalysis(mode="skipped", model=None, extraction=e).analysis_state, "skipped")


def rate_limited_assessment():
    incident = SimpleNamespace(
        message=CEO_MESSAGE,
        channel="WhatsApp",
        sender=SimpleNamespace(name="Arvind Rao", role="CEO"),
        payment=SimpleNamespace(amount=1850000, beneficiary_name="New Vendor X"),
    )
    return incident


class RiskUnchangedByFailure(CleanEnv):
    def assess(self, analysis):
        with mock.patch("app.services.risk_correlation.service.analyze_message", return_value=analysis):
            return assess_incident_risk(rate_limited_assessment()).to_dict()

    def test_score_is_identical_for_ai_fallback_and_mock_extraction(self):
        ai = self.assess(run(FakeGeminiClient(text=good_reply())))
        fb = self.assess(run(FakeGeminiClient(error=http_error(429))))
        # same structured evidence -> same score; the extractor's origin never changes the verdict
        fb_same = self.assess(run(FakeGeminiClient(error=TimeoutError())))
        for key in ("risk_score", "risk_level", "recommended_action", "category_points"):
            self.assertEqual(fb[key], fb_same[key], key)
        self.assertIn(fb["risk_level"], ("HIGH", "CRITICAL"))
        self.assertIn(ai["risk_level"], ("HIGH", "CRITICAL"))

    def test_risk_inputs_disclose_the_fallback(self):
        fb = self.assess(run(FakeGeminiClient(error=http_error(429))))["inputs"]["message"]
        self.assertEqual((fb["status"], fb["analysis_state"], fb["failure_kind"], fb["provider"]), ("used", "fallback", "quota_exhausted", "mock"))
        self.assertIn("not AI", fb["detail"])
        ai = self.assess(run(FakeGeminiClient(text=good_reply())))["inputs"]["message"]
        self.assertEqual((ai["analysis_state"], ai["provider"], ai["failure_kind"]), ("ai", "gemini", None))
        self.assertNotIn("fallback", ai["detail"].lower())


@unittest.skipUnless(HAVE_FASTAPI, "fastapi/httpx not installed")
class ApiResilience(CleanEnv):
    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        self._db = (os.environ.get("TRUSTBREAK_DB_PATH"), os.environ.get("TRUSTBREAK_SEED_DEMO"))
        os.environ["TRUSTBREAK_DB_PATH"] = str(Path(self._tmp.name) / "r.db")
        os.environ["TRUSTBREAK_SEED_DEMO"] = "1"
        from app.main import create_app

        self._cm = TestClient(create_app())
        self.client = self._cm.__enter__()
        os.environ.update(TRUSTBREAK_AI_PROVIDER="gemini", GEMINI_API_KEY=SECRET)

    def tearDown(self):
        self._cm.__exit__(None, None, None)
        for key, old in zip(("TRUSTBREAK_DB_PATH", "TRUSTBREAK_SEED_DEMO"), self._db):
            if old is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old
        self._tmp.cleanup()
        super().tearDown()

    def patched(self, fake):
        return mock.patch("app.services.message_analysis.service.build_provider", return_value=gemini_with(fake))

    def test_429_message_analysis_is_labelled_fallback(self):
        with self.patched(FakeGeminiClient(error=http_error(429))):
            res = self.client.post("/api/incidents/1/analyze-message")
        d = res.json()["data"]
        self.assertEqual(res.status_code, 200)
        self.assertEqual((d["analysis_state"], d["failure_kind"], d["mode"], d["is_fallback"]), ("fallback", "quota_exhausted", "mock", True))
        self.assertNotIn(SECRET, res.text)

    def test_auth_error_in_ai_mode_is_a_clear_unavailable_error_with_kind(self):
        os.environ["TRUSTBREAK_AI_MODE"] = "ai"
        with self.patched(FakeGeminiClient(error=http_error(401))):
            res = self.client.post("/api/incidents/1/analyze-message")
        body = res.json()
        self.assertEqual((res.status_code, body["success"], body["error"]["code"]), (502, False, "ai_unavailable"))
        self.assertEqual(body["error"]["details"], [{"failure_kind": "auth_error"}])
        self.assertNotIn(SECRET, res.text)

    def test_risk_assessment_survives_429_and_persists_the_disclosure(self):
        with self.patched(FakeGeminiClient(error=http_error(429))):
            res = self.client.post("/api/incidents/1/analyze-risk")
        data = res.json()["data"]
        self.assertEqual(res.status_code, 200)
        self.assertTrue(data["persisted"])
        self.assertEqual(data["risk_level"], "CRITICAL")
        self.assertEqual(data["inputs"]["message"]["analysis_state"], "fallback")
        stored = self.client.get("/api/incidents/1").json()["data"]["risk_assessment"]
        self.assertEqual(stored["inputs"]["message"]["failure_kind"], "quota_exhausted")
        self.assertEqual(stored["risk_score"], data["risk_score"])

    def test_score_is_the_same_whether_gemini_answers_or_is_rate_limited(self):
        with self.patched(FakeGeminiClient(text=good_reply())):
            ok = self.client.post("/api/incidents/1/analyze-risk").json()["data"]
        with self.patched(FakeGeminiClient(error=http_error(429))):
            limited = self.client.post("/api/incidents/1/analyze-risk").json()["data"]
        self.assertEqual(ok["inputs"]["message"]["analysis_state"], "ai")
        self.assertEqual(limited["inputs"]["message"]["analysis_state"], "fallback")
        self.assertEqual(ok["risk_level"], limited["risk_level"])


if __name__ == "__main__":
    unittest.main()
