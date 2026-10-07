"""Repository / status-mapping tests for persisted risk assessments (stdlib + pydantic, no HTTP)."""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from app import database, repository, risk_repository, seed
from app.schemas import IncidentCreate
from app.services.risk_correlation import assess_incident_risk
from app.services.risk_correlation.incident_status import (
    NOT_ASSESSED,
    STATUS_FOR_LEVEL,
    label_for_status,
    status_for_level,
)

import os

NORMAL = IncidentCreate(
    sender_name="Arvind Rao", sender_role="Chief Executive Officer", sender_known=True, channel="Email",
    amount=100000, beneficiary_name="Vendor A", beneficiary_is_new=False,
    message="Please pay the monthly invoice as usual.",
)


def fake_result(level="HIGH", score=55, **over) -> dict:
    base = {
        "risk_score": score, "raw_points": score, "max_score": 100, "risk_level": level,
        "recommended_action": {"LOW": "PROCEED", "CRITICAL": "HOLD_PAYMENT"}.get(level, "VERIFY"),
        "recommended_action_label": "x", "recommended_action_guidance": "guidance",
        "trust_break_detected": False, "headline": "Elevated risk indicators", "explanation": "because",
        "signals": [{"code": "S", "category": "c", "source": "message", "severity": "low", "points": 10,
                     "title": "t", "message": "m", "details": []}],
        "category_points": {"c": 10}, "inputs": {"message": {"status": "used", "detail": "d"}},
        "thresholds": [{"min_score": 0, "level": "LOW"}], "notes": ["n"], "scoring_method": "heuristic_points",
        "disclaimer": "not proof of fraud",
    }
    base.update(over)
    return base


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
        return repository.create_incident(self.conn, payload).id


class SchemaTests(Base):
    def test_table_is_created_with_expected_columns(self):
        cols = {r["name"] for r in self.conn.execute("PRAGMA table_info(risk_assessments)")}
        for name in ("incident_id", "risk_score", "raw_points", "max_score", "risk_level", "recommended_action",
                     "trust_break_detected", "headline", "explanation", "recommended_action_guidance",
                     "signals_json", "inputs_json", "notes_json", "disclaimer", "assessed_at", "assessment_version"):
            self.assertIn(name, cols)

    def test_init_db_is_idempotent_and_keeps_existing_rows(self):
        iid = self.make()
        risk_repository.save_risk_assessment(self.conn, iid, fake_result())
        database.init_db(self.path)
        self.assertIsNotNone(risk_repository.get_latest_risk_assessment(self.conn, iid))

    def test_old_database_without_the_table_gains_it(self):
        old = Path(self._tmp.name) / "old.db"
        conn = sqlite3.connect(old)
        conn.executescript(database.SCHEMA.split("-- v0.6.0")[0])  # the pre-0.6.0 schema
        conn.close()
        database.init_db(old)
        conn = database.connect(old)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM risk_assessments").fetchone()[0], 0)
        conn.close()

    def test_risk_level_check_constraint(self):
        iid = self.make()
        with self.assertRaises(sqlite3.IntegrityError):
            risk_repository.save_risk_assessment(self.conn, iid, fake_result(level="SEVERE"))


class RepositoryTests(Base):
    def test_save_and_retrieve_round_trip(self):
        iid = self.make()
        saved = risk_repository.save_risk_assessment(self.conn, iid, fake_result("HIGH", 55), assessed_at="2026-10-03T10:00:00Z")
        got = risk_repository.get_latest_risk_assessment(self.conn, iid)
        self.assertEqual(got, saved)
        self.assertEqual((got.risk_level, got.risk_score, got.incident_status), ("HIGH", 55, "verify"))
        self.assertEqual(got.assessed_at, "2026-10-03T10:00:00Z")
        self.assertEqual(got.assessment_version, risk_repository.ASSESSMENT_VERSION)
        self.assertEqual(got.signals[0].code, "S")
        self.assertEqual(got.inputs["message"].status, "used")
        self.assertEqual(got.notes, ["n"])
        self.assertTrue(got.persisted)

    def test_no_assessment_returns_none(self):
        self.assertIsNone(risk_repository.get_latest_risk_assessment(self.conn, self.make()))

    def test_unknown_incident(self):
        self.assertIsNone(risk_repository.get_latest_risk_assessment(self.conn, 999))
        with self.assertRaises(risk_repository.IncidentNotFound):
            risk_repository.save_risk_assessment(self.conn, 999, fake_result())
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM risk_assessments").fetchone()[0], 0)

    def test_malformed_result_writes_nothing(self):
        iid = self.make()
        bad = fake_result()
        del bad["signals"]
        with self.assertRaises(ValueError):
            risk_repository.save_risk_assessment(self.conn, iid, bad)
        self.assertIsNone(risk_repository.get_latest_risk_assessment(self.conn, iid))

    def test_repeated_assessments_return_the_latest_and_keep_every_version(self):
        iid = self.make()
        risk_repository.save_risk_assessment(self.conn, iid, fake_result("LOW", 10), assessed_at="2026-10-03T10:00:00Z")
        risk_repository.save_risk_assessment(self.conn, iid, fake_result("CRITICAL", 100, trust_break_detected=True),
                                             assessed_at="2026-10-03T11:00:00Z")
        got = risk_repository.get_latest_risk_assessment(self.conn, iid)
        self.assertEqual((got.risk_level, got.incident_status, got.assessed_at), ("CRITICAL", "hold_payment", "2026-10-03T11:00:00Z"))
        self.assertTrue(got.trust_break_detected)
        # v0.8.0: nothing is overwritten - both versions remain, v1 exactly as first stored.
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM risk_assessment_history").fetchone()[0], 2)
        self.assertEqual((got.version_number, got.is_latest), (2, True))
        first = risk_repository.get_assessment_version(self.conn, iid, 1)
        self.assertEqual((first.risk_level, first.risk_score, first.assessed_at, first.is_latest), ("LOW", 10, "2026-10-03T10:00:00Z", False))

    def test_assessments_are_per_incident(self):
        a, b = self.make(), self.make()
        risk_repository.save_risk_assessment(self.conn, a, fake_result("CRITICAL", 90))
        self.assertIsNone(risk_repository.get_latest_risk_assessment(self.conn, b))
        self.assertEqual(repository.get_incident(self.conn, b).incident_status, NOT_ASSESSED)

    def test_get_incident_exposes_assessment_and_status(self):
        iid = self.make()
        before = repository.get_incident(self.conn, iid)
        self.assertIsNone(before.risk_assessment)
        self.assertEqual((before.incident_status, before.incident_status_label), ("not_assessed", "Not assessed"))
        risk_repository.save_risk_assessment(self.conn, iid, fake_result("CRITICAL", 90))
        after = repository.get_incident(self.conn, iid)
        self.assertEqual(after.risk_assessment.risk_level, "CRITICAL")
        self.assertEqual(after.incident_status, "hold_payment")
        self.assertEqual(after.analysis.risk_status, "needs_review")  # stored placeholder untouched

    def test_list_joins_latest_assessment_in_one_query(self):
        a, b = self.make(), self.make()
        risk_repository.save_risk_assessment(self.conn, a, fake_result("MEDIUM", 25))
        statements = []
        self.conn.set_trace_callback(statements.append)
        rows = {r.id: r for r in repository.list_incidents(self.conn)}
        self.conn.set_trace_callback(None)
        self.assertEqual(len([s for s in statements if s.lstrip().upper().startswith("SELECT")]), 1)
        self.assertEqual((rows[a].risk_level, rows[a].incident_status, rows[a].recommended_action), ("MEDIUM", "verify", "VERIFY"))
        self.assertEqual((rows[b].risk_level, rows[b].incident_status, rows[b].incident_status_label),
                         (None, "not_assessed", "Not assessed"))
        self.assertIsNone(rows[b].recommended_action)

    def test_risk_summary_counts_only_persisted_assessments(self):
        ids = [self.make() for _ in range(5)]
        self.assertEqual(risk_repository.risk_summary(self.conn)["not_assessed"], 5)
        for iid, lvl in zip(ids[:4], ("LOW", "MEDIUM", "HIGH", "CRITICAL")):
            risk_repository.save_risk_assessment(self.conn, iid, fake_result(lvl, 50))
        s = risk_repository.risk_summary(self.conn)
        self.assertEqual((s["total"], s["low"], s["medium"], s["high"], s["critical"], s["assessed"], s["not_assessed"]),
                         (5, 1, 1, 1, 1, 4, 1))

    def test_empty_database_summary_is_zero(self):
        s = risk_repository.risk_summary(self.conn)
        self.assertTrue(all(v == 0 for v in s.values()))


class StatusMappingTests(unittest.TestCase):
    def test_level_to_status(self):
        self.assertEqual(status_for_level("LOW"), "proceed")
        self.assertEqual(status_for_level("MEDIUM"), "verify")
        self.assertEqual(status_for_level("HIGH"), "verify")
        self.assertEqual(status_for_level("CRITICAL"), "hold_payment")

    def test_unknown_level_is_cautious_not_blocking(self):
        self.assertEqual(status_for_level("???"), "verify")
        self.assertEqual(status_for_level(None), "verify")

    def test_mapping_agrees_with_the_engine_actions(self):
        from app.services.risk_correlation import action_for_level

        pairs = {"PROCEED": "proceed", "VERIFY": "verify", "HOLD_PAYMENT": "hold_payment"}
        for level in STATUS_FOR_LEVEL:
            self.assertEqual(pairs[action_for_level(level)], status_for_level(level))

    def test_labels_and_unassessed(self):
        self.assertEqual(label_for_status("not_assessed"), "Not assessed")
        self.assertEqual(label_for_status("hold_payment"), "Hold payment")
        self.assertEqual(label_for_status("garbage"), "Not assessed")
        self.assertNotIn("needs_review", STATUS_FOR_LEVEL.values())


class RealEngineTests(Base):
    def test_seeded_demo_persists_critical_hold_payment(self):
        seed.seed_if_empty(self.conn)
        incident = repository.get_incident(self.conn, 1)
        result = assess_incident_risk(incident).to_dict()
        risk_repository.save_risk_assessment(self.conn, 1, result)
        got = repository.get_incident(self.conn, 1)
        self.assertEqual((got.risk_assessment.risk_level, got.risk_assessment.recommended_action), ("CRITICAL", "HOLD_PAYMENT"))
        self.assertEqual(got.incident_status, "hold_payment")
        self.assertTrue(got.risk_assessment.trust_break_detected)
        self.assertEqual(got.risk_assessment.headline, "TRUST BREAK DETECTED")

    def test_normal_payment_persists_low_proceed(self):
        iid = self.make()
        risk_repository.save_risk_assessment(self.conn, iid, assess_incident_risk(repository.get_incident(self.conn, iid)).to_dict())
        got = repository.get_incident(self.conn, iid)
        self.assertEqual((got.risk_assessment.risk_level, got.risk_assessment.recommended_action, got.incident_status),
                         ("LOW", "PROCEED", "proceed"))

    def test_engine_module_still_has_no_database_code(self):
        import ast
        import app.services.risk_correlation.engine as engine

        tree = ast.parse(Path(engine.__file__).read_text())
        imported = {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)} | {
            a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        for forbidden in ("sqlite3", "fastapi", "app.database", "app.risk_repository", "urllib", "subprocess"):
            self.assertFalse(any(m.startswith(forbidden) for m in imported), forbidden)


if __name__ == "__main__":
    unittest.main()
