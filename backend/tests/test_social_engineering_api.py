"""HTTP test: POST /api/incidents/{id}/analyze-message returns social_engineering evidence (offline mock mode)."""

import os
import tempfile
import unittest
from pathlib import Path

try:
    from fastapi.testclient import TestClient

    HAVE_FASTAPI = True
except ImportError:  # pragma: no cover
    HAVE_FASTAPI = False

_ENV_KEYS = ("TRUSTBREAK_DB_PATH", "TRUSTBREAK_SEED_DEMO", "TRUSTBREAK_AI_MODE", "TRUSTBREAK_AI_PROVIDER", "GEMINI_API_KEY",
             "TRUSTBREAK_LOAD_DOTENV")


@unittest.skipUnless(HAVE_FASTAPI, "fastapi/httpx not installed")
class SocialEngineeringApiTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._saved = {k: os.environ.get(k) for k in _ENV_KEYS}
        os.environ.update({"TRUSTBREAK_DB_PATH": str(Path(self._tmp.name) / "a.db"), "TRUSTBREAK_SEED_DEMO": "1",
                           "TRUSTBREAK_AI_MODE": "mock", "TRUSTBREAK_LOAD_DOTENV": "0"})
        os.environ.pop("GEMINI_API_KEY", None)
        from app.main import create_app

        self._cm = TestClient(create_app())
        self.client = self._cm.__enter__()

    def tearDown(self):
        self._cm.__exit__(None, None, None)
        for k, v in self._saved.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        self._tmp.cleanup()

    def test_demo_incident_returns_labelled_evidence(self):
        data = self.client.post("/api/incidents/1/analyze-message").json()["data"]
        se = data["social_engineering"]
        self.assertFalse(se["is_final_decision"])
        self.assertEqual(len(se["signals"]), 11)
        detected = [s for s in se["signals"] if s["detected"]]
        self.assertGreaterEqual(len(detected), 3)
        for s in detected:
            self.assertTrue(s["evidence"])
            self.assertEqual(s["source"], "rule")
        self.assertNotIn("risk_score", str(se))


if __name__ == "__main__":
    unittest.main()
