"""HTTP tests for Baseline 2.0 (received_at, time/day/velocity from real stored incidents)."""

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
BASE = {
    "sender_name": "Arvind Rao", "sender_role": "Chief Executive Officer", "sender_known": True,
    "sender_identity_id": "CEO-001", "channel": "Email", "amount": 100000, "beneficiary_name": "Vendor A",
    "beneficiary_is_new": False, "message": "Please pay the monthly invoice as usual.",
}


@unittest.skipUnless(HAVE_FASTAPI, "fastapi/httpx not installed")
class BaselineApiTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._saved = {k: os.environ.get(k) for k in _ENV_KEYS}
        os.environ["TRUSTBREAK_DB_PATH"] = str(Path(self._tmp.name) / "api.db")
        os.environ["TRUSTBREAK_SEED_DEMO"] = "0"
        from app.main import create_app

        self._cm = TestClient(create_app())
        self.client = self._cm.__enter__()

    def tearDown(self):
        self._cm.__exit__(None, None, None)
        for k, v in self._saved.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        self._tmp.cleanup()

    def _create(self, **kw):
        res = self.client.post("/api/incidents", json={**BASE, **kw})
        self.assertEqual(res.status_code, 201, res.text)
        return res.json()["data"]["id"]

    def _behaviour(self, incident_id):
        return self.client.post(f"/api/incidents/{incident_id}/analyze-behaviour").json()["data"]

    def test_without_received_at_time_checks_not_evaluated(self):
        data = self._behaviour(self._create())
        self.assertEqual(data["checks"]["time"]["status"], "not_evaluated")
        self.assertEqual(data["checks"]["velocity"]["status"], "not_evaluated")
        self.assertEqual(data["anomalies"], [])
        self.assertEqual(data["baseline"]["completed_event_count"] > 50, True)

    def test_attack_scenario_with_timestamp(self):
        i = self._create(channel="WhatsApp", amount=1850000, beneficiary_name="Vendor X", beneficiary_is_new=True,
                         received_at="2026-10-07T12:00:00+05:30")
        data = self._behaviour(i)
        self.assertEqual({a["code"] for a in data["anomalies"]}, {"AMOUNT_ABOVE_BASELINE", "NEW_BENEFICIARY", "UNUSUAL_CHANNEL"})
        self.assertEqual(data["checks"]["amount"]["ratio_to_typical_max"], 9.25)

    def test_night_request_flags_time(self):
        data = self._behaviour(self._create(received_at="2026-10-07T23:30:00+05:30"))
        self.assertIn("UNUSUAL_TIME", {a["code"] for a in data["anomalies"]})

    def test_velocity_emerges_from_stored_incidents(self):
        self._create(received_at="2026-10-07T12:00:00+05:30")
        self._create(received_at="2026-10-07T12:04:00+05:30")
        third = self._create(received_at="2026-10-07T12:08:00+05:30")
        data = self._behaviour(third)
        self.assertIn("VELOCITY_ANOMALY", {a["code"] for a in data["anomalies"]})
        first = self._behaviour(1)
        self.assertNotIn("VELOCITY_ANOMALY", {a["code"] for a in first["anomalies"]})

    def test_incidents_without_received_at_do_not_count(self):
        for _ in range(3):
            self._create()
        last = self._create(received_at="2026-10-07T12:00:00+05:30")
        self.assertNotIn("VELOCITY_ANOMALY", {a["code"] for a in self._behaviour(last)["anomalies"]})

    def test_invalid_received_at_rejected(self):
        res = self.client.post("/api/incidents", json={**BASE, "received_at": "yesterday-ish"})
        self.assertEqual(res.status_code, 422)

    def test_received_at_round_trips_and_naive_is_utc(self):
        i = self._create(received_at="2026-10-07T06:30:00")
        got = self.client.get(f"/api/incidents/{i}").json()["data"]
        self.assertEqual(got["received_at"], "2026-10-07T06:30:00+00:00")


if __name__ == "__main__":
    unittest.main()
