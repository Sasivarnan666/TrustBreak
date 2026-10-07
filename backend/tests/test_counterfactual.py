"""Counterfactual risk analysis: same engine, read-only, no hardcoded scores."""

import unittest

from app.services import counterfactual
from app.services.risk_correlation import rules
from app.services.risk_correlation.engine import correlate_signals
from app.services.risk_correlation.signals import RiskSignal
from tests.test_risk_persistence_api import NORMAL, PersistedRiskApiTests, demo_zip


def sig(code, points=None):
    rule = rules.RULES_BY_CODE[code]
    pts = rule.weight if points is None else points
    return RiskSignal(code=code, category=rule.category, source="rule", severity=rules.severity_for_points(pts), points=pts,
                      title=rule.title, message=rule.default_message, group=rule.group, analyzer="behaviour")


def assessment_from(signals):
    res = correlate_signals(signals, {}).to_dict()
    res["version_number"] = 1
    return res


class CounterfactualUnitTests(unittest.TestCase):
    def test_none_assessment_is_unavailable(self):
        out = counterfactual.analyze(None)
        self.assertFalse(out["available"])
        self.assertIn("No stored risk assessment", out["reason"])
        self.assertEqual(out["counterfactuals"], [])

    def test_scores_come_from_the_engine_not_constants(self):
        sigs = [sig("NEW_BENEFICIARY"), sig("UNUSUAL_CHANNEL"), sig("AMOUNT_ABOVE_BASELINE")]  # 20 + 15 + 20 = 55 HIGH
        out = counterfactual.analyze(assessment_from(sigs))
        self.assertTrue(out["available"])
        self.assertEqual((out["current"]["risk_score"], out["current"]["risk_level"]), (55, "HIGH"))
        by_id = {c["id"]: c for c in out["counterfactuals"]}
        self.assertEqual(by_id["known_beneficiary"]["new_score"], 35)
        self.assertEqual(by_id["known_beneficiary"]["score_delta"], -20)
        self.assertEqual(by_id["trusted_channel"]["new_score"], 40)
        self.assertEqual(by_id["normal_amount"]["new_score"], 35)
        for c in by_id.values():  # every number equals a real engine run on the remaining signals
            remaining = [s for s in sigs if s.code not in {a["code"] for a in c["affected_signals"]}]
            self.assertEqual(c["new_score"], correlate_signals(remaining, {}).risk_score)

    def test_changing_a_weight_changes_the_counterfactual(self):
        # Proves nothing is hardcoded: a different stored point value gives a different delta.
        out = counterfactual.analyze(assessment_from([sig("NEW_BENEFICIARY", 10), sig("UNUSUAL_CHANNEL")]))
        by_id = {c["id"]: c for c in out["counterfactuals"]}
        self.assertEqual(by_id["known_beneficiary"]["score_delta"], -10)

    def test_inapplicable_counterfactuals_are_omitted(self):
        out = counterfactual.analyze(assessment_from([sig("NEW_BENEFICIARY")]))
        self.assertEqual([c["id"] for c in out["counterfactuals"]], ["known_beneficiary"])

    def test_largest_reduction_and_sorting(self):
        out = counterfactual.analyze(assessment_from([sig("NEW_BENEFICIARY"), sig("UNUSUAL_CHANNEL"), sig("UNUSUAL_TIME")]))
        self.assertEqual(out["largest_reduction"]["id"], "known_beneficiary")
        deltas = [c["score_delta"] for c in out["counterfactuals"]]
        self.assertEqual(deltas, sorted(deltas))

    def test_capped_score_reports_zero_delta_honestly_and_finds_a_combination(self):
        sigs = [sig("NEW_BENEFICIARY"), sig("AMOUNT_ABOVE_BASELINE"), sig("UNUSUAL_CHANNEL"), sig("SECRECY_REQUESTED"),
                sig("VERIFICATION_SUPPRESSION"), sig("EXECUTABLE_ATTACHMENT"), sig("DOCUMENT_WITH_EXECUTABLE"),
                sig("AUTHORITY_MISMATCH"), sig("FINANCIAL_TRANSFER_INTENT")]  # 114 + 15 + 8 = 137
        a = assessment_from(sigs)
        self.assertEqual((a["risk_score"], a["raw_points"]), (100, 137))
        out = counterfactual.analyze(a)
        by_id = {c["id"]: c for c in out["counterfactuals"]}
        self.assertEqual(by_id["known_beneficiary"]["score_delta"], 0)       # still capped: shown honestly
        self.assertEqual(by_id["known_beneficiary"]["raw_delta"], -20)
        self.assertIn("display cap", by_id["known_beneficiary"]["explanation"])
        self.assertTrue(any("capped" in n for n in out["notes"]))
        down = out["smallest_downgrade"]
        self.assertIsNotNone(down)
        self.assertIn(down["new_level"], ("LOW", "MEDIUM", "HIGH"))
        self.assertGreaterEqual(len(down["ids"]), 1)

    def test_does_not_mutate_the_assessment(self):
        a = assessment_from([sig("NEW_BENEFICIARY"), sig("UNUSUAL_CHANNEL")])
        import copy
        before = copy.deepcopy(a)
        counterfactual.analyze(a)
        self.assertEqual(a, before)

    def test_old_engine_assessment_is_not_rescored(self):
        a = assessment_from([sig("NEW_BENEFICIARY")])
        a["risk_score"], a["risk_level"] = 99, "CRITICAL"  # does not match what the engine reproduces
        out = counterfactual.analyze(a)
        self.assertFalse(out["available"])
        self.assertIn("earlier engine version", out["reason"])

    def test_disclaimer_present(self):
        self.assertIn("same Risk Engine", counterfactual.analyze(None)["disclaimer"])
        self.assertIn("do not modify the incident or assessment history", counterfactual.DISCLAIMER)


class CounterfactualApiTests(PersistedRiskApiTests):
    def cf(self, iid=1):
        return self.client.get(f"/api/incidents/{iid}/counterfactuals")

    def test_unknown_incident_404(self):
        self.assertEqual(self.cf(999).status_code, 404)

    def test_unassessed_incident_is_unavailable_not_an_error(self):
        res = self.cf()
        self.assertEqual(res.status_code, 200)
        self.assertFalse(res.json()["data"]["available"])

    def test_demo_with_attachment_reproduces_engine_and_is_read_only(self):
        self.run_risk(files={"file": ("RBI_Statement.zip", demo_zip(), "application/zip")})
        before_history = self.client.get("/api/incidents/1/assessments").json()["data"]
        before_incident = self.get()
        data = self.cf().json()["data"]
        self.assertTrue(data["available"])
        self.assertEqual((data["current"]["risk_score"], data["current"]["raw_points"], data["current"]["risk_level"]), (100, 130, "CRITICAL"))
        ids = {c["id"] for c in data["counterfactuals"]}
        self.assertTrue({"known_beneficiary", "trusted_channel", "normal_amount", "no_social_engineering",
                         "no_suspicious_attachment", "no_executable_evidence"} <= ids)
        att = next(c for c in data["counterfactuals"] if c["id"] == "no_suspicious_attachment")
        self.assertLess(att["new_score"], 100)
        self.assertEqual(att["score_delta"], att["new_score"] - 100)
        self.assertIsNotNone(data["smallest_downgrade"])
        self.assertIn("do not modify", data["disclaimer"])
        self.cf()  # repeated calls: no side effects
        self.assertEqual(self.client.get("/api/incidents/1/assessments").json()["data"], before_history)
        self.assertEqual(self.get(), before_incident)

    def test_benign_incident_has_few_or_no_reductions(self):
        iid = self.client.post("/api/incidents", json=NORMAL).json()["data"]["id"]
        self.run_risk(iid)
        data = self.cf(iid).json()["data"]
        self.assertTrue(data["available"])
        self.assertEqual(data["current"]["risk_level"], "LOW")
        for c in data["counterfactuals"]:
            self.assertEqual(c["new_level"], "LOW")


if __name__ == "__main__":
    unittest.main()
