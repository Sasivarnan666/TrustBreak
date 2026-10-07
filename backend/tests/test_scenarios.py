"""Scenario simulator: synthetic inputs through the REAL pipeline; results come from the engine."""

import inspect
import unittest

from app.services import scenarios
from tests.test_risk_persistence_api import PersistedRiskApiTests


class ScenarioDefinitionTests(unittest.TestCase):
    def test_seven_required_scenarios(self):
        self.assertEqual(
            [s.id for s in scenarios.SCENARIOS],
            ["executive_payment_impersonation", "vendor_bank_detail_change", "urgent_invoice_fraud", "credential_otp_request",
             "suspicious_document_delivery", "legitimate_high_value_payment", "suspicious_but_legitimate_request"])

    def test_no_scores_or_levels_are_defined_in_the_scenarios(self):
        src = inspect.getsource(scenarios)
        for word in ("risk_score", "CRITICAL", "HOLD_PAYMENT", "risk_level", "recommended_action"):
            self.assertNotIn(word, src)
        for s in scenarios.SCENARIOS:
            self.assertNotIn("risk_score", s.to_public())

    def test_attachment_is_a_harmless_in_memory_zip_listing(self):
        import io, zipfile
        s = scenarios.get_scenario("executive_payment_impersonation")
        with zipfile.ZipFile(io.BytesIO(s.attachment_bytes())) as z:
            self.assertEqual(z.namelist(), ["Statement.pdf", "Update.exe", "helper.dll"])
            self.assertTrue(all(b"synthetic placeholder" in z.read(n) for n in z.namelist()))

    def test_every_payload_is_valid_incident_input(self):
        from app.schemas import IncidentCreate
        for s in scenarios.SCENARIOS:
            IncidentCreate(**s.incident_payload())


class ScenarioApiTests(PersistedRiskApiTests):
    def load(self, sid):
        return self.client.post(f"/api/scenarios/{sid}/load")

    def test_list_is_labelled_synthetic(self):
        data = self.client.get("/api/scenarios").json()["data"]
        self.assertEqual(len(data), 7)
        self.assertTrue(all(d["synthetic"] and "Synthetic" in d["synthetic_label"] for d in data))

    def test_unknown_scenario_404(self):
        self.assertEqual(self.load("nope").status_code, 404)

    def test_executive_scenario_reaches_critical_hold_trust_break_from_engine(self):
        data = self.load("executive_payment_impersonation").json()["data"]
        self.assertTrue(data["synthetic"] and data["assessment_persisted"])
        self.assertEqual((data["risk_level"], data["recommended_action"], data["risk_score"]), ("CRITICAL", "HOLD_PAYMENT", 100))
        inc = self.get(data["incident_id"])
        self.assertTrue(inc["is_synthetic"])
        self.assertEqual(inc["scenario_id"], "executive_payment_impersonation")
        ra = inc["risk_assessment"]
        self.assertEqual((ra["raw_points"], ra["headline"]), (130, "TRUST BREAK DETECTED"))
        self.assertEqual(ra["inputs"]["attachment"]["status"], "used")

    def test_legitimate_scenario_is_low_proceed(self):
        d = self.load("legitimate_high_value_payment").json()["data"]
        self.assertEqual((d["risk_level"], d["recommended_action"]), ("LOW", "PROCEED"))

    def test_every_scenario_persists_a_real_assessment_with_signals(self):
        levels = {}
        for s in scenarios.SCENARIOS:
            d = self.load(s.id).json()["data"]
            self.assertTrue(d["assessment_persisted"], s.id)
            inc = self.get(d["incident_id"])
            self.assertEqual(inc["risk_assessment"]["risk_score"], d["risk_score"])
            self.assertEqual(len(inc["assessment_history"]), 1)
            levels[s.id] = d["risk_level"]
        self.assertEqual(levels["legitimate_high_value_payment"], "LOW")
        self.assertEqual(levels["executive_payment_impersonation"], "CRITICAL")
        self.assertIn(levels["credential_otp_request"], ("HIGH", "CRITICAL"))
        self.assertIn(levels["suspicious_document_delivery"], ("HIGH", "CRITICAL"))
        self.assertIn(levels["vendor_bank_detail_change"], ("MEDIUM", "HIGH", "CRITICAL"))

    def test_loading_twice_creates_two_independent_incidents(self):
        a = self.load("urgent_invoice_fraud").json()["data"]["incident_id"]
        b = self.load("urgent_invoice_fraud").json()["data"]["incident_id"]
        self.assertNotEqual(a, b)

    def test_non_scenario_incident_is_not_marked_synthetic(self):
        from tests.test_risk_persistence_api import NORMAL
        iid = self.client.post("/api/incidents", json=NORMAL).json()["data"]["id"]
        d = self.get(iid)
        self.assertFalse(d["is_synthetic"])
        self.assertIsNone(d["scenario_id"])


if __name__ == "__main__":
    unittest.main()
