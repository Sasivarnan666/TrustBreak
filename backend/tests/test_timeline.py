"""Forensic timeline: only persisted events, never invented timestamps."""

import unittest

from app.services import timeline
from tests.test_risk_persistence_api import PersistedRiskApiTests, demo_zip
from tests.test_verification import CONFIRM, START


class TimelineTests(PersistedRiskApiTests):
    def tl(self, iid=1):
        return self.client.get(f"/api/incidents/{iid}/timeline")

    def codes(self, iid=1):
        return [e["event_code"] for e in self.tl(iid).json()["data"]["events"]]

    def test_unknown_incident_404(self):
        self.assertEqual(self.tl(999).status_code, 404)

    def test_unassessed_incident_shows_only_intake_events(self):
        self.assertEqual(self.codes(), ["INCIDENT_CREATED", "IDENTITY_RESOLVED", "CASE_OPENED"])

    def test_full_demo_timeline_order_and_content(self):
        self.run_risk(files={"file": ("RBI_Statement.zip", demo_zip(), "application/zip")})
        self.client.post("/api/incidents/1/verification", json=START)
        self.client.post("/api/incidents/1/verification", json=CONFIRM)
        self.client.post("/api/incidents/1/decision", json={"decision": "REJECTED", "reason": "Confirmed fraudulent by CEO office", "analyst_name": "Priya"})
        events = self.tl().json()["data"]["events"]
        codes = [e["event_code"] for e in events]
        for needed in ("INCIDENT_CREATED", "IDENTITY_RESOLVED", "MESSAGE_ANALYZED", "BEHAVIOUR_ANALYZED", "ATTACHMENT_ANALYZED",
                       "RISK_ASSESSED", "RECOMMENDATION", "VERIFICATION_STARTED", "VERIFICATION_CONFIRMED", "ANALYST_DECISION"):
            self.assertIn(needed, codes)
        self.assertLess(codes.index("RISK_ASSESSED"), codes.index("RECOMMENDATION"))
        self.assertLess(codes.index("VERIFICATION_CONFIRMED"), codes.index("ANALYST_DECISION"))
        self.assertEqual([e["seq"] for e in events], list(range(1, len(events) + 1)))
        by = {e["event_code"]: e for e in events}
        self.assertIn("Arvind Rao / CEO-001", by["IDENTITY_RESOLVED"]["explanation"])
        self.assertIn("100 / CRITICAL", by["RISK_ASSESSED"]["explanation"])
        self.assertIn("Executable content detected", by["ATTACHMENT_ANALYZED"]["explanation"])
        self.assertIn("HOLD PAYMENT", by["RECOMMENDATION"]["explanation"])
        self.assertIn("static structural analysis only", by["ATTACHMENT_ANALYZED"]["explanation"])

    def test_reassessment_is_labelled_and_timestamps_are_persisted_values(self):
        self.run_risk()
        self.run_risk(files={"file": ("RBI_Statement.zip", demo_zip(), "application/zip")})
        events = self.tl().json()["data"]["events"]
        self.assertEqual([e["event_code"] for e in events].count("RISK_REASSESSED"), 1)
        history = {h["assessed_at"] for h in self.client.get("/api/incidents/1/assessments").json()["data"]}
        for e in events:
            if e["event_code"] in ("RISK_ASSESSED", "RISK_REASSESSED"):
                self.assertIn(e["timestamp"], history)

    def test_missing_timestamp_is_not_fabricated(self):
        class Sender: identity_id, name, identity_source = None, "X", "none"
        class Inc:
            created_at, received_at, reference, sender, case_history = None, None, "TB-0009", Sender(), []
        ev = timeline.build_timeline(Inc(), [], [])
        self.assertTrue(all(e["timestamp"] is None for e in ev))
        self.assertIn("not linked to a trusted identity", ev[1]["explanation"])


if __name__ == "__main__":
    unittest.main()
