"""HTTP tests for v0.7.0: POST /api/incidents/{id}/decision, extended GET, list and case-summary."""

import unittest

from .test_risk_persistence_api import HAVE_FASTAPI, PersistedRiskApiTests

REASON = "Confirmed the request with the sender through the corporate directory number."
GOOD = {"decision": "VERIFIED", "reason": REASON, "analyst_name": "Security Analyst"}

RISK_KEYS = ("risk_score", "raw_points", "max_score", "risk_level", "recommended_action", "incident_status",
             "assessment_version", "assessed_at", "signals", "category_points", "inputs", "thresholds")


@unittest.skipUnless(HAVE_FASTAPI, "fastapi/httpx not installed")
class CaseApiBase(PersistedRiskApiTests):
    def decide(self, body=None, iid=1, **kw):
        return self.client.post(f"/api/incidents/{iid}/decision", json=GOOD if body is None else body, **kw)

    def with_(self, **over):
        return {**GOOD, **over}

    def assertError(self, res, status, code):
        self.assertEqual(res.status_code, status, res.text)
        body = res.json()
        self.assertIs(body["success"], False)
        self.assertEqual(body["error"]["code"], code)
        self.assertIsInstance(body["error"]["details"], list)
        return body["error"]


class OpenStateTests(CaseApiBase):
    def test_new_incident_is_open_with_case_opened_history(self):
        d = self.get()
        self.assertEqual((d["workflow_status"], d["workflow_status_label"]), ("OPEN", "Open"))
        self.assertEqual([h["decision"] for h in d["case_history"]], ["CASE_OPENED"])
        self.assertIsNone(d["case_history"][0]["analyst_name"])

    def test_created_incident_via_api_starts_open(self):
        res = self.client.post("/api/incidents", json={
            "sender_name": "Arvind Rao", "sender_role": "CEO", "sender_known": True, "channel": "Email",
            "amount": 5000, "beneficiary_name": "Vendor A", "beneficiary_is_new": False,
            "message": "Please pay the monthly invoice."})
        self.assertEqual(res.status_code, 201)
        self.assertEqual(res.json()["data"]["workflow_status"], "OPEN")

    def test_critical_risk_can_coexist_with_open_case(self):
        self.run_risk()
        d = self.get()
        self.assertEqual((d["risk_assessment"]["risk_level"], d["risk_assessment"]["recommended_action"]), ("CRITICAL", "HOLD_PAYMENT"))
        self.assertEqual(d["workflow_status"], "OPEN")

    def test_list_shows_risk_and_case_status_separately(self):
        self.run_risk()
        row = self.client.get("/api/incidents").json()["data"][0]
        self.assertEqual((row["risk_level"], row["workflow_status"], row["workflow_status_label"]), ("CRITICAL", "OPEN", "Open"))


class DecisionApiTests(CaseApiBase):
    def test_verified_decision(self):
        res = self.decide()
        self.assertEqual(res.status_code, 200, res.text)
        body = res.json()
        self.assertIs(body["success"], True)  # response envelope
        data = body["data"]
        self.assertEqual((data["incident_id"], data["reference"]), (1, "TB-0001"))
        self.assertEqual((data["workflow_status"], data["workflow_status_label"]), ("VERIFIED", "Verified"))
        last = data["case_history"][-1]
        self.assertEqual((last["previous_status"], last["new_status"], last["decision"]), ("OPEN", "VERIFIED", "VERIFIED"))
        self.assertEqual((last["reason"], last["analyst_name"]), (REASON, "Security Analyst"))
        self.assertTrue(last["created_at"].endswith("Z"))
        self.assertEqual(last["decision_label"], "Analyst verified the request")

    def test_rejected_decision(self):
        data = self.decide(self.with_(decision="REJECTED")).json()["data"]
        self.assertEqual((data["workflow_status"], data["workflow_status_label"]), ("REJECTED", "Rejected"))
        self.assertEqual(data["case_history"][-1]["decision_label"], "Analyst rejected the case")

    def test_reason_and_analyst_are_trimmed(self):
        data = self.decide(self.with_(reason="  " + REASON + "  ", analyst_name="  Priya N  ")).json()["data"]
        self.assertEqual((data["case_history"][-1]["reason"], data["case_history"][-1]["analyst_name"]), (REASON, "Priya N"))

    def test_decision_persists_across_get_and_app_restart(self):
        self.decide()
        self._stop()
        self._start()  # simulates a server restart / page refresh
        d = self.get()
        self.assertEqual(d["workflow_status"], "VERIFIED")
        self.assertEqual([h["decision"] for h in d["case_history"]], ["CASE_OPENED", "VERIFIED"])
        self.assertEqual(self.get()["case_history"], d["case_history"])  # repeated GET returns the same history

    def test_unknown_incident_is_404(self):
        self.assertError(self.decide(iid=999), 404, "not_found")

    def test_invalid_incident_id_is_validation_error(self):
        self.assertError(self.decide(iid=0), 422, "validation_error")

    def test_invalid_decision_values(self):
        for bad in ("OPEN", "APPROVED", "verified", "", "CASE_OPENED", None, 5):
            err = self.assertError(self.decide(self.with_(decision=bad)), 422, "validation_error")
            self.assertEqual(err["details"][0]["field"], "decision")
        self.assertEqual(self.get()["workflow_status"], "OPEN")

    def test_missing_decision(self):
        body = dict(GOOD)
        del body["decision"]
        self.assertError(self.decide(body), 422, "validation_error")

    def test_missing_reason(self):
        body = dict(GOOD)
        del body["reason"]
        err = self.assertError(self.decide(body), 422, "validation_error")
        self.assertEqual(err["details"][0]["field"], "reason")

    def test_missing_analyst(self):
        body = dict(GOOD)
        del body["analyst_name"]
        err = self.assertError(self.decide(body), 422, "validation_error")
        self.assertEqual(err["details"][0]["field"], "analyst_name")

    def test_whitespace_only_reason_and_analyst(self):
        for field in ("reason", "analyst_name"):
            err = self.assertError(self.decide(self.with_(**{field: "   \t \n "})), 422, "validation_error")
            self.assertEqual(err["details"][0]["field"], field)

    def test_too_short_and_too_long_inputs(self):
        for over in ({"reason": "ok"}, {"reason": "x" * 1001}, {"analyst_name": "A"}, {"analyst_name": "n" * 81}):
            self.assertError(self.decide(self.with_(**over)), 422, "validation_error")

    def test_unknown_fields_are_rejected(self):
        self.assertError(self.decide(self.with_(status="VERIFIED")), 422, "validation_error")

    def test_malformed_requests(self):
        self.assertError(self.client.post("/api/incidents/1/decision", content=b"{not json",
                                          headers={"Content-Type": "application/json"}), 422, "validation_error")
        self.assertError(self.client.post("/api/incidents/1/decision"), 422, "validation_error")
        self.assertError(self.decide([1, 2, 3]), 422, "validation_error")
        self.assertEqual(self.get()["workflow_status"], "OPEN")

    def test_invalid_input_does_not_write_an_audit_row(self):
        self.decide(self.with_(reason="no"))
        self.assertEqual(len(self.get()["case_history"]), 1)

    def test_wrong_http_method(self):
        self.assertError(self.client.get("/api/incidents/1/decision"), 405, "method_not_allowed")


class ClosedCaseTests(CaseApiBase):
    def test_second_decision_is_409_case_already_closed(self):
        self.decide()
        res = self.decide(self.with_(decision="REJECTED", reason="Changed my mind about this case."))
        err = self.assertError(res, 409, "case_already_closed")
        self.assertIn("already verified", err["message"])
        d = self.get()
        self.assertEqual(d["workflow_status"], "VERIFIED")
        self.assertEqual(len(d["case_history"]), 2)

    def test_rejected_cannot_become_verified_and_same_decision_is_also_refused(self):
        self.decide(self.with_(decision="REJECTED"))
        self.assertError(self.decide(), 409, "case_already_closed")
        self.assertError(self.decide(self.with_(decision="REJECTED")), 409, "case_already_closed")
        self.assertEqual(self.get()["workflow_status"], "REJECTED")

    def test_closing_one_case_does_not_close_another(self):
        self.client.post("/api/incidents", json={
            "sender_name": "Arvind Rao", "sender_role": "CEO", "sender_known": True, "channel": "Email",
            "amount": 5000, "beneficiary_name": "Vendor A", "beneficiary_is_new": False,
            "message": "Please pay the monthly invoice."})
        self.decide()
        self.assertEqual(self.get(2)["workflow_status"], "OPEN")
        self.assertEqual(self.decide(iid=2).status_code, 200)


class RiskSeparationApiTests(CaseApiBase):
    def test_decision_does_not_change_the_risk_assessment(self):
        self.run_risk()
        before = self.get()["risk_assessment"]
        self.assertEqual(before["risk_level"], "CRITICAL")
        self.decide()
        after = self.get()
        for key in RISK_KEYS:
            self.assertEqual(after["risk_assessment"][key], before[key], key)
        self.assertEqual(after["risk_assessment"], before)
        self.assertEqual((after["risk_assessment"]["risk_level"], after["incident_status"]), ("CRITICAL", "hold_payment"))
        self.assertEqual(after["workflow_status"], "VERIFIED")

    def test_rejection_also_leaves_risk_unchanged(self):
        self.run_risk()
        before = self.get()["risk_assessment"]
        self.decide(self.with_(decision="REJECTED"))
        self.assertEqual(self.get()["risk_assessment"], before)

    def test_decision_works_without_any_risk_assessment(self):
        self.assertEqual(self.decide().status_code, 200)
        d = self.get()
        self.assertIsNone(d["risk_assessment"])
        self.assertEqual(d["incident_status"], "not_assessed")

    def test_refreshing_the_risk_assessment_does_not_reopen_or_change_the_case(self):
        self.run_risk()
        self.decide()
        self.run_risk()
        d = self.get()
        self.assertEqual((d["workflow_status"], d["risk_assessment"]["risk_level"]), ("VERIFIED", "CRITICAL"))


class CaseSummaryApiTests(CaseApiBase):
    def make_incident(self):
        return self.client.post("/api/incidents", json={
            "sender_name": "Arvind Rao", "sender_role": "CEO", "sender_known": True, "channel": "Email",
            "amount": 5000, "beneficiary_name": "Vendor A", "beneficiary_is_new": False,
            "message": "Please pay the monthly invoice."})

    def test_summary_counts_come_from_persisted_state(self):
        self.make_incident()
        self.make_incident()
        res = self.client.get("/api/incidents/case-summary")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["data"], {"total": 3, "open": 3, "verified": 0, "rejected": 0})
        self.decide()
        self.decide(self.with_(decision="REJECTED"), iid=2)
        self.assertEqual(self.client.get("/api/incidents/case-summary").json()["data"],
                         {"total": 3, "open": 1, "verified": 1, "rejected": 1})

    def test_summary_is_independent_of_risk_summary(self):
        self.run_risk()
        self.decide()
        risk = self.client.get("/api/incidents/risk-summary").json()["data"]
        self.assertEqual((risk["critical"], risk["not_assessed"]), (1, 0))
        self.assertEqual(self.client.get("/api/incidents/case-summary").json()["data"]["verified"], 1)


class DemoAcceptanceTests(CaseApiBase):
    """The v0.7.0 demo: CRITICAL + OPEN -> analyst decision -> CRITICAL + VERIFIED, surviving a refresh."""

    def test_demo_sequence(self):
        self.run_risk()
        d = self.get()
        self.assertEqual((d["risk_assessment"]["risk_level"], d["risk_assessment"]["recommended_action"], d["workflow_status"]),
                         ("CRITICAL", "HOLD_PAYMENT", "OPEN"))
        row = self.client.get("/api/incidents").json()["data"][0]
        self.assertEqual((row["risk_level"], row["workflow_status"]), ("CRITICAL", "OPEN"))
        self.assertEqual(self.decide().status_code, 200)
        self._stop()
        self._start()
        d = self.get()
        self.assertEqual((d["risk_assessment"]["risk_level"], d["workflow_status"]), ("CRITICAL", "VERIFIED"))
        row = self.client.get("/api/incidents").json()["data"][0]
        self.assertEqual((row["risk_level"], row["workflow_status"]), ("CRITICAL", "VERIFIED"))
        self.assertEqual(d["case_history"][-1]["analyst_name"], "Security Analyst")


if __name__ == "__main__":
    unittest.main()
