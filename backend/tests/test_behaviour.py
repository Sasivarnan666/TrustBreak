"""Behaviour baseline & anomaly detection tests (stdlib only; no FastAPI needed)."""

import unittest

from app.services.behaviour import (
    BehaviourInput,
    BehaviourProfile,
    analyze_behaviour,
    analyze_incident_behaviour,
    get_profile_for_sender,
)

CEO = BehaviourProfile(
    employee_id="CEO-001",
    name="Test CEO",
    role="Chief Executive Officer",
    normal_channels=("email", "erp"),
    known_beneficiaries=("Vendor A", "Vendor B"),
    historical_amounts=(10_000, 25_000, 50_000, 75_000, 120_000, 200_000),
    typical_max_amount=200_000,
)


def run(**kw):
    return analyze_behaviour(BehaviourInput(**kw), CEO)


def types(result):
    return {a["type"] for a in result["anomalies"]}


class AmountTests(unittest.TestCase):
    def test_1_normal_amount(self):
        r = run(amount=75_000)
        self.assertFalse(r["amount_anomaly"])
        self.assertEqual(r["amount_deviation"], 0.0)
        self.assertEqual(r["checks"]["amount"]["status"], "within_baseline")
        self.assertNotIn("amount", types(r))

    def test_amount_equal_to_max_is_normal(self):
        self.assertFalse(run(amount=200_000)["amount_anomaly"])

    def test_2_extremely_high_amount(self):
        r = run(amount=1_850_000)
        self.assertTrue(r["amount_anomaly"])
        self.assertEqual(r["amount_deviation"], 8.25)
        a = next(x for x in r["anomalies"] if x["type"] == "amount")
        self.assertEqual(a["severity"], "high")
        self.assertIn("₹18,50,000", a["message"])

    def test_moderately_above_is_medium(self):
        r = run(amount=300_000)  # deviation 0.5
        self.assertTrue(r["amount_anomaly"])
        self.assertEqual(next(x for x in r["anomalies"] if x["type"] == "amount")["severity"], "medium")


class BeneficiaryTests(unittest.TestCase):
    def test_3_known_beneficiary(self):
        r = run(beneficiary="Vendor A")
        self.assertFalse(r["new_beneficiary"])
        self.assertEqual(r["checks"]["beneficiary"]["status"], "known")

    def test_known_beneficiary_is_case_and_space_insensitive(self):
        self.assertFalse(run(beneficiary="  vendor   b ")["new_beneficiary"])

    def test_4_new_beneficiary(self):
        r = run(beneficiary="Vendor X")
        self.assertTrue(r["new_beneficiary"])
        a = r["anomalies"][0]
        self.assertEqual((a["type"], a["code"], a["severity"]), ("beneficiary", "NEW_BENEFICIARY", "high"))


class ChannelTests(unittest.TestCase):
    def test_5_normal_channel(self):
        r = run(channel="Email")
        self.assertFalse(r["channel_anomaly"])
        self.assertEqual(r["checks"]["channel"]["status"], "normal")

    def test_6_unusual_channel(self):
        r = run(channel="WhatsApp")
        self.assertTrue(r["channel_anomaly"])
        a = r["anomalies"][0]
        self.assertEqual((a["type"], a["code"], a["severity"]), ("channel", "UNUSUAL_CHANNEL", "medium"))


class CombinedAndMissingTests(unittest.TestCase):
    def test_7_multiple_anomalies(self):
        r = run(channel="WhatsApp", beneficiary="Vendor X", amount=1_850_000)
        self.assertTrue(r["amount_anomaly"] and r["new_beneficiary"] and r["channel_anomaly"])
        self.assertFalse(r["frequency_anomaly"])
        self.assertEqual(types(r), {"amount", "beneficiary", "channel"})
        self.assertFalse(r["is_final_decision"])
        self.assertNotIn("risk_level", r)
        self.assertNotIn("risk_score", r)

    def test_normal_request_has_no_anomalies(self):
        r = run(channel="Email", beneficiary="Vendor A", amount=50_000)
        self.assertEqual(r["anomalies"], [])

    def test_8_missing_profile(self):
        r = analyze_behaviour(BehaviourInput("WhatsApp", 1_850_000, "Vendor X"), None)
        self.assertFalse(r["profile_found"])
        self.assertIsNone(r["employee_id"])
        self.assertEqual(r["anomalies"], [])
        self.assertFalse(r["amount_anomaly"] or r["new_beneficiary"] or r["channel_anomaly"])
        self.assertTrue(any("No behaviour profile" in n for n in r["notes"]))

    def test_unknown_sender_has_no_profile(self):
        r = analyze_incident_behaviour("Nobody Known", "WhatsApp", 5_000_000, "Vendor X")
        self.assertFalse(r["profile_found"])

    def test_9_missing_beneficiary(self):
        for value in (None, "", "   "):
            r = run(channel="WhatsApp", amount=1_850_000, beneficiary=value)
            self.assertFalse(r["new_beneficiary"])
            self.assertEqual(r["checks"]["beneficiary"]["status"], "not_evaluated")
            self.assertEqual(types(r), {"amount", "channel"})

    def test_10_missing_amount(self):
        for value in (None, 0):
            r = run(channel="WhatsApp", amount=value, beneficiary="Vendor X")
            self.assertFalse(r["amount_anomaly"])
            self.assertIsNone(r["amount_deviation"])
            self.assertEqual(r["checks"]["amount"]["status"], "not_evaluated")
            self.assertEqual(types(r), {"beneficiary", "channel"})

    def test_missing_everything_does_not_raise(self):
        r = run()
        self.assertTrue(r["profile_found"])
        self.assertEqual(r["anomalies"], [])

    def test_frequency_is_reported_as_not_evaluated(self):
        r = run(amount=1)
        self.assertFalse(r["frequency_anomaly"])
        self.assertEqual(r["checks"]["frequency"]["status"], "not_evaluated")


class DemoRegistryTests(unittest.TestCase):
    def test_demo_ceo_scenario_from_seed(self):
        # Mirrors the seeded demo incident (sender Arvind Rao, WhatsApp, ₹18,50,000, "New Vendor X").
        r = analyze_incident_behaviour("Arvind Rao", "WhatsApp", 1_850_000, "New Vendor X")
        self.assertEqual(r["employee_id"], "CEO-001")
        self.assertTrue(r["amount_anomaly"] and r["new_beneficiary"] and r["channel_anomaly"])
        self.assertEqual(r["amount_deviation"], 8.25)

    def test_demo_normal_payment(self):
        r = analyze_incident_behaviour("arvind rao", "Email", 100_000, "Vendor C")
        self.assertEqual(r["anomalies"], [])

    def test_profile_lookup(self):
        self.assertEqual(get_profile_for_sender("Arvind Rao").employee_id, "CEO-001")
        self.assertIsNone(get_profile_for_sender(None))
        self.assertIsNone(get_profile_for_sender(""))


if __name__ == "__main__":
    unittest.main()
