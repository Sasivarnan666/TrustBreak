"""P1.1 - immutable assessment history and decision-to-assessment linkage (v0.8.0). Synthetic data only."""

import os
import re
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path

from app import database, repository, risk_repository
from app.errors import AppError
from app.services import case_workflow as cw

from .test_assessment_integrity import make_zip
from .test_case_workflow import REASON
from .test_risk_persistence import NORMAL, fake_result

try:
    from fastapi.testclient import TestClient

    HAVE_FASTAPI = True
except ImportError:  # pragma: no cover
    HAVE_FASTAPI = False


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "h.db"
        database.init_db(self.path)
        self.conn = database.connect(self.path)

    def tearDown(self):
        self.conn.close()
        self._tmp.cleanup()

    def make(self):
        return repository.create_incident(self.conn, NORMAL).id

    def save(self, iid, level="HIGH", score=55, **kw):
        return risk_repository.save_risk_assessment(self.conn, iid, fake_result(level, score), **kw)


class VersioningTests(Base):
    def test_each_run_appends_a_numbered_assessment(self):
        iid = self.make()
        got = [self.save(iid, "LOW", 10), self.save(iid, "HIGH", 55), self.save(iid, "CRITICAL", 100)]
        self.assertEqual([g.version_number for g in got], [1, 2, 3])
        self.assertEqual(len({g.assessment_id for g in got}), 3)
        self.assertTrue(all(g.engine_version == risk_repository.ASSESSMENT_VERSION for g in got))
        self.assertEqual(got[0].assessment_version, got[0].engine_version)  # legacy field kept
        history = risk_repository.list_assessment_history(self.conn, iid)
        self.assertEqual([(h.version_number, h.risk_level, h.is_latest) for h in history],
                         [(1, "LOW", False), (2, "HIGH", False), (3, "CRITICAL", True)])

    def test_numbering_is_per_incident(self):
        a, b = self.make(), self.make()
        self.save(a), self.save(a)
        self.assertEqual(self.save(b).version_number, 1)
        self.assertEqual(self.save(a).version_number, 3)

    def test_old_versions_are_returned_exactly_as_stored(self):
        iid = self.make()
        first = self.save(iid, "LOW", 10, assessed_at="2026-10-01T09:00:00Z")
        self.save(iid, "CRITICAL", 100)
        again = risk_repository.get_assessment_version(self.conn, iid, 1)
        self.assertEqual(again.model_dump() | {"is_latest": None}, first.model_dump() | {"is_latest": None})
        self.assertFalse(again.is_latest)
        self.assertIsNone(risk_repository.get_assessment_version(self.conn, iid, 9))

    def test_rows_cannot_be_updated(self):
        iid = self.make()
        self.save(iid)
        with self.assertRaises(sqlite3.DatabaseError) as ctx:
            self.conn.execute("UPDATE risk_assessment_history SET risk_score = 0 WHERE incident_id = ?", (iid,))
        self.assertIn("immutable", str(ctx.exception))

    def test_latest_drives_list_status_and_summary_but_counts_each_incident_once(self):
        iid = self.make()
        self.save(iid, "LOW", 10)
        self.save(iid, "CRITICAL", 100)
        row = repository.list_incidents(self.conn)[0]
        self.assertEqual((row.risk_level, row.risk_score), ("CRITICAL", 100))
        self.assertEqual(repository.get_incident(self.conn, iid).incident_status, "hold_payment")
        summary = risk_repository.risk_summary(self.conn)
        self.assertEqual((summary["assessed"], summary["critical"], summary["low"]), (1, 1, 0))

    def test_incident_detail_carries_the_timeline(self):
        iid = self.make()
        self.save(iid, "LOW", 10), self.save(iid, "HIGH", 60)
        detail = repository.get_incident(self.conn, iid)
        self.assertEqual([h.version_number for h in detail.assessment_history], [1, 2])
        self.assertEqual(detail.risk_assessment.version_number, 2)

    def test_concurrent_runs_never_share_a_version_number(self):
        iid = self.make()
        errors = []

        def run():
            conn = database.connect(self.path)
            try:
                conn.execute("PRAGMA busy_timeout = 5000")
                risk_repository.save_risk_assessment(conn, iid, fake_result("HIGH", 55))
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)
            finally:
                conn.close()

        threads = [threading.Thread(target=run) for _ in range(8)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual(errors, [])
        self.assertEqual([h.version_number for h in risk_repository.list_assessment_history(self.conn, iid)], list(range(1, 9)))


class DecisionLinkageTests(Base):
    def test_decision_records_the_exact_latest_assessment(self):
        iid = self.make()
        self.save(iid, "LOW", 10)
        v2 = self.save(iid, "CRITICAL", 100)
        cw.record_decision(self.conn, iid, "REJECTED", REASON, "Analyst")
        action = repository.get_incident(self.conn, iid).case_history[-1]
        self.assertEqual((action.assessment_id, action.assessment_number, action.assessment_risk_score, action.assessment_risk_level),
                         (v2.assessment_id, 2, 100, "CRITICAL"))
        self.assertIsNone(repository.get_incident(self.conn, iid).case_history[0].assessment_id)  # CASE_OPENED

    def test_a_later_assessment_does_not_change_what_the_decision_was_based_on(self):
        iid = self.make()
        v1 = self.save(iid, "HIGH", 70)
        cw.record_decision(self.conn, iid, "VERIFIED", REASON, "Analyst")
        self.save(iid, "LOW", 5)
        action = repository.get_incident(self.conn, iid).case_history[-1]
        self.assertEqual((action.assessment_id, action.assessment_number, action.assessment_risk_level), (v1.assessment_id, 1, "HIGH"))

    def test_explicit_id_must_be_the_latest(self):
        iid = self.make()
        v1 = self.save(iid)
        v2 = self.save(iid, "CRITICAL", 100)
        with self.assertRaises(AppError) as ctx:
            cw.record_decision(self.conn, iid, "VERIFIED", REASON, "Analyst", v1.assessment_id)
        self.assertEqual((ctx.exception.code, ctx.exception.status_code), ("assessment_superseded", 409))
        self.assertEqual(repository.get_incident(self.conn, iid).workflow_status, "OPEN")  # nothing written
        cw.record_decision(self.conn, iid, "VERIFIED", REASON, "Analyst", v2.assessment_id)
        self.assertEqual(repository.get_incident(self.conn, iid).case_history[-1].assessment_number, 2)

    def test_foreign_or_unknown_assessment_ids_are_rejected(self):
        a, b = self.make(), self.make()
        self.save(a)
        other = self.save(b)
        for bad in (other.assessment_id, 99999):
            with self.assertRaises(AppError) as ctx:
                cw.record_decision(self.conn, a, "VERIFIED", REASON, "Analyst", bad)
            self.assertEqual((ctx.exception.code, ctx.exception.status_code), ("assessment_not_found", 422))
        self.assertEqual(repository.get_incident(self.conn, a).workflow_status, "OPEN")

    def test_decision_without_any_assessment_is_allowed_and_unlinked(self):
        iid = self.make()
        cw.record_decision(self.conn, iid, "REJECTED", REASON, "Analyst")
        self.assertIsNone(repository.get_incident(self.conn, iid).case_history[-1].assessment_id)

    def test_decision_never_touches_the_history(self):
        iid = self.make()
        self.save(iid, "HIGH", 70)
        before = [tuple(r) for r in self.conn.execute("SELECT * FROM risk_assessment_history ORDER BY id")]
        cw.record_decision(self.conn, iid, "VERIFIED", REASON, "Analyst")
        self.assertEqual([tuple(r) for r in self.conn.execute("SELECT * FROM risk_assessment_history ORDER BY id")], before)


class MigrationTests(unittest.TestCase):
    """A database created by 0.7.x must upgrade in place without losing its assessment or audit rows."""

    def old_schema(self):
        s = database.SCHEMA
        a, b = s.index("-- v0.8.0: IMMUTABLE"), s.index("-- v0.7.0: append-only")
        s = s[:a] + s[b:]
        s, n = re.subn(r",\n    assessment_id\s+INTEGER REFERENCES[^\n]*", "", s)
        self.assertEqual(n, 1)
        return s

    def test_upgrade_backfills_version_1_and_adds_the_link_column(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "old.db"
            database.init_db(path)  # brings a clean DB to the current schema
            # build the "old" state on top of a real incident created by the app
            conn = database.connect(path)
            inc = repository.create_incident(conn, NORMAL)
            risk_repository.save_risk_assessment(conn, inc.id, fake_result("CRITICAL", 100), assessed_at="2026-10-01T09:00:00Z")
            row = dict(conn.execute("SELECT * FROM risk_assessment_history").fetchone())
            conn.close()

            old = Path(tmp) / "old2.db"
            c = sqlite3.connect(old)
            c.executescript(self.old_schema())
            c.row_factory = sqlite3.Row
            src = sqlite3.connect(path)
            src.row_factory = sqlite3.Row
            irow = dict(src.execute("SELECT * FROM incidents WHERE id = ?", (inc.id,)).fetchone())
            c.execute(f"INSERT INTO incidents ({','.join(irow)}) VALUES ({','.join('?' * len(irow))})", tuple(irow.values()))
            legacy = {k: v for k, v in row.items() if k not in ("id", "version_number", "engine_version")}
            legacy["assessment_version"] = row["engine_version"]
            c.execute(f"INSERT INTO risk_assessments ({','.join(legacy)}) VALUES ({','.join('?' * len(legacy))})", tuple(legacy.values()))
            c.execute("INSERT INTO case_actions (incident_id, previous_status, new_status, decision, reason, analyst_name, created_at) "
                      "VALUES (?, 'OPEN', 'VERIFIED', 'VERIFIED', 'old decision recorded before 0.8.0', 'Old Analyst', '2026-10-01T10:00:00Z')", (inc.id,))
            c.commit()
            c.close()
            src.close()

            for _ in range(2):  # idempotent
                database.init_db(old)
            conn = database.connect(old)
            history = risk_repository.list_assessment_history(conn, inc.id)
            self.assertEqual([(h.version_number, h.risk_score, h.assessed_at) for h in history], [(1, 100, "2026-10-01T09:00:00Z")])
            detail = repository.get_incident(conn, inc.id)
            self.assertEqual((detail.risk_assessment.version_number, detail.risk_assessment.risk_level), (1, "CRITICAL"))
            old_decision = [a for a in detail.case_history if a.decision == "VERIFIED"][0]
            self.assertIsNone(old_decision.assessment_id)  # honest: it was not linked when it was recorded
            self.assertEqual(risk_repository.risk_summary(conn)["critical"], 1)
            new = risk_repository.save_risk_assessment(conn, inc.id, fake_result("LOW", 5))
            self.assertEqual(new.version_number, 2)
            conn.close()


@unittest.skipUnless(HAVE_FASTAPI, "fastapi/httpx not installed")
class HistoryApiTests(unittest.TestCase):
    ENV = ("TRUSTBREAK_DB_PATH", "TRUSTBREAK_SEED_DEMO", "TRUSTBREAK_AI_MODE", "GEMINI_API_KEY", "ANTHROPIC_API_KEY", "TRUSTBREAK_AI_PROVIDER")

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._saved = {k: os.environ.get(k) for k in self.ENV}
        os.environ.update(TRUSTBREAK_DB_PATH=str(Path(self._tmp.name) / "a.db"), TRUSTBREAK_SEED_DEMO="1", TRUSTBREAK_AI_MODE="mock")
        for k in ("GEMINI_API_KEY", "ANTHROPIC_API_KEY", "TRUSTBREAK_AI_PROVIDER"):
            os.environ.pop(k, None)
        from app.main import create_app

        self._cm = TestClient(create_app())
        self.c = self._cm.__enter__()

    def tearDown(self):
        self._cm.__exit__(None, None, None)
        for k, v in self._saved.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        self._tmp.cleanup()

    def files(self):
        return {"file": ("RBI_Statement.zip", make_zip("Statement.pdf", "Update.exe", "helper.dll"), "application/zip")}

    def run_risk(self, with_file=False):
        res = self.c.post("/api/incidents/1/analyze-risk", files=self.files() if with_file else None)
        self.assertEqual(res.status_code, 200)
        return res.json()["data"]

    def test_demo_flow_v1_v2_v3_and_decision_on_v3(self):
        a = self.run_risk()  # message + behaviour only
        b = self.run_risk(with_file=True)
        c = self.run_risk(with_file=True)
        self.assertEqual([x["version_number"] for x in (a, b, c)], [1, 2, 3])
        self.assertEqual([x["risk_score"] for x in (a, b, c)], [93, 100, 100])
        hist = self.c.get("/api/incidents/1/assessments").json()["data"]
        self.assertEqual([(h["version_number"], h["risk_score"], h["risk_level"], h["is_latest"]) for h in hist],
                         [(1, 93, "CRITICAL", False), (2, 100, "CRITICAL", False), (3, 100, "CRITICAL", True)])
        res = self.c.post("/api/incidents/1/decision", json={"decision": "REJECTED", "reason": REASON, "analyst_name": "Priya Nair", "assessment_id": c["assessment_id"]})
        self.assertEqual(res.status_code, 200)
        last = res.json()["data"]["case_history"][-1]
        self.assertEqual((last["decision"], last["assessment_number"], last["assessment_risk_score"], last["assessment_risk_level"]), ("REJECTED", 3, 100, "CRITICAL"))

    def test_rerun_without_the_file_no_longer_loses_the_attachment_evidence(self):
        self.run_risk(with_file=True)
        self.run_risk(with_file=False)
        v1 = self.c.get("/api/incidents/1/assessments/1").json()["data"]
        v2 = self.c.get("/api/incidents/1/assessments/2").json()["data"]
        self.assertEqual(v1["inputs"]["attachment"]["status"], "used")
        self.assertTrue(any(s["analyzer"] == "attachment" for s in v1["signals"]))
        self.assertEqual(v2["inputs"]["attachment"]["status"], "not_provided")
        self.assertGreater(v1["risk_score"], v2["risk_score"])
        self.assertEqual((v1["is_latest"], v2["is_latest"]), (False, True))

    def test_stale_assessment_id_is_a_409_and_writes_nothing(self):
        v1 = self.run_risk()
        self.run_risk(with_file=True)
        res = self.c.post("/api/incidents/1/decision", json={"decision": "VERIFIED", "reason": REASON, "analyst_name": "Priya Nair", "assessment_id": v1["assessment_id"]})
        body = res.json()
        self.assertEqual((res.status_code, body["error"]["code"]), (409, "assessment_superseded"))
        self.assertEqual(self.c.get("/api/incidents/1").json()["data"]["workflow_status"], "OPEN")

    def test_unknown_resources_and_bad_ids(self):
        self.assertEqual(self.c.get("/api/incidents/999/assessments").status_code, 404)
        self.assertEqual(self.c.get("/api/incidents/999/assessments/1").status_code, 404)
        self.assertEqual(self.c.get("/api/incidents/1/assessments").json()["data"], [])
        self.assertEqual(self.c.get("/api/incidents/1/assessments/1").status_code, 404)
        self.assertEqual(self.c.post("/api/incidents/1/decision", json={"decision": "VERIFIED", "reason": REASON, "analyst_name": "Priya Nair", "assessment_id": 0}).status_code, 422)

    def test_detail_exposes_history_and_latest_identity(self):
        self.run_risk(), self.run_risk(with_file=True)
        d = self.c.get("/api/incidents/1").json()["data"]
        self.assertEqual([h["version_number"] for h in d["assessment_history"]], [1, 2])
        self.assertEqual((d["risk_assessment"]["version_number"], d["risk_assessment"]["is_latest"]), (2, True))
        row = next(i for i in self.c.get("/api/incidents").json()["data"] if i["id"] == 1)
        self.assertEqual(row["risk_score"], d["risk_assessment"]["risk_score"])

    def test_unsaved_result_has_no_history_identity(self):
        # AI-only mode with no key: the message input is unavailable, so the engine result is incomplete and NOT saved.
        os.environ["TRUSTBREAK_AI_MODE"] = "ai"
        res = self.c.post("/api/incidents/1/analyze-risk")
        data = res.json()["data"]
        self.assertEqual((res.status_code, data["persisted"]), (200, False))
        self.assertIsNone(data["assessment_id"])
        self.assertIsNone(data["version_number"])
        self.assertEqual(self.c.get("/api/incidents/1/assessments").json()["data"], [])
        self.assertIsNone(self.c.get("/api/incidents/1").json()["data"]["risk_assessment"])


if __name__ == "__main__":
    unittest.main()
