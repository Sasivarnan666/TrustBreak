"""Core tests: validation, placeholder analysis, SQLite persistence, seeding.

Standard library `unittest` only (plus pydantic, which FastAPI installs).
Run from backend/:  python -m unittest discover -s tests -t . -v
"""

import json
import tempfile
import unittest
from pathlib import Path

from pydantic import ValidationError

from app import database, repository, seed
from app.schemas import IncidentCreate
from app.services.analysis import ANALYSIS_MODE, RISK_NEEDS_REVIEW, analyze_incident, format_inr


def valid_payload(**overrides) -> dict:
    data = {
        "sender_name": "Priya Nair",
        "sender_role": "Finance Controller",
        "sender_known": True,
        "channel": "Email",
        "amount": 250000,
        "beneficiary_name": "Acme Supplies",
        "beneficiary_is_new": False,
        "message": "Please process this invoice today.",
    }
    data.update(overrides)
    return data


class FormatInrTests(unittest.TestCase):
    def test_indian_grouping(self):
        self.assertEqual(format_inr(1_850_000), "₹18,50,000")
        self.assertEqual(format_inr(999), "₹999")
        self.assertEqual(format_inr(1_000), "₹1,000")
        self.assertEqual(format_inr(12_345_678), "₹1,23,45,678")


class SchemaValidationTests(unittest.TestCase):
    def test_valid_payload_accepted(self):
        incident = IncidentCreate(**valid_payload())
        self.assertEqual(incident.amount, 250000)
        self.assertIsNone(incident.attachment_name)

    def test_whitespace_is_stripped_and_blank_optionals_become_none(self):
        incident = IncidentCreate(**valid_payload(sender_name="  Priya Nair  ", sender_contact="   ", attachment_name=""))
        self.assertEqual(incident.sender_name, "Priya Nair")
        self.assertIsNone(incident.sender_contact)
        self.assertIsNone(incident.attachment_name)

    def test_rejects_non_positive_amount(self):
        for bad in (0, -5):
            with self.assertRaises(ValidationError):
                IncidentCreate(**valid_payload(amount=bad))

    def test_rejects_fractional_and_oversized_amount(self):
        with self.assertRaises(ValidationError):
            IncidentCreate(**valid_payload(amount=1.5))
        with self.assertRaises(ValidationError):
            IncidentCreate(**valid_payload(amount=10_000_000_001))

    def test_rejects_unknown_channel(self):
        with self.assertRaises(ValidationError):
            IncidentCreate(**valid_payload(channel="Carrier pigeon"))

    def test_rejects_short_message_and_blank_names(self):
        with self.assertRaises(ValidationError):
            IncidentCreate(**valid_payload(message="hi"))
        with self.assertRaises(ValidationError):
            IncidentCreate(**valid_payload(sender_name="   "))
        with self.assertRaises(ValidationError):
            IncidentCreate(**valid_payload(beneficiary_name=""))

    def test_rejects_missing_required_field(self):
        data = valid_payload()
        del data["sender_known"]
        with self.assertRaises(ValidationError):
            IncidentCreate(**data)

    def test_rejects_unexpected_field(self):
        with self.assertRaises(ValidationError):
            IncidentCreate(**valid_payload(risk_status="low"))

    def test_attachment_details_require_a_name(self):
        with self.assertRaises(ValidationError):
            IncidentCreate(**valid_payload(attachment_size_bytes=1024))
        incident = IncidentCreate(**valid_payload(attachment_name="a.pdf", attachment_size_bytes=1024))
        self.assertEqual(incident.attachment_name, "a.pdf")


class PlaceholderAnalysisTests(unittest.TestCase):
    def test_is_clearly_a_placeholder_and_needs_review(self):
        analysis = analyze_incident(seed.DEMO_INCIDENT)
        self.assertEqual(analysis.mode, ANALYSIS_MODE)
        self.assertEqual(ANALYSIS_MODE, "placeholder")
        self.assertEqual(analysis.risk_status, RISK_NEEDS_REVIEW)
        self.assertIn("not enabled", analysis.summary)
        self.assertTrue(analysis.recommended_action)

    def test_evidence_is_only_submitted_facts(self):
        analysis = analyze_incident(seed.DEMO_INCIDENT)
        self.assertTrue(analysis.evidence)
        self.assertTrue(all(item.source == "submitted" for item in analysis.evidence))
        values = " | ".join(item.value for item in analysis.evidence)
        self.assertIn("₹18,50,000", values)
        self.assertIn("RBI_Statement.zip", values)
        self.assertIn("New Vendor X (new)", values)

    def test_no_attachment_wording(self):
        analysis = analyze_incident(IncidentCreate(**valid_payload()))
        attachment = next(item for item in analysis.evidence if item.label == "Attachment")
        self.assertEqual(attachment.value, "No attachment")

    def test_result_does_not_depend_on_input_risk(self):
        # Guards against someone sneaking heuristics into the placeholder.
        a = analyze_incident(IncidentCreate(**valid_payload(amount=1)))
        b = analyze_incident(IncidentCreate(**valid_payload(amount=9_000_000_000, sender_known=False)))
        self.assertEqual(a.risk_status, b.risk_status)
        self.assertEqual(a.recommended_action, b.recommended_action)


class RepositoryTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "test.db"
        database.init_db(self.db_path)
        self.conn = database.connect(self.db_path)

    def tearDown(self):
        self.conn.close()
        self._tmp.cleanup()

    def test_init_db_is_idempotent(self):
        database.init_db(self.db_path)
        database.init_db(self.db_path)
        self.assertEqual(repository.count_incidents(self.conn), 0)

    def test_create_then_get_round_trip(self):
        created = repository.create_incident(self.conn, seed.DEMO_INCIDENT)
        fetched = repository.get_incident(self.conn, created.id)
        self.assertEqual(fetched, created)
        self.assertEqual(created.reference, "TB-0001")
        self.assertEqual(created.sender.name, "Arvind Rao")
        self.assertTrue(created.sender.known)
        self.assertEqual(created.channel, "WhatsApp")
        self.assertEqual(created.payment.amount, 1_850_000)
        self.assertEqual(created.payment.currency, "INR")
        self.assertTrue(created.payment.beneficiary_is_new)
        self.assertEqual(created.attachment.name, "RBI_Statement.zip")
        self.assertEqual(created.analysis.risk_status, "needs_review")
        self.assertGreater(len(created.analysis.evidence), 0)
        self.assertTrue(created.created_at.endswith("Z"))

    def test_incident_without_attachment_has_null_attachment(self):
        created = repository.create_incident(self.conn, IncidentCreate(**valid_payload()))
        self.assertIsNone(created.attachment)

    def test_get_missing_returns_none(self):
        self.assertIsNone(repository.get_incident(self.conn, 999))

    def test_list_is_newest_first_with_paging(self):
        for name in ("First Sender", "Second Sender", "Third Sender"):
            repository.create_incident(self.conn, IncidentCreate(**valid_payload(sender_name=name)))
        items = repository.list_incidents(self.conn)
        self.assertEqual([i.sender_name for i in items], ["Third Sender", "Second Sender", "First Sender"])
        self.assertEqual(repository.count_incidents(self.conn), 3)
        page = repository.list_incidents(self.conn, limit=1, offset=1)
        self.assertEqual([i.sender_name for i in page], ["Second Sender"])

    def test_summary_flags(self):
        repository.create_incident(self.conn, seed.DEMO_INCIDENT)
        repository.create_incident(self.conn, IncidentCreate(**valid_payload()))
        newest, oldest = repository.list_incidents(self.conn)
        self.assertFalse(newest.has_attachment)
        self.assertTrue(oldest.has_attachment)
        self.assertTrue(oldest.beneficiary_is_new)

    def test_stored_evidence_is_valid_json(self):
        repository.create_incident(self.conn, seed.DEMO_INCIDENT)
        raw = self.conn.execute("SELECT evidence_json FROM incidents").fetchone()[0]
        self.assertIsInstance(json.loads(raw), list)

    def test_database_rejects_non_positive_amount(self):
        import sqlite3

        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                "INSERT INTO incidents (created_at,title,sender_name,sender_role,sender_known,channel,amount,"
                "beneficiary_name,beneficiary_is_new,message,analysis_mode,risk_status,analysis_summary,"
                "recommended_action,evidence_json) VALUES ('t','t','s','r',1,'Email',0,'b',0,'m','p','n','s','a','[]')"
            )


class SeedTests(unittest.TestCase):
    def test_seed_inserts_demo_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "seed.db"
            database.init_db(path)
            conn = database.connect(path)
            try:
                self.assertTrue(seed.seed_if_empty(conn))
                self.assertFalse(seed.seed_if_empty(conn))
                self.assertEqual(repository.count_incidents(conn), 1)
                demo = repository.get_incident(conn, 1)
                self.assertEqual(demo.payment.beneficiary_name, "New Vendor X")
                self.assertEqual(demo.channel, "WhatsApp")
                self.assertIn("urgent", demo.message.lower())
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
