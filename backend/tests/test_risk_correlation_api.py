"""HTTP tests for POST /api/incidents/{id}/analyze-risk (skipped without FastAPI/httpx)."""

import io
import os
import tempfile
import unittest
import zipfile
from pathlib import Path

try:
    from fastapi.testclient import TestClient

    HAVE_FASTAPI = True
except ImportError:  # pragma: no cover
    HAVE_FASTAPI = False

_ENV_KEYS = ("TRUSTBREAK_DB_PATH", "TRUSTBREAK_SEED_DEMO", "TRUSTBREAK_AI_MODE")

NORMAL = {
    "sender_name": "Arvind Rao", "sender_role": "Chief Executive Officer", "sender_known": True,
    "channel": "Email", "amount": 100000, "beneficiary_name": "Vendor A", "beneficiary_is_new": False,
    "message": "Please pay the monthly invoice as usual.",
}


def demo_zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name in ("Statement.pdf", "Update.exe", "helper.dll"):
            z.writestr(name, "inert placeholder")
    return buf.getvalue()


@unittest.skipUnless(HAVE_FASTAPI, "fastapi/httpx not installed")
class AnalyzeRiskApiTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._saved = {k: os.environ.get(k) for k in _ENV_KEYS}
        os.environ["TRUSTBREAK_DB_PATH"] = str(Path(self._tmp.name) / "api.db")
        os.environ["TRUSTBREAK_SEED_DEMO"] = "1"
        os.environ["TRUSTBREAK_AI_MODE"] = "mock"
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

    def test_demo_without_file(self):
        res = self.client.post("/api/incidents/1/analyze-risk")
        self.assertEqual(res.status_code, 200)
        data = res.json()["data"]
        self.assertEqual((data["risk_level"], data["recommended_action"]), ("CRITICAL", "HOLD_PAYMENT"))
        self.assertEqual(data["inputs"]["attachment"]["status"], "not_provided")
        self.assertTrue(data["trust_break_detected"])

    def test_demo_with_attachment(self):
        res = self.client.post("/api/incidents/1/analyze-risk",
                               files={"file": ("RBI_Statement.zip", demo_zip(), "application/zip")})
        self.assertEqual(res.status_code, 200)
        data = res.json()["data"]
        self.assertEqual((data["risk_score"], data["raw_points"], data["risk_level"]), (100, 130, "CRITICAL"))
        self.assertEqual(data["inputs"]["attachment"]["status"], "used")
        by_code = {s["code"]: s for s in data["signals"]}
        self.assertEqual(sorted(by_code["EXECUTABLE_ATTACHMENT"]["details"]), ["Update.exe", "helper.dll"])
        self.assertTrue(data["is_final_decision"])
        self.assertFalse(data["payment_blocked"])
        self.assertIn("not proof of fraud", data["disclaimer"])

    def test_normal_payment_is_low(self):
        created = self.client.post("/api/incidents", json=NORMAL).json()["data"]
        data = self.client.post(f"/api/incidents/{created['id']}/analyze-risk").json()["data"]
        self.assertEqual((data["risk_score"], data["risk_level"], data["recommended_action"]), (10, "LOW", "PROCEED"))
        self.assertEqual([s["code"] for s in data["signals"]], ["FINANCIAL_TRANSFER_INTENT"])

    def test_invalid_file_uses_the_error_envelope(self):
        res = self.client.post("/api/incidents/1/analyze-risk", files={"file": ("a.zip", b"", "application/zip")})
        self.assertEqual(res.status_code, 400)
        body = res.json()
        self.assertFalse(body["success"])
        self.assertEqual(body["error"]["code"], "empty_file")

    def test_not_found_bad_id_and_method(self):
        self.assertEqual(self.client.post("/api/incidents/9999/analyze-risk").status_code, 404)
        self.assertEqual(self.client.post("/api/incidents/0/analyze-risk").status_code, 422)
        self.assertEqual(self.client.get("/api/incidents/1/analyze-risk").status_code, 405)

    def test_nothing_is_stored_and_existing_endpoints_are_unchanged(self):
        before = self.client.get("/api/incidents/1").json()["data"]
        self.client.post("/api/incidents/1/analyze-risk")
        after = self.client.get("/api/incidents/1").json()["data"]
        self.assertEqual(before, after)
        self.assertEqual(after["analysis"]["mode"], "placeholder")
        self.assertEqual(self.client.get("/api/health").status_code, 200)
        self.assertEqual(self.client.post("/api/incidents/1/analyze-message").status_code, 200)
        self.assertEqual(self.client.post("/api/incidents/1/analyze-behaviour").status_code, 200)


if __name__ == "__main__":
    unittest.main()
