"""Independent verification workflow: states, audit trail, separation from risk and case decision."""

import sqlite3
import unittest

from tests.test_risk_persistence_api import NORMAL, PersistedRiskApiTests, demo_zip

START = {"action": "START", "method": "known_corporate_phone", "reason": "Calling the CEO office line from the records", "analyst_name": "Priya"}
CONFIRM = {"action": "CONFIRM", "reason": "CEO denied sending the request", "analyst_name": "Priya"}
FAIL = {"action": "FAIL", "reason": "Number from records did not answer", "analyst_name": "Priya"}


class VerificationTests(PersistedRiskApiTests):
    def v(self, iid=1):
        return self.client.get(f"/api/incidents/{iid}/verification")

    def post(self, body, iid=1):
        return self.client.post(f"/api/incidents/{iid}/verification", json=body)

    def test_not_applicable_before_assessment_and_for_proceed(self):
        d = self.v().json()["data"]
        self.assertFalse(d["applicable"])
        self.assertEqual(d["state"], "NOT_STARTED")
        self.assertEqual(self.post(START).status_code, 409)
        iid = self.client.post("/api/incidents", json=NORMAL).json()["data"]["id"]
        self.run_risk(iid)
        d = self.v(iid).json()["data"]
        self.assertFalse(d["applicable"])
        self.assertIn("not required", d["not_applicable_reason"])
        self.assertEqual(self.post(START, iid).json()["error"]["code"], "verification_not_applicable")

    def test_recommended_methods_never_include_the_suspicious_channel(self):
        self.run_risk()  # demo: WhatsApp, CEO-001 (trusted: email, erp, known corporate phone)
        d = self.v().json()["data"]
        self.assertTrue(d["applicable"])
        keys = [m["method"] for m in d["recommended_methods"]]
        self.assertEqual(keys, ["known_corporate_phone", "finance_erp_confirmation", "approved_vendor_directory", "previously_trusted_channel"])
        trusted = next(m for m in d["recommended_methods"] if m["method"] == "previously_trusted_channel")
        self.assertNotIn("whatsapp", [c.lower() for c in trusted["channels"]])
        self.assertIn("Do not verify through the suspicious channel", d["warning"])

    def test_channel_of_request_is_excluded_even_if_it_is_a_trusted_channel(self):
        body = dict(NORMAL, message="Please pay vendor F urgently, keep this secret", beneficiary_name="Vendor F", beneficiary_is_new=True, amount=900000)
        iid = self.client.post("/api/incidents", json=body).json()["data"]["id"]  # Email
        self.run_risk(iid)
        d = self.v(iid).json()["data"]
        self.assertTrue(d["applicable"])
        trusted = next(m for m in d["recommended_methods"] if m["method"] == "previously_trusted_channel")
        self.assertNotIn("email", [c.lower() for c in trusted["channels"]])

    def test_full_workflow_confirmed_and_audit_events(self):
        self.run_risk()
        d = self.post(START).json()["data"]
        self.assertEqual((d["state"], d["allowed_actions"]), ("IN_PROGRESS", ["CONFIRM", "FAIL"]))
        d = self.post(CONFIRM).json()["data"]
        self.assertEqual(d["state"], "CONFIRMED")
        self.assertEqual([e["event_type"] for e in d["events"]], ["VERIFICATION_STARTED", "VERIFICATION_CONFIRMED"])
        last = d["events"][-1]
        self.assertEqual((last["method"], last["analyst_name"], last["assessment_number"]), ("known_corporate_phone", "Priya", 1))
        self.assertTrue(last["created_at"].endswith("Z"))
        self.assertEqual(self.post(START).status_code, 409)  # CONFIRMED is terminal

    def test_failed_can_be_retried(self):
        self.run_risk()
        self.post(START)
        self.assertEqual(self.post(FAIL).json()["data"]["state"], "FAILED")
        again = self.post(dict(START, method="finance_erp_confirmation")).json()["data"]
        self.assertEqual(again["state"], "IN_PROGRESS")
        self.assertEqual(len(again["events"]), 3)

    def test_validation(self):
        self.run_risk()
        self.assertEqual(self.post(dict(START, method=None)).status_code, 422)
        self.assertEqual(self.post(dict(START, method="reply_to_message")).status_code, 422)  # not an allowed method
        self.assertEqual(self.post(dict(START, reason="x")).status_code, 422)
        self.assertEqual(self.post(CONFIRM).status_code, 409)  # cannot confirm before starting
        self.assertEqual(self.post(dict(START, analyst_name="")).status_code, 422)
        self.assertEqual(self.v(999).status_code, 404)

    def test_verification_is_separate_from_assessment_and_case_decision(self):
        self.run_risk()
        before = self.get()
        hist = self.client.get("/api/incidents/1/assessments").json()["data"]
        self.post(START)
        self.post(CONFIRM)
        after = self.get()
        self.assertEqual(after["risk_assessment"], before["risk_assessment"])
        self.assertEqual(self.client.get("/api/incidents/1/assessments").json()["data"], hist)
        self.assertEqual(after["workflow_status"], "OPEN")          # human decision untouched
        self.assertEqual(after["case_history"], before["case_history"])
        res = self.client.post("/api/incidents/1/decision", json={"decision": "VERIFIED", "reason": "Confirmed by phone", "analyst_name": "Priya"})
        self.assertEqual(res.status_code, 200)

    def test_audit_rows_are_immutable(self):
        self.run_risk()
        self.post(START)
        conn = sqlite3.connect(self.db_path)
        with self.assertRaises(sqlite3.DatabaseError):
            conn.execute("UPDATE verification_events SET reason = 'tampered'")
        conn.close()


if __name__ == "__main__":
    unittest.main()
