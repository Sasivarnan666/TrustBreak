"""Command-centre aggregates: counted from persisted rows; honest AI status."""

import unittest

from tests.test_risk_persistence_api import NORMAL, PersistedRiskApiTests, demo_zip


class DashboardTests(PersistedRiskApiTests):
    def dash(self):
        res = self.client.get("/api/dashboard")
        self.assertEqual(res.status_code, 200)
        return res.json()["data"]

    def test_empty_assessments_counts(self):
        d = self.dash()
        self.assertEqual((d["kpis"]["critical"], d["kpis"]["high"], d["kpis"]["not_assessed"]), (0, 0, 1))
        self.assertEqual(d["kpis"]["open_cases"], 1)
        self.assertEqual(d["active_high_risk"], [])

    def test_counts_follow_the_engine_results(self):
        self.run_risk(files={"file": ("RBI_Statement.zip", demo_zip(), "application/zip")})
        iid = self.client.post("/api/incidents", json=NORMAL).json()["data"]["id"]
        self.run_risk(iid)
        d = self.dash()
        self.assertEqual((d["kpis"]["critical"], d["risk_distribution"]["low"], d["risk_distribution"]["assessed"]), (1, 1, 2))
        row = d["active_high_risk"][0]
        self.assertEqual((row["reference"], row["risk_level"], row["risk_score"], row["recommended_action"]), ("TB-0001", "CRITICAL", 100, "HOLD_PAYMENT"))
        self.assertTrue(row["is_synthetic"])
        self.assertGreaterEqual(row["trust_dimensions"], 5)
        cats = {c["category"]: c["incidents"] for c in d["trust_break_categories"]}
        for c in ("COMMUNICATION", "FINANCIAL", "BENEFICIARY", "SOCIAL_ENGINEERING", "ATTACHMENT"):
            self.assertEqual(cats[c], 1)
        self.assertEqual(d["recent_critical"][0]["incident_id"], 1)

    def test_closed_case_leaves_the_active_list_and_counts_move(self):
        self.run_risk()
        self.client.post("/api/incidents/1/decision", json={"decision": "REJECTED", "reason": "Confirmed fraud attempt", "analyst_name": "Priya"})
        d = self.dash()
        self.assertEqual((d["kpis"]["open_cases"], d["kpis"]["rejected"]), (0, 1))
        self.assertEqual(d["active_high_risk"], [])

    def test_ai_status_never_claims_online_in_mock_mode(self):
        self.run_risk()
        ai = self.dash()["system_status"]["ai_extraction"]
        self.assertEqual(ai["state"], "fallback")
        self.assertEqual(ai["label"], "AI unavailable — deterministic fallback active")
        self.assertFalse(ai["provider_configured"])

    def test_system_status_has_no_secrets(self):
        text = str(self.dash()).lower()
        self.assertNotIn("api_key", text)
        self.assertNotIn("secret", text)


if __name__ == "__main__":
    unittest.main()
