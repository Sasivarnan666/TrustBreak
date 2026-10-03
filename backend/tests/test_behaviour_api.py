"""HTTP tests for POST /api/incidents/{id}/analyze-behaviour (skipped without FastAPI/httpx)."""

import os
import tempfile
import unittest
from pathlib import Path

try:
    from fastapi.testclient import TestClient

    HAVE_FASTAPI = True
except ImportError:  # pragma: no cover
    HAVE_FASTAPI = False

_ENV_KEYS = ("TRUSTBREAK_DB_PATH", "TRUSTBREAK_SEED_DEMO")

NORMAL = {
    "sender_name": "Arvind Rao",
    "sender_role": "Chief Executive Officer",
    "sender_known": True,
    "channel": "Email",
    "amount": 100000,
    "beneficiary_name": "Vendor A",
    "beneficiary_is_new": False,
    "message": "Please pay the monthly invoice as usual.",
}


@unittest.skipUnless(HAVE_FASTAPI, "fastapi/httpx not installed")
class AnalyzeBehaviourApiTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._saved = {k: os.environ.get(k) for k in _ENV_KEYS}
        os.environ["TRUSTBREAK_DB_PATH"] = str(Path(self._tmp.name) / "api.db")
        os.environ["TRUSTBREAK_SEED_DEMO"] = "1"
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

    def test_demo_ceo_scenario(self):
        res = self.client.post("/api/incidents/1/analyze-behaviour")
        self.assertEqual(res.status_code, 200)
        data = res.json()["data"]
        self.assertEqual(data["employee_id"], "CEO-001")
        self.assertTrue(data["amount_anomaly"] and data["new_beneficiary"] and data["channel_anomaly"])
        self.assertEqual(data["amount_deviation"], 8.25)
        self.assertFalse(data["is_final_decision"])
        self.assertEqual({a["type"] for a in data["anomalies"]}, {"amount", "beneficiary", "channel"})

    def test_normal_payment(self):
        created = self.client.post("/api/incidents", json=NORMAL).json()["data"]
        data = self.client.post(f"/api/incidents/{created['id']}/analyze-behaviour").json()["data"]
        self.assertEqual(data["anomalies"], [])

    def test_unknown_sender_has_no_profile(self):
        created = self.client.post("/api/incidents", json={**NORMAL, "sender_name": "Someone Else"}).json()["data"]
        data = self.client.post(f"/api/incidents/{created['id']}/analyze-behaviour").json()["data"]
        self.assertFalse(data["profile_found"])

    def test_not_found_and_bad_id(self):
        self.assertEqual(self.client.post("/api/incidents/9999/analyze-behaviour").status_code, 404)
        self.assertEqual(self.client.post("/api/incidents/0/analyze-behaviour").status_code, 422)

    def test_get_not_allowed(self):
        self.assertEqual(self.client.get("/api/incidents/1/analyze-behaviour").status_code, 405)


if __name__ == "__main__":
    unittest.main()
