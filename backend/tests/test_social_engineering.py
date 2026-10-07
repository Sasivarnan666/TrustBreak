"""Phase 2: social-engineering evidence (rules, fallback, AI grounding, API)."""

import json
import unittest

from app.services.message_analysis import analyze_message
from app.services.message_analysis.service import AISettings
from app.services.message_analysis.social_engineering import (
    SIGNALS, build_social_engineering, detect_rule_signals, normalize_text, validate_ai_signals,
)

ATTACK = ("URGENT: I am the CEO. Transfer ₹18,50,000 to the new vendor before 4 PM today. Keep this confidential. "
          "Do not involve finance until the payment is complete.")
BENIGN = "Hi, please pay the monthly invoice from Vendor A as usual. Thanks."


def hit(text, name):
    return detect_rule_signals(text)[name]["detected"]


class RuleTests(unittest.TestCase):
    def test_all_keys_present(self):
        self.assertEqual(set(detect_rule_signals("hello")), set(SIGNALS))

    def test_attack_message(self):
        r = detect_rule_signals(ATTACK)
        for name in ("authority_pressure", "urgency_pressure", "secrecy_pressure", "verification_suppression",
                     "deadline_pressure", "payment_pressure"):
            self.assertTrue(r[name]["detected"], name)
        self.assertEqual(r["verification_suppression"]["evidence"], "Do not involve finance until the payment is complete.")
        self.assertEqual(r["secrecy_pressure"]["source"], "rule")
        self.assertIsNotNone(r["secrecy_pressure"]["confidence"])

    def test_benign_has_nothing(self):
        r = detect_rule_signals(BENIGN)
        self.assertEqual([k for k, v in r.items() if v["detected"]], [])

    def test_spec_phrases(self):
        cases = {
            "secrecy_pressure": ["keep this confidential", "Don't tell anyone", "this is between us", "KEEP  THIS   PRIVATE"],
            "verification_suppression": ["don't call me", "do not verify this", "don't involve finance", "do not contact the bank", "no need to confirm"],
            "urgency_pressure": ["this is urgent", "do it immediately", "ASAP please", "right away", "before 4 PM", "pay today"],
            "authority_pressure": ["I am the CEO", "as your manager", "CEO instruction", "the director instructed this"],
            "payment_pressure": ["transfer the money", "release payment now", "send funds", "wire it"],
            "credential_pressure": ["send OTP", "send the password", "share credentials"],
        }
        for name, texts in cases.items():
            for t in texts:
                self.assertTrue(hit(t, name), f"{name}: {t}")

    def test_normalization(self):
        self.assertTrue(hit("Don\u2019t   call\nme", "verification_suppression"))  # curly apostrophe + whitespace
        self.assertTrue(hit("KEEP\tTHIS\u200b CONFIDENTIAL", "secrecy_pressure"))  # zero-width char
        self.assertEqual(normalize_text(" a \n b\u2019s "), "a b's")

    def test_negation_is_not_a_request(self):
        self.assertFalse(hit("Never share your OTP with anyone.", "credential_pressure"))
        self.assertFalse(hit("Do not share your password.", "credential_pressure"))
        self.assertFalse(hit("This is not confidential.", "secrecy_pressure"))

    def test_other_signals(self):
        self.assertTrue(hit("Pay now or else your account will be suspended.", "fear_or_threat"))
        self.assertTrue(hit("This is my new number, save it.", "impersonation_cue"))
        self.assertTrue(hit("Buy gift cards for the client.", "unusual_instruction"))
        self.assertTrue(hit("Do not discuss with the team, handle this yourself.", "isolation_request"))

    def test_evidence_is_clipped_and_in_message(self):
        long = "Do not call me " + "x " * 300
        ev = detect_rule_signals(long)["verification_suppression"]["evidence"]
        self.assertLessEqual(len(ev), 200)
        self.assertIn("Do not call", ev)


class AiGroundingTests(unittest.TestCase):
    def test_accepts_grounded(self):
        ok, notes = validate_ai_signals([{"signal": "urgency_pressure", "evidence": "pay IMMEDIATELY", "confidence": "high"}], "Please pay immediately.")
        self.assertEqual(len(ok), 1)
        self.assertEqual(notes, [])

    def test_rejects_invented_evidence(self):
        ok, notes = validate_ai_signals([{"signal": "urgency_pressure", "evidence": "pay within the hour", "confidence": "high"}], "Please pay.")
        self.assertEqual(ok, [])
        self.assertTrue(notes)

    def test_rejects_risk_fields_unknown_signal_and_dupes(self):
        msg = "pay now"
        bad = [
            {"signal": "urgency_pressure", "evidence": "pay now", "confidence": "high", "risk_score": 99},
            {"signal": "made_up", "evidence": "pay now", "confidence": "high"},
            {"signal": "urgency_pressure", "evidence": "pay now", "confidence": "extreme"},
            "string",
        ]
        self.assertEqual(validate_ai_signals(bad, msg)[0], [])
        good = {"signal": "urgency_pressure", "evidence": "pay now", "confidence": "low"}
        self.assertEqual(len(validate_ai_signals([good, good], msg)[0]), 1)

    def test_non_list_is_dropped_not_raised(self):
        self.assertEqual(validate_ai_signals({"a": 1}, "x")[0], [])
        self.assertEqual(validate_ai_signals(None, "x"), ([], []))


class MergeTests(unittest.TestCase):
    def test_labels(self):
        ai = [{"signal": "authority_pressure", "evidence": "I am the CEO", "confidence": "medium"}]
        b = build_social_engineering(ATTACK, ai_signals=ai, ai_requested=True)
        by = {s["signal"]: s for s in b["signals"]}
        self.assertEqual(by["authority_pressure"]["source"], "AI")
        self.assertIn("rule", by["authority_pressure"]["sources"])
        self.assertEqual(by["authority_pressure"]["confidence"], "high")  # rules corroborate with higher confidence
        self.assertEqual(by["secrecy_pressure"]["source"], "rule")
        self.assertTrue(b["ai_contributed"])
        fb = build_social_engineering(ATTACK, ai_requested=True, ai_failed=True)
        self.assertEqual({s["source"] for s in fb["signals"] if s["detected"]}, {"fallback"})
        self.assertFalse(fb["is_final_decision"])

    def test_no_score_fields(self):
        b = build_social_engineering(ATTACK)
        flat = json.dumps(b)
        for forbidden in ("risk_score", "risk_level", "recommended_action"):
            self.assertNotIn(forbidden, flat)


class _Client:
    model = "fake"

    def __init__(self, signals):
        self.signals = signals

    def complete(self, system, user):
        reply = {
            "claimed_authority": "CEO", "requested_action": "transfer money", "payment_amount": 1850000, "currency": "INR",
            "beneficiary": None, "urgency_level": "high", "secrecy_indicator": True, "organization": None, "deadline": None,
            "financial_intent": "payment_transfer", "extracted_entities": [], "confidence": 0.9,
        }
        if self.signals is not None:
            reply["social_engineering_signals"] = self.signals
        return json.dumps(reply)


def settings(**kw):
    return AISettings(mode="auto", api_key="k", model="m", timeout=5, provider="gemini", **kw)


class ServiceTests(unittest.TestCase):
    def test_ai_path_with_signals(self):
        sig = [{"signal": "fear_or_threat", "evidence": "Do not involve finance", "confidence": "low"}]
        r = analyze_message(ATTACK, settings=settings(), client=_Client(sig))
        self.assertEqual(r.mode, "ai")
        by = {s["signal"]: s for s in r.social_engineering["signals"]}
        self.assertEqual(by["fear_or_threat"]["source"], "AI")
        self.assertEqual(by["secrecy_pressure"]["source"], "rule")  # rules still run beside the AI
        self.assertTrue(r.social_engineering["ai_contributed"])

    def test_ai_reply_without_signals_still_valid(self):
        r = analyze_message(ATTACK, settings=settings(), client=_Client(None))
        self.assertEqual(r.mode, "ai")
        self.assertFalse(r.social_engineering["ai_contributed"])

    def test_ungrounded_ai_signal_dropped_extraction_kept(self):
        sig = [{"signal": "fear_or_threat", "evidence": "you will be arrested", "confidence": "high"}]
        r = analyze_message(ATTACK, settings=settings(), client=_Client(sig))
        self.assertEqual(r.mode, "ai")
        self.assertFalse({s["signal"]: s for s in r.social_engineering["signals"]}["fear_or_threat"]["detected"])
        self.assertTrue(any("discarded" in n for n in r.social_engineering["notes"]))

    def test_malformed_signals_do_not_fail_extraction(self):
        r = analyze_message(ATTACK, settings=settings(), client=_Client("nonsense"))
        self.assertEqual(r.mode, "ai")

    def test_top_level_risk_field_still_rejected(self):
        class Bad(_Client):
            def complete(self, s, u):
                d = json.loads(super().complete(s, u))
                d["risk_score"] = 5
                return json.dumps(d)

        r = analyze_message(ATTACK, settings=settings(), client=Bad(None))
        self.assertEqual(r.analysis_state, "fallback")  # validation rejected -> labelled fallback
        self.assertEqual(r.failure_kind, "invalid_response")
        self.assertEqual({s["source"] for s in r.social_engineering["signals"] if s["detected"]}, {"fallback"})

    def test_mock_mode_labels_rule(self):
        r = analyze_message(ATTACK, settings=AISettings(mode="mock", api_key=None, model="m", timeout=5, provider="mock"))
        self.assertEqual({s["source"] for s in r.social_engineering["signals"] if s["detected"]}, {"rule"})

    def test_empty_message(self):
        r = analyze_message("   ", settings=settings())
        self.assertIsNone(r.social_engineering)


if __name__ == "__main__":
    unittest.main()
