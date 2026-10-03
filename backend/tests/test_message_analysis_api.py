"""HTTP tests for POST /api/incidents/{id}/analyze-message.

Requires fastapi + httpx (pip install -r requirements-dev.txt); skipped otherwise.
"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

try:
    from fastapi.testclient import TestClient

    HAVE_FASTAPI = True
except ImportError:  # pragma: no cover
    HAVE_FASTAPI = False

_ENV_KEYS = ("TRUSTBREAK_DB_PATH", "TRUSTBREAK_SEED_DEMO", "TRUSTBREAK_AI_MODE", "ANTHROPIC_API_KEY")


@unittest.skipUnless(HAVE_FASTAPI, "fastapi/httpx not installed")
class AnalyzeMessageApiTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._saved = {k: os.environ.get(k) for k in _ENV_KEYS}
        os.environ["TRUSTBREAK_DB_PATH"] = str(Path(self._tmp.name) / "api.db")
        os.environ["TRUSTBREAK_SEED_DEMO"] = "1"
        os.environ["TRUSTBREAK_AI_MODE"] = "auto"
        os.environ.pop("ANTHROPIC_API_KEY", None)  # no key -> demo/mock mode

        from app.main import create_app

        self._cm = TestClient(create_app())
        self.client = self._cm.__enter__()

    def tearDown(self):
        self._cm.__exit__(None, None, None)
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self._tmp.cleanup()

    def test_demo_incident_without_api_key_returns_labelled_mock(self):
        res = self.client.post("/api/incidents/1/analyze-message")
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertTrue(body["success"])
        data = body["data"]
        self.assertEqual(data["mode"], "mock")
        self.assertIsNone(data["model"])
        self.assertFalse(data["is_final_decision"])
        self.assertIn("No AI API key", data["fallback_reason"])
        extraction = data["extraction"]
        self.assertEqual(extraction["payment_amount"], 1850000)
        self.assertEqual(extraction["currency"], "INR")
        self.assertTrue(extraction["secrecy_indicator"])
        self.assertEqual(extraction["urgency_level"], "high")
        self.assertNotIn("risk_level", extraction)

    def test_unknown_incident_is_404_envelope(self):
        res = self.client.post("/api/incidents/999/analyze-message")
        self.assertEqual(res.status_code, 404)
        self.assertEqual(res.json()["error"]["code"], "not_found")

    def test_invalid_id_is_422(self):
        self.assertEqual(self.client.post("/api/incidents/0/analyze-message").status_code, 422)

    def test_get_is_not_allowed(self):
        self.assertEqual(self.client.get("/api/incidents/1/analyze-message").status_code, 405)

    def test_ai_only_mode_without_key_is_clear_503(self):
        os.environ["TRUSTBREAK_AI_MODE"] = "ai"
        res = self.client.post("/api/incidents/1/analyze-message")
        self.assertEqual(res.status_code, 503)
        self.assertEqual(res.json()["error"]["code"], "ai_not_configured")

    def test_provider_failure_maps_to_502(self):
        from app.services.message_analysis import ExtractionError

        with mock.patch("app.routers.incidents.analyze_message", side_effect=ExtractionError("ai_unavailable", "down")):
            res = self.client.post("/api/incidents/1/analyze-message")
        self.assertEqual(res.status_code, 502)
        self.assertEqual(res.json()["error"]["code"], "ai_unavailable")

    def test_existing_incident_endpoints_unchanged(self):
        detail = self.client.get("/api/incidents/1").json()["data"]
        self.assertEqual(detail["analysis"]["mode"], "placeholder")
        self.assertEqual(detail["analysis"]["risk_status"], "needs_review")
        self.assertEqual(self.client.get("/api/incidents").json()["meta"]["total"], 1)


if __name__ == "__main__":
    unittest.main()
