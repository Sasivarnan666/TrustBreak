"""HTTP tests: persisted risk assessment, incident status, list and dashboard summary."""

import io
import os
import sqlite3
import tempfile
import unittest
import zipfile
from pathlib import Path

try:
    from fastapi.testclient import TestClient

    HAVE_FASTAPI = True
except ImportError:  # pragma: no cover
    HAVE_FASTAPI = False

_ENV_KEYS = ("TRUSTBREAK_DB_PATH", "TRUSTBREAK_SEED_DEMO", "TRUSTBREAK_AI_MODE", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "TRUSTBREAK_AI_PROVIDER")

NORMAL = {
    "sender_name": "Arvind Rao", "sender_role": "Chief Executive Officer", "sender_known": True,
    "channel": "Email", "amount": 100000, "beneficiary_name": "Vendor A", "beneficiary_is_new": False,
    "message": "Please pay the monthly invoice as usual.",
}
MARKER = b"UNIQUE-ATTACHMENT-MARKER-7f3a9c"


def demo_zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("Statement.pdf", MARKER)
        z.writestr("Update.exe", MARKER)
        z.writestr("helper.dll", MARKER)
    return buf.getvalue()


@unittest.skipUnless(HAVE_FASTAPI, "fastapi/httpx not installed")
class PersistedRiskApiTests(unittest.TestCase):
    mode = "mock"

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "api.db"
        self._saved = {k: os.environ.get(k) for k in _ENV_KEYS}
        os.environ["TRUSTBREAK_DB_PATH"] = str(self.db_path)
        os.environ["TRUSTBREAK_SEED_DEMO"] = "1"
        os.environ["TRUSTBREAK_AI_MODE"] = self.mode
        os.environ.pop("ANTHROPIC_API_KEY", None)
        os.environ.pop("GEMINI_API_KEY", None)
        os.environ.pop("TRUSTBREAK_AI_PROVIDER", None)
        self._start()

    def _start(self):
        from app.main import create_app

        self._cm = TestClient(create_app())
        self.client = self._cm.__enter__()

    def _stop(self):
        self._cm.__exit__(None, None, None)

    def tearDown(self):
        self._stop()
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self._tmp.cleanup()

    def get(self, iid=1):
        return self.client.get(f"/api/incidents/{iid}").json()["data"]

    def run_risk(self, iid=1, **kw):
        return self.client.post(f"/api/incidents/{iid}/analyze-risk", **kw)


class PersistenceTests(PersistedRiskApiTests):
    def test_unassessed_incident_has_null_assessment_and_not_assessed_status(self):
        d = self.get()
        self.assertIsNone(d["risk_assessment"])
        self.assertEqual((d["incident_status"], d["incident_status_label"]), ("not_assessed", "Not assessed"))
        self.assertEqual(d["analysis"]["risk_status"], "needs_review")  # legacy stored field kept for compatibility

    def test_analyze_risk_persists_and_returns_the_persisted_assessment(self):
        res = self.run_risk()
        self.assertEqual(res.status_code, 200)
        data = res.json()["data"]
        self.assertTrue(data["persisted"])
        self.assertEqual((data["risk_level"], data["recommended_action"], data["incident_status"]), ("CRITICAL", "HOLD_PAYMENT", "hold_payment"))
        self.assertEqual(data["assessment_version"], "0.6.0")
        self.assertTrue(data["assessed_at"].endswith("Z"))
        self.assertEqual(data["incident_id"], 1)
        self.assertEqual(self.get()["risk_assessment"], data)  # GET returns exactly what was returned

    def test_demo_is_critical_hold_payment_trust_break_and_survives_refetch_and_restart(self):
        self.run_risk()
        for _ in range(2):  # repeated fresh GETs
            d = self.get()
            ra = d["risk_assessment"]
            self.assertEqual((ra["risk_level"], ra["recommended_action"]), ("CRITICAL", "HOLD_PAYMENT"))
            self.assertTrue(ra["trust_break_detected"])
            self.assertEqual(ra["headline"], "TRUST BREAK DETECTED")
            self.assertEqual(d["incident_status"], "hold_payment")
            self.assertGreaterEqual(len(ra["signals"]), 6)
            self.assertEqual(ra["inputs"]["message"]["status"], "used")
            self.assertEqual(ra["inputs"]["attachment"]["status"], "not_provided")
            self.assertIn("not proof of fraud", ra["disclaimer"])
            self.assertFalse(ra["payment_blocked"])
        saved = self.get()["risk_assessment"]
        self._stop()  # simulate a server restart on the same database file
        self._start()
        self.assertEqual(self.get()["risk_assessment"], saved)

    def test_normal_payment_is_low_proceed_and_persisted(self):
        iid = self.client.post("/api/incidents", json=NORMAL).json()["data"]["id"]
        data = self.run_risk(iid).json()["data"]
        self.assertEqual((data["risk_level"], data["recommended_action"], data["incident_status"]), ("LOW", "PROCEED", "proceed"))
        again = self.get(iid)
        self.assertEqual((again["risk_assessment"]["risk_level"], again["incident_status"]), ("LOW", "proceed"))

    def test_run_again_replaces_the_latest_snapshot(self):
        first = self.run_risk().json()["data"]
        self.assertEqual(first["risk_score"], 85)
        second = self.run_risk(files={"file": ("RBI_Statement.zip", demo_zip(), "application/zip")}).json()["data"]
        self.assertEqual((second["risk_score"], second["raw_points"]), (100, 130))
        self.assertEqual(second["inputs"]["attachment"]["status"], "used")
        stored = self.get()["risk_assessment"]
        self.assertEqual(stored, second)
        self.assertGreaterEqual(stored["assessed_at"], first["assessed_at"])
        with sqlite3.connect(self.db_path) as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM risk_assessments").fetchone()[0], 1)

    def test_attachment_bytes_are_never_stored(self):
        self.run_risk(files={"file": ("RBI_Statement.zip", demo_zip(), "application/zip")})
        with sqlite3.connect(self.db_path) as c:
            for table in ("incidents", "risk_assessments"):
                for row in c.execute(f"SELECT * FROM {table}"):
                    for cell in row:
                        blob = cell if isinstance(cell, bytes) else str(cell).encode()
                        self.assertNotIn(MARKER, blob)
                        self.assertNotIn(b"PK\x03\x04", blob)
            self.assertFalse(any(r[2] == "BLOB" for r in c.execute("PRAGMA table_info(risk_assessments)")))
        # the data directory holds only the database (no extracted/uploaded file)
        self.assertEqual({p.name for p in Path(self._tmp.name).iterdir() if p.is_file() and p.suffix not in ("", ".db")}, set())
        # but derived structured evidence (file names) is stored
        ra = self.get()["risk_assessment"]
        self.assertTrue(any("Update.exe" in s["details"] for s in ra["signals"]))

    def test_bad_file_does_not_overwrite_or_create_an_assessment(self):
        res = self.run_risk(files={"file": ("a.zip", b"", "application/zip")})
        self.assertEqual((res.status_code, res.json()["error"]["code"]), (400, "empty_file"))
        self.assertIsNone(self.get()["risk_assessment"])
        self.run_risk()
        before = self.get()["risk_assessment"]
        self.run_risk(files={"file": ("a.zip", b"", "application/zip")})
        self.assertEqual(self.get()["risk_assessment"], before)

    def test_error_envelopes_for_bad_ids_and_methods(self):
        self.assertEqual(self.run_risk(9999).status_code, 404)
        self.assertEqual(self.run_risk(0).status_code, 422)
        self.assertEqual(self.client.post("/api/incidents/abc/analyze-risk").status_code, 422)
        self.assertEqual(self.client.get("/api/incidents/1/analyze-risk").status_code, 405)
        res = self.client.get("/api/incidents/9999")
        self.assertEqual((res.status_code, res.json()["error"]["code"]), (404, "not_found"))
        self.assertEqual(self.client.get("/api/incidents/0").status_code, 422)
        with sqlite3.connect(self.db_path) as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM risk_assessments").fetchone()[0], 0)

    def test_existing_endpoints_still_work(self):
        self.assertEqual(self.client.get("/api/health").status_code, 200)
        self.assertEqual(self.client.get("/api/incidents").status_code, 200)
        self.assertEqual(self.client.post("/api/incidents", json=NORMAL).status_code, 201)
        for ep in ("analyze-message", "analyze-behaviour"):
            self.assertEqual(self.client.post(f"/api/incidents/1/{ep}").status_code, 200)
        self.assertEqual(self.client.post("/api/incidents/1/analyze-message").json()["data"]["is_final_decision"], False)
        self.assertEqual(self.client.post("/api/incidents", json={**NORMAL, "amount": -1}).status_code, 422)


class ListAndSummaryTests(PersistedRiskApiTests):
    def test_list_shows_not_assessed_then_real_state(self):
        row = self.client.get("/api/incidents").json()["data"][0]
        self.assertEqual((row["incident_status"], row["incident_status_label"], row["risk_level"], row["recommended_action"]),
                         ("not_assessed", "Not assessed", None, None))
        self.run_risk()
        row = self.client.get("/api/incidents").json()["data"][0]
        self.assertEqual((row["risk_level"], row["recommended_action"], row["incident_status"], row["risk_score"]),
                         ("CRITICAL", "HOLD_PAYMENT", "hold_payment", 85))
        self.assertTrue(row["trust_break_detected"])
        self.assertTrue(row["assessed_at"])

    def test_list_mixes_assessed_and_unassessed(self):
        new = self.client.post("/api/incidents", json=NORMAL).json()["data"]["id"]
        self.run_risk(new)
        rows = {r["id"]: r for r in self.client.get("/api/incidents").json()["data"]}
        self.assertEqual(rows[new]["risk_level"], "LOW")
        self.assertEqual(rows[1]["incident_status"], "not_assessed")

    def test_dashboard_summary_zero_without_assessments(self):
        s = self.client.get("/api/incidents/risk-summary").json()["data"]
        self.assertEqual(s, {"total": 1, "critical": 0, "high": 0, "medium": 0, "low": 0, "assessed": 0, "not_assessed": 1})

    def test_dashboard_summary_reflects_persisted_assessments(self):
        self.run_risk()
        new = self.client.post("/api/incidents", json=NORMAL).json()["data"]["id"]
        self.run_risk(new)
        self.client.post("/api/incidents", json=NORMAL)
        s = self.client.get("/api/incidents/risk-summary").json()["data"]
        self.assertEqual(s, {"total": 3, "critical": 1, "high": 0, "medium": 0, "low": 1, "assessed": 2, "not_assessed": 1})

    def test_summary_route_is_not_shadowed_by_id_route(self):
        res = self.client.get("/api/incidents/risk-summary")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json()["success"])


class IncompleteEvidenceTests(PersistedRiskApiTests):
    mode = "ai"  # no API key -> message analysis unavailable

    def test_unavailable_message_analysis_is_returned_but_not_persisted(self):
        res = self.run_risk()
        self.assertEqual(res.status_code, 200)  # existing unavailable-input behaviour preserved
        data = res.json()["data"]
        self.assertEqual(data["inputs"]["message"]["status"], "unavailable")
        self.assertFalse(data["persisted"])
        self.assertIsNone(data["assessed_at"])
        self.assertTrue(any("not saved" in n for n in data["notes"]))
        d = self.get()
        self.assertIsNone(d["risk_assessment"])
        self.assertEqual(d["incident_status"], "not_assessed")

    def test_unavailable_run_leaves_earlier_assessment_unchanged(self):
        from app import database, repository, risk_repository
        from app.services.risk_correlation import assess_incident_risk

        os.environ["TRUSTBREAK_AI_MODE"] = "mock"
        self.run_risk()
        good = self.get()["risk_assessment"]
        os.environ["TRUSTBREAK_AI_MODE"] = "ai"
        self.assertFalse(self.run_risk().json()["data"]["persisted"])
        self.assertEqual(self.get()["risk_assessment"], good)


if __name__ == "__main__":
    unittest.main()
