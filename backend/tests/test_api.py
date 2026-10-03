"""HTTP API tests (envelope shape, status codes, validation errors).

Requires fastapi + httpx (pip install -r requirements-dev.txt). Skipped
automatically if they are not installed.
"""

import os
import tempfile
import unittest
from pathlib import Path

try:
    from fastapi.testclient import TestClient

    HAVE_FASTAPI = True
except ImportError:  # pragma: no cover
    HAVE_FASTAPI = False

from tests.test_core import valid_payload


@unittest.skipUnless(HAVE_FASTAPI, "fastapi/httpx not installed")
class ApiTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._saved = {k: os.environ.get(k) for k in ("TRUSTBREAK_DB_PATH", "TRUSTBREAK_SEED_DEMO")}
        os.environ["TRUSTBREAK_DB_PATH"] = str(Path(self._tmp.name) / "api.db")
        os.environ["TRUSTBREAK_SEED_DEMO"] = "1"

        from app.main import create_app

        self._client_cm = TestClient(create_app())
        self.client = self._client_cm.__enter__()  # runs lifespan: init db + seed

    def tearDown(self):
        self._client_cm.__exit__(None, None, None)
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self._tmp.cleanup()

    def test_health(self):
        body = self.client.get("/api/health").json()
        self.assertTrue(body["success"])
        self.assertEqual(body["data"]["status"], "ok")

    def test_list_contains_seeded_demo_incident(self):
        res = self.client.get("/api/incidents")
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertTrue(body["success"])
        self.assertEqual(body["meta"]["total"], 1)
        row = body["data"][0]
        self.assertEqual(row["reference"], "TB-0001")
        self.assertEqual(row["amount"], 1850000)
        self.assertEqual(row["risk_status"], "needs_review")

    def test_get_demo_incident_detail(self):
        res = self.client.get("/api/incidents/1")
        self.assertEqual(res.status_code, 200)
        data = res.json()["data"]
        self.assertEqual(data["channel"], "WhatsApp")
        self.assertEqual(data["payment"]["beneficiary_name"], "New Vendor X")
        self.assertEqual(data["attachment"]["name"], "RBI_Statement.zip")
        self.assertEqual(data["analysis"]["mode"], "placeholder")
        self.assertTrue(data["analysis"]["recommended_action"])

    def test_create_incident_returns_201_and_is_listed(self):
        res = self.client.post("/api/incidents", json=valid_payload())
        self.assertEqual(res.status_code, 201)
        created = res.json()["data"]
        self.assertEqual(created["id"], 2)
        listing = self.client.get("/api/incidents").json()
        self.assertEqual(listing["meta"]["total"], 2)
        self.assertEqual(listing["data"][0]["id"], 2)  # newest first

    def test_create_invalid_returns_422_envelope_with_field_details(self):
        res = self.client.post("/api/incidents", json=valid_payload(amount=0, channel="Pigeon"))
        self.assertEqual(res.status_code, 422)
        body = res.json()
        self.assertFalse(body["success"])
        self.assertEqual(body["error"]["code"], "validation_error")
        fields = {d["field"] for d in body["error"]["details"]}
        self.assertTrue({"amount", "channel"} <= fields)

    def test_create_with_malformed_json_is_enveloped(self):
        res = self.client.post("/api/incidents", content="{not json", headers={"Content-Type": "application/json"})
        self.assertEqual(res.status_code, 422)
        self.assertFalse(res.json()["success"])

    def test_missing_incident_is_404_envelope(self):
        res = self.client.get("/api/incidents/9999")
        self.assertEqual(res.status_code, 404)
        self.assertEqual(res.json()["error"]["code"], "not_found")

    def test_bad_id_is_validation_error(self):
        res = self.client.get("/api/incidents/abc")
        self.assertEqual(res.status_code, 422)
        self.assertEqual(res.json()["error"]["code"], "validation_error")

    def test_unknown_route_uses_error_envelope(self):
        res = self.client.get("/api/nope")
        self.assertEqual(res.status_code, 404)
        self.assertEqual(res.json()["error"]["code"], "not_found")

    def test_list_limit_is_validated(self):
        self.assertEqual(self.client.get("/api/incidents?limit=0").status_code, 422)


if __name__ == "__main__":
    unittest.main()
