"""v0.7.0 case workflow: persistence, audit trail, transitions and risk separation (stdlib + pydantic, no HTTP)."""

import os
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path

from app import case_repository, database, repository, risk_repository, seed
from app.errors import AppError, NotFoundError
from app.schemas import CaseDecisionRequest, IncidentCreate
from app.services import case_workflow as cw

from .test_risk_persistence import NORMAL, fake_result

REASON = "Confirmed the request with the sender through the corporate directory number."


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "t.db"
        database.init_db(self.path)
        self.conn = database.connect(self.path)
        self._saved = os.environ.get("TRUSTBREAK_AI_MODE")
        os.environ["TRUSTBREAK_AI_MODE"] = "mock"

    def tearDown(self):
        self.conn.close()
        self._tmp.cleanup()
        if self._saved is None:
            os.environ.pop("TRUSTBREAK_AI_MODE", None)
        else:
            os.environ["TRUSTBREAK_AI_MODE"] = self._saved

    def make(self, payload=NORMAL):
        return repository.create_incident(self.conn, payload)

    def rows(self, iid):
        return self.conn.execute("SELECT * FROM case_actions WHERE incident_id = ? ORDER BY id", (iid,)).fetchall()


class InitialStateTests(Base):
    def test_new_incident_starts_open_with_one_audit_row(self):
        inc = self.make()
        self.assertEqual((inc.workflow_status, inc.workflow_status_label), ("OPEN", "Open"))
        self.assertEqual(len(inc.case_history), 1)
        h = inc.case_history[0]
        self.assertEqual((h.previous_status, h.new_status, h.decision, h.analyst_name), (None, "OPEN", "CASE_OPENED", None))
        self.assertEqual(h.created_at, inc.created_at)

    def test_open_is_not_derived_from_risk_level(self):
        inc = self.make()
        risk_repository.save_risk_assessment(self.conn, inc.id, fake_result("CRITICAL", 90))
        got = repository.get_incident(self.conn, inc.id)
        self.assertEqual((got.risk_assessment.risk_level, got.workflow_status), ("CRITICAL", "OPEN"))

    def test_seeded_demo_incident_is_open(self):
        seed.seed_if_empty(self.conn)
        self.assertEqual(repository.get_incident(self.conn, 1).workflow_status, "OPEN")

    def test_incident_and_case_row_are_created_together(self):
        self.make()
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM case_actions").fetchone()[0], 1)

    def test_backfill_gives_pre_v070_incidents_a_case_row_and_is_idempotent(self):
        inc = self.make()
        self.conn.execute("DELETE FROM case_actions")  # simulate a database created by v0.6.0
        self.conn.commit()
        self.assertEqual(repository.get_incident(self.conn, inc.id).workflow_status, "OPEN")  # no rows still means OPEN
        database.init_db(self.path)
        database.init_db(self.path)
        rows = self.rows(inc.id)
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["decision"], rows[0]["created_at"]), ("CASE_OPENED", inc.created_at))


class DecisionPersistenceTests(Base):
    def test_decision_persists_and_updates_current_status(self):
        inc = self.make()
        cw.record_decision(self.conn, inc.id, "VERIFIED", REASON, "Security Analyst")
        self.conn.close()
        self.conn = database.connect(self.path)  # a brand new connection sees the persisted state
        got = repository.get_incident(self.conn, inc.id)
        self.assertEqual((got.workflow_status, got.workflow_status_label), ("VERIFIED", "Verified"))

    def test_audit_record_contents(self):
        inc = self.make()
        cw.record_decision(self.conn, inc.id, "REJECTED", REASON, "Security Analyst")
        r = self.rows(inc.id)[-1]
        self.assertEqual(
            (r["previous_status"], r["new_status"], r["decision"], r["reason"], r["analyst_name"]),
            ("OPEN", "REJECTED", "REJECTED", REASON, "Security Analyst"),
        )
        self.assertTrue(r["created_at"].endswith("Z"))

    def test_history_is_chronological_and_repeatable(self):
        inc = self.make()
        cw.record_decision(self.conn, inc.id, "VERIFIED", REASON, "A. Analyst")
        first = [h.model_dump() for h in repository.get_incident(self.conn, inc.id).case_history]
        second = [h.model_dump() for h in repository.get_incident(self.conn, inc.id).case_history]
        self.assertEqual(first, second)
        self.assertEqual([h["decision"] for h in first], ["CASE_OPENED", "VERIFIED"])
        self.assertEqual([h["new_status"] for h in first], ["OPEN", "VERIFIED"])
        self.assertLessEqual(first[0]["created_at"], first[1]["created_at"])
        self.assertEqual(first[1]["decision_label"], "Analyst verified the request")

    def test_history_does_not_expose_database_details(self):
        inc = self.make()
        self.assertEqual(
            set(repository.get_incident(self.conn, inc.id).case_history[0].model_dump()),
            {"previous_status", "new_status", "new_status_label", "decision", "decision_label", "reason",
             "analyst_name", "created_at", "assessment_id", "assessment_number", "assessment_risk_score",
             "assessment_risk_level"},
        )

    def test_decisions_are_per_incident(self):
        a, b = self.make(), self.make()
        cw.record_decision(self.conn, a.id, "VERIFIED", REASON, "Analyst")
        self.assertEqual(repository.get_incident(self.conn, a.id).workflow_status, "VERIFIED")
        self.assertEqual(repository.get_incident(self.conn, b.id).workflow_status, "OPEN")

    def test_list_and_summary_reflect_workflow_status(self):
        a, b, c = self.make(), self.make(), self.make()
        cw.record_decision(self.conn, a.id, "VERIFIED", REASON, "Analyst")
        cw.record_decision(self.conn, b.id, "REJECTED", REASON, "Analyst")
        by_id = {s.id: s.workflow_status for s in repository.list_incidents(self.conn)}
        self.assertEqual(by_id, {a.id: "VERIFIED", b.id: "REJECTED", c.id: "OPEN"})
        s = cw.case_summary(self.conn)
        self.assertEqual((s.total, s.open, s.verified, s.rejected), (3, 1, 1, 1))

    def test_summary_with_no_incidents_is_all_zero(self):
        s = cw.case_summary(self.conn)
        self.assertEqual((s.total, s.open, s.verified, s.rejected), (0, 0, 0, 0))


class TransitionTests(Base):
    def test_transition_table(self):
        self.assertTrue(cw.can_transition("OPEN", "VERIFIED"))
        self.assertTrue(cw.can_transition("OPEN", "REJECTED"))
        for current in ("VERIFIED", "REJECTED"):
            for target in ("OPEN", "VERIFIED", "REJECTED"):
                self.assertFalse(cw.can_transition(current, target), (current, target))

    def test_open_to_verified_and_open_to_rejected(self):
        for decision in ("VERIFIED", "REJECTED"):
            inc = self.make()
            cw.record_decision(self.conn, inc.id, decision, REASON, "Analyst")
            self.assertEqual(repository.get_incident(self.conn, inc.id).workflow_status, decision)

    def test_closed_cases_cannot_be_flipped_or_repeated(self):
        for first, second in (("VERIFIED", "REJECTED"), ("REJECTED", "VERIFIED"), ("VERIFIED", "VERIFIED")):
            inc = self.make()
            cw.record_decision(self.conn, inc.id, first, REASON, "Analyst")
            with self.assertRaises(AppError) as ctx:
                cw.record_decision(self.conn, inc.id, second, "A different reason entirely.", "Other")
            self.assertEqual((ctx.exception.code, ctx.exception.status_code), ("case_already_closed", 409))
            got = repository.get_incident(self.conn, inc.id)
            self.assertEqual(got.workflow_status, first)
            self.assertEqual(len(got.case_history), 2)  # the refused attempt left no trace

    def test_unknown_incident_is_not_found_and_writes_nothing(self):
        with self.assertRaises(NotFoundError):
            cw.record_decision(self.conn, 999, "VERIFIED", REASON, "Analyst")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM case_actions").fetchone()[0], 0)

    def test_invalid_decision_is_refused(self):
        inc = self.make()
        for bad in ("OPEN", "APPROVED", "", "verified", "CASE_OPENED"):
            with self.assertRaises(AppError) as ctx:
                cw.record_decision(self.conn, inc.id, bad, REASON, "Analyst")
            self.assertEqual(ctx.exception.status_code, 422)
        self.assertEqual(len(self.rows(inc.id)), 1)


class IntegrityTests(Base):
    def test_audit_rows_cannot_be_updated(self):
        inc = self.make()
        cw.record_decision(self.conn, inc.id, "VERIFIED", REASON, "Analyst")
        with self.assertRaises(sqlite3.DatabaseError):
            self.conn.execute("UPDATE case_actions SET reason = 'edited' WHERE incident_id = ?", (inc.id,))
        self.conn.rollback()
        self.assertEqual(self.rows(inc.id)[-1]["reason"], REASON)

    def test_database_allows_only_one_decision_per_case(self):
        inc = self.make()
        cw.record_decision(self.conn, inc.id, "VERIFIED", REASON, "Analyst")
        with self.assertRaises(sqlite3.IntegrityError):
            case_repository.append_action(
                self.conn, incident_id=inc.id, previous_status="VERIFIED", new_status="REJECTED",
                decision="REJECTED", reason=REASON, analyst_name="x", created_at="2026-10-03T00:00:00Z",
            )
        self.conn.rollback()

    def test_check_constraints_reject_arbitrary_status_strings(self):
        inc = self.make()
        with self.assertRaises(sqlite3.IntegrityError):
            case_repository.append_action(
                self.conn, incident_id=inc.id, previous_status="OPEN", new_status="APPROVED",
                decision="VERIFIED", reason=REASON, analyst_name="x", created_at="2026-10-03T00:00:00Z",
            )
        self.conn.rollback()

    def test_failed_write_rolls_back_atomically(self):
        inc = self.make()
        original = case_repository.append_action

        def boom(*a, **k):
            raise RuntimeError("disk on fire")

        case_repository.append_action = boom
        try:
            with self.assertRaises(RuntimeError):
                cw.record_decision(self.conn, inc.id, "VERIFIED", REASON, "Analyst")
        finally:
            case_repository.append_action = original
        self.assertFalse(self.conn.in_transaction)
        self.assertEqual(repository.get_incident(self.conn, inc.id).workflow_status, "OPEN")
        cw.record_decision(self.conn, inc.id, "VERIFIED", REASON, "Analyst")  # connection is still usable

    def test_concurrent_decisions_yield_exactly_one_winner(self):
        inc = self.make()
        results = []

        def attempt(decision):
            conn = database.connect(self.path)
            conn.execute("PRAGMA busy_timeout = 5000")
            try:
                cw.record_decision(conn, inc.id, decision, REASON, decision.title())
                results.append("ok")
            except AppError as exc:
                results.append(exc.code)
            finally:
                conn.close()

        threads = [threading.Thread(target=attempt, args=(d,)) for d in ("VERIFIED", "REJECTED") * 3]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual(results.count("ok"), 1)
        self.assertEqual(results.count("case_already_closed"), 5)
        self.assertEqual(len(self.rows(inc.id)), 2)


class RequestSchemaTests(unittest.TestCase):
    def ok(self, **over):
        return CaseDecisionRequest(**{"decision": "VERIFIED", "reason": REASON, "analyst_name": "Security Analyst", **over})

    def test_valid_and_trimmed(self):
        r = self.ok(reason="   " + REASON + "   ", analyst_name="  Security Analyst ")
        self.assertEqual((r.reason, r.analyst_name), (REASON, "Security Analyst"))

    def test_rejects_bad_input(self):
        from pydantic import ValidationError

        for over in (
            {"decision": "OPEN"}, {"decision": "APPROVED"}, {"decision": "verified"},
            {"reason": ""}, {"reason": "   \n\t  "}, {"reason": "too short"}, {"reason": "x" * 1001},
            {"analyst_name": ""}, {"analyst_name": "    "}, {"analyst_name": "A"}, {"analyst_name": "n" * 81},
            {"unexpected": "field"},
        ):
            with self.assertRaises(ValidationError, msg=over):
                self.ok(**over)


class RiskSeparationTests(Base):
    def snapshot(self, iid):
        # v0.8.0: assessments live in the append-only history; compare the whole history, not just the latest row.
        return [dict(r) for r in self.conn.execute("SELECT * FROM risk_assessment_history WHERE incident_id = ? ORDER BY id", (iid,))]

    def test_decision_leaves_the_risk_assessment_byte_for_byte_unchanged(self):
        inc = self.make()
        risk_repository.save_risk_assessment(self.conn, inc.id, fake_result("CRITICAL", 92, trust_break_detected=True))
        before = self.snapshot(inc.id)
        api_before = repository.get_incident(self.conn, inc.id).risk_assessment.model_dump()
        cw.record_decision(self.conn, inc.id, "REJECTED", REASON, "Security Analyst")
        self.assertEqual(self.snapshot(inc.id), before)  # score, raw_points, level, signals, inputs, version, timestamp
        got = repository.get_incident(self.conn, inc.id)
        self.assertEqual(got.risk_assessment.model_dump(), api_before)
        self.assertEqual((got.risk_assessment.risk_level, got.incident_status), ("CRITICAL", "hold_payment"))
        self.assertEqual(got.workflow_status, "REJECTED")

    def test_refused_decision_also_leaves_risk_unchanged(self):
        inc = self.make()
        risk_repository.save_risk_assessment(self.conn, inc.id, fake_result("HIGH", 60))
        cw.record_decision(self.conn, inc.id, "VERIFIED", REASON, "Analyst")
        before = self.snapshot(inc.id)
        with self.assertRaises(AppError):
            cw.record_decision(self.conn, inc.id, "REJECTED", REASON, "Analyst")
        self.assertEqual(self.snapshot(inc.id), before)

    def test_decision_does_not_create_an_assessment(self):
        inc = self.make()
        cw.record_decision(self.conn, inc.id, "VERIFIED", REASON, "Analyst")
        got = repository.get_incident(self.conn, inc.id)
        self.assertIsNone(got.risk_assessment)
        self.assertEqual(got.incident_status, "not_assessed")
        self.assertEqual(risk_repository.risk_summary(self.conn)["not_assessed"], 1)

    def test_risk_engine_does_not_import_the_case_workflow(self):
        root = Path(__file__).resolve().parent.parent / "app" / "services" / "risk_correlation"
        for f in root.glob("*.py"):
            text = f.read_text()
            self.assertNotIn("case_workflow", text, f.name)
            self.assertNotIn("case_repository", text, f.name)


if __name__ == "__main__":
    unittest.main()
