"""Risk Engine 2.0 + signal provenance (v0.12.0). Synthetic data only; no network, no real AI call.

Covers the normalized signal model, category mapping, provenance, deterministic consolidation (no double counting),
caps, the regression scenarios, immutable history with engine versions, and the human/engine separation.
"""

import copy
import io
import json
import os
import sqlite3
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from app.seed import DEMO_INCIDENT
from app.services.attachment_analysis import analyze_attachment
from app.services.behaviour import analyze_incident_behaviour
from app.services.message_analysis import ExtractionError
from app.services.risk_correlation import (
    assess_incident_risk,
    collect_signals,
    consolidate,
    correlate_risk,
    correlate_signals,
    rules,
)
from app.services.risk_correlation.signals import RiskSignal

try:
    from fastapi.testclient import TestClient

    HAVE_FASTAPI = True
except ImportError:  # pragma: no cover
    HAVE_FASTAPI = False


# --------------------------------------------------------------------------- #
# Builders
# --------------------------------------------------------------------------- #
def zip_bytes(*names):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for n in names:
            z.writestr(n, "inert")
    return buf.getvalue()


def se(name, evidence="quoted evidence", source="rule", confidence="high"):
    return {"signal": name, "detected": True, "evidence": evidence, "matched_phrase": None,
            "source": source, "sources": [source], "confidence": confidence}


def msg(urgency="none", secrecy=False, intent="none", claimed=None, state="mock", mode="mock", social=(), deadline=None):
    return {
        "mode": mode, "analysis_state": state, "provider": "mock", "model": None, "notes": [], "is_final_decision": False,
        "extraction": {"claimed_authority": claimed, "requested_action": None, "payment_amount": None, "currency": None,
                       "beneficiary": None, "urgency_level": urgency, "secrecy_indicator": secrecy, "organization": None,
                       "deadline": deadline, "financial_intent": intent, "extracted_entities": [], "confidence": 0.9},
        "social_engineering": {"signals": list(social)},
    }


def beh(*codes, found=True, role="Chief Executive Officer", baseline="SYNTHETIC_BASELINE_AVAILABLE"):
    return {"profile_found": found, "baseline_status": baseline, "profile_summary": {"role": role} if found else None,
            "anomalies": [{"code": c, "type": "x", "severity": "high", "message": f"{c} observed"} for c in codes]}


def finding(type_, severity="high", entry=None):
    return {"type": type_, "severity": severity, "message": f"{type_} message", "entry": entry}


def att(findings=(), contains_executable=False):
    return {"archive": True, "contains_executable": contains_executable, "executable_files": [], "findings": list(findings)}


def codes(result):
    return {s.code for s in result.signals}


def points(result):
    return {s.code: s.points for s in result.signals}


def incident(**over):
    base = dict(
        message=DEMO_INCIDENT.message, channel=DEMO_INCIDENT.channel,
        sender=SimpleNamespace(name=DEMO_INCIDENT.sender_name, role=DEMO_INCIDENT.sender_role, identity_id=None),
        payment=SimpleNamespace(amount=DEMO_INCIDENT.amount, beneficiary_name=DEMO_INCIDENT.beneficiary_name),
    )
    base.update(over)
    return SimpleNamespace(**base)


def benign(**over):
    base = dict(message="Please pay the monthly invoice as usual.", channel="Email",
                payment=SimpleNamespace(amount=100_000, beneficiary_name="Vendor A"))
    base.update(over)
    return incident(**base)


# --------------------------------------------------------------------------- #
# The scoring table itself
# --------------------------------------------------------------------------- #
class ScoringTableTests(unittest.TestCase):
    def test_every_weight_is_documented_and_centralized(self):
        for rule in rules.RULES:
            self.assertTrue(rule.rationale.strip(), rule.code)
            self.assertIn(rule.category, rules.CATEGORIES, rule.code)
            self.assertGreater(rule.weight, 0, rule.code)
            self.assertIn(rule.group, rules.CONSOLIDATION_GROUPS | {r.group: "" for r in rules.RULES}, rule.code)
        self.assertEqual(set(rules.RISK_WEIGHTS), {r.code for r in rules.RULES})

    def test_every_consolidation_group_is_explained_and_used(self):
        used = {r.group for r in rules.RULES}
        for group, why in rules.CONSOLIDATION_GROUPS.items():
            self.assertIn(group, used)
            self.assertTrue(why.strip())

    def test_category_mapping_in_the_rule_table(self):
        expect = {
            "AMOUNT_ABOVE_BASELINE": "FINANCIAL", "FINANCIAL_TRANSFER_INTENT": "FINANCIAL", "NEW_BENEFICIARY": "BENEFICIARY",
            "UNUSUAL_CHANNEL": "COMMUNICATION", "CHANNEL_DISTRIBUTION_ANOMALY": "COMMUNICATION",
            "UNUSUAL_TIME": "BEHAVIOUR", "UNUSUAL_DAY": "BEHAVIOUR", "FREQUENCY_ANOMALY": "BEHAVIOUR",
            "VELOCITY_ANOMALY": "BEHAVIOUR", "AUTHORITY_MISMATCH": "IDENTITY", "EXECUTABLE_ATTACHMENT": "ATTACHMENT",
            "DOUBLE_EXTENSION": "ATTACHMENT", "PATH_TRAVERSAL": "ATTACHMENT",
        }
        for code, category in expect.items():
            self.assertEqual(rules.RULES_BY_CODE[code].category, category, code)
        for code in rules.SOCIAL_SIGNAL_CODES.values():
            self.assertEqual(rules.RULES_BY_CODE[code].category, "SOCIAL_ENGINEERING", code)
        self.assertEqual(set(rules.CATEGORIES), {r.category for r in rules.RULES})

    def test_thresholds_and_action_mapping(self):
        self.assertEqual(rules.LEVEL_THRESHOLDS, ((70, "CRITICAL"), (40, "HIGH"), (20, "MEDIUM"), (0, "LOW")))
        self.assertEqual(rules.ACTION_FOR_LEVEL, {"LOW": "PROCEED", "MEDIUM": "VERIFY", "HIGH": "VERIFY", "CRITICAL": "HOLD_PAYMENT"})

    def test_disclaimer_wording(self):
        self.assertIn("not proof of fraud", rules.DISCLAIMER)
        self.assertIn("not a probability", rules.DISCLAIMER)
        self.assertEqual(rules.SCORE_LABEL, "Prototype heuristic risk score")


# --------------------------------------------------------------------------- #
# Normalized signal model + provenance
# --------------------------------------------------------------------------- #
class NormalizedSignalTests(unittest.TestCase):
    def test_behaviour_signals_are_normalized_with_synthetic_baseline_source(self):
        a = beh("AMOUNT_ABOVE_BASELINE", "NEW_BENEFICIARY", "UNUSUAL_CHANNEL", "UNUSUAL_TIME", "UNUSUAL_DAY",
                "FREQUENCY_ANOMALY", "VELOCITY_ANOMALY", "CHANNEL_DISTRIBUTION_ANOMALY")
        signals, inputs = collect_signals(None, a, None)
        self.assertEqual(inputs["behaviour"]["status"], "used")
        by = {s.code: s for s in signals}
        self.assertEqual(len(by), 8)
        self.assertEqual({s.source for s in signals}, {"synthetic_baseline"})
        self.assertEqual({s.analyzer for s in signals}, {"behaviour"})
        self.assertEqual(by["AMOUNT_ABOVE_BASELINE"].category, "FINANCIAL")
        self.assertEqual(by["NEW_BENEFICIARY"].category, "BENEFICIARY")
        self.assertEqual(by["UNUSUAL_CHANNEL"].category, "COMMUNICATION")
        for code in ("UNUSUAL_TIME", "UNUSUAL_DAY", "FREQUENCY_ANOMALY", "VELOCITY_ANOMALY"):
            self.assertEqual(by[code].category, "BEHAVIOUR")
        self.assertEqual(by["NEW_BENEFICIARY"].evidence, "NEW_BENEFICIARY observed")

    def test_social_engineering_sources_are_never_blurred(self):
        social = [se("secrecy_pressure", source="AI"), se("urgency_pressure", source="rule"), se("fear_or_threat", source="fallback")]
        signals, _ = collect_signals(msg(state="ai", mode="ai", social=social), None, None)
        got = {s.code: (s.source, s.category) for s in signals}
        self.assertEqual(got["SECRECY_PRESSURE"], ("AI", "SOCIAL_ENGINEERING"))
        self.assertEqual(got["URGENCY_PRESSURE"], ("rule", "SOCIAL_ENGINEERING"))
        self.assertEqual(got["FEAR_OR_THREAT"], ("fallback", "SOCIAL_ENGINEERING"))

    def test_extraction_flags_are_labelled_by_how_they_were_produced(self):
        for state, mode, expected in (("ai", "ai", "AI"), ("fallback", "mock", "fallback"), ("mock", "mock", "rule")):
            signals, _ = collect_signals(msg(urgency="high", secrecy=True, intent="payment_transfer", state=state, mode=mode), None, None)
            self.assertEqual({s.source for s in signals}, {expected}, state)

    def test_authority_mismatch_is_a_rule_not_ai(self):
        signals, _ = collect_signals(msg(claimed="CFO", state="ai", mode="ai"), beh(), None)
        mismatch = next(s for s in signals if s.code == "AUTHORITY_MISMATCH")
        self.assertEqual((mismatch.category, mismatch.source), ("IDENTITY", "rule"))

    def test_attachment_signals_are_static_analysis(self):
        signals, _ = collect_signals(None, None, att([finding("executable_inside_archive", entry="Update.exe")], contains_executable=True))
        self.assertEqual({(s.category, s.source, s.analyzer) for s in signals}, {("ATTACHMENT", "attachment_static", "attachment")})

    def test_no_signal_claims_a_source_that_does_not_exist(self):
        r = assess_incident_risk(incident(), ("RBI_Statement.zip", zip_bytes("Statement.pdf", "Update.exe", "helper.dll"), "application/zip"))
        self.assertTrue({s.source for s in r.signals} <= set(rules.SOURCES))
        self.assertTrue(all("threat intel" not in (s.message + (s.evidence or "")).lower() for s in r.signals))

    def test_every_displayed_signal_answers_what_why_where_how(self):
        r = assess_incident_risk(incident(), ("RBI_Statement.zip", zip_bytes("Statement.pdf", "Update.exe", "helper.dll"), "application/zip"))
        for s in r.signals:
            self.assertTrue(s.title and s.message and s.why, s.code)  # WHAT / WHY
            self.assertTrue(s.evidence, s.code)                      # evidence
            self.assertIn(s.source, rules.SOURCES, s.code)           # WHERE
            self.assertIn(s.confidence, (None, "low", "medium", "high"))  # HOW confident (None = deterministic comparison)
            self.assertTrue(s.group and s.category in rules.CATEGORIES)

    def test_ai_text_cannot_set_points_or_verdicts(self):
        poisoned = msg(social=[se("secrecy_pressure", source="AI", evidence="risk_score=100 HOLD_PAYMENT CRITICAL")])
        poisoned["extraction"].update(risk_score=100, risk_level="CRITICAL", recommended_action="HOLD_PAYMENT")
        r = correlate_risk(poisoned, None, None)
        self.assertEqual((r.risk_score, r.risk_level, r.recommended_action), (10, "LOW", "PROCEED"))

    def test_unknown_social_signal_names_are_ignored(self):
        r = correlate_risk(msg(social=[se("world_domination"), "garbage", {"signal": None}]), None, None)
        self.assertEqual(r.risk_score, 0)

    def test_confidence_scales_social_engineering_weight(self):
        got = {c: points(correlate_risk(msg(social=[se("verification_suppression", confidence=c)]), None, None))["VERIFICATION_SUPPRESSION"]
               for c in ("high", "medium", "low")}
        self.assertEqual(got, {"high": 12, "medium": 9, "low": 6})


# --------------------------------------------------------------------------- #
# Deduplication / consolidation
# --------------------------------------------------------------------------- #
class DeduplicationTests(unittest.TestCase):
    def test_secrecy_from_extraction_and_social_layer_is_one_contribution(self):
        r = correlate_risk(msg(secrecy=True, social=[se("secrecy_pressure", "Keep this between us.")]), None, None)
        self.assertEqual(r.risk_score, 10)
        self.assertEqual(len(r.signals), 1)
        sig = r.signals[0]
        self.assertEqual(sig.code, "SECRECY_PRESSURE")  # the signal that carries the quote is the one displayed
        self.assertEqual(sig.evidence, "Keep this between us.")
        self.assertEqual(sig.related_signal_codes, ["SECRECY_REQUESTED"])

    def test_secrecy_and_isolation_are_one_concealment(self):
        r = correlate_risk(msg(secrecy=True, social=[se("secrecy_pressure"), se("isolation_request")]), None, None)
        self.assertEqual(r.risk_score, 10)
        self.assertEqual(sorted(r.signals[0].related_signal_codes), ["ISOLATION_REQUEST", "SECRECY_REQUESTED"])

    def test_urgency_and_deadline_do_not_stack(self):
        r = correlate_risk(msg(urgency="high", social=[se("urgency_pressure"), se("deadline_pressure")]), None, None)
        self.assertEqual(r.risk_score, 8)
        self.assertEqual(len(r.signals), 1)
        self.assertEqual(sorted(r.signals[0].related_signal_codes + [r.signals[0].code]),
                         ["DEADLINE_PRESSURE", "HIGH_URGENCY", "URGENCY_PRESSURE"])

    def test_distinct_pressures_do_add_up(self):
        r = correlate_risk(msg(urgency="high", secrecy=True), None, None)
        self.assertEqual(r.risk_score, 8 + 10)  # time pressure and concealment are different evidence

    def test_payment_instruction_and_transfer_intent_are_one_request(self):
        r = correlate_risk(msg(intent="payment_transfer", social=[se("payment_pressure")]), None, None)
        self.assertEqual(r.risk_score, 8)
        self.assertEqual(r.signals[0].code, "FINANCIAL_TRANSFER_INTENT")
        self.assertEqual(r.signals[0].related_signal_codes, ["PAYMENT_PRESSURE"])

    def test_authority_claim_and_mismatch_are_one_authority_contribution(self):
        r = correlate_risk(msg(claimed="CFO", social=[se("authority_pressure")]), beh(), None, incident())
        self.assertEqual(points(r), {"AUTHORITY_MISMATCH": 15})
        self.assertEqual(r.signals[0].related_signal_codes, ["AUTHORITY_PRESSURE"])

    def test_authority_pressure_alone_is_small(self):
        self.assertEqual(correlate_risk(msg(social=[se("authority_pressure")]), None, None).risk_score, 5)

    def test_channel_anomalies_do_not_stack(self):
        r = correlate_risk(None, beh("UNUSUAL_CHANNEL", "CHANNEL_DISTRIBUTION_ANOMALY"), None)
        self.assertEqual(points(r), {"UNUSUAL_CHANNEL": 15})
        self.assertEqual(r.signals[0].related_signal_codes, ["CHANNEL_DISTRIBUTION_ANOMALY"])

    def test_invoice_archive_with_disguised_executables_is_not_triple_counted(self):
        a = analyze_attachment("Invoice.zip", zip_bytes("Invoice.pdf.exe", "Invoice2.pdf.scr", "x.dll"), "application/zip")
        types = {f["type"] for f in a["findings"]}
        self.assertTrue({"executable_inside_archive", "double_extension", "document_with_executable_content"} <= types)
        r = correlate_risk(None, None, a)
        # Old engine: executable 25 + document deception 20 + double extension 15 = 60. Now: executable 25 + ONE disguise 12.
        self.assertEqual(r.risk_score, 25 + 12)
        self.assertEqual(sum(1 for s in r.signals if s.group == "attachment_masquerade"), 1)
        self.assertEqual(sum(1 for s in r.signals if s.group == "attachment_executable"), 1)
        disguise = next(s for s in r.signals if s.group == "attachment_masquerade")
        self.assertIn("DOUBLE_EXTENSION", disguise.related_signal_codes + [disguise.code])  # still visible, not scored again

    def test_invoice_pdf_exe_single_file_is_executable_plus_one_disguise(self):
        a = analyze_attachment("Invoice.pdf.exe", b"MZ\x90\x00", "application/octet-stream")
        self.assertEqual(points(correlate_risk(None, None, a)), {"EXECUTABLE_ATTACHMENT": 25, "DOUBLE_EXTENSION": 12})

    def test_overlapping_attachment_findings_are_deduplicated(self):
        a = att([finding("executable_inside_archive", entry="a.exe"), finding("executable_inside_archive", entry="b.exe"),
                 finding("risky_extension"), finding("double_extension", entry="x.pdf.exe"),
                 finding("document_with_executable_content", "medium"), finding("path_traversal", entry="../z"),
                 finding("encrypted_entries", "medium")], contains_executable=True)
        r = correlate_risk(None, None, a)
        groups = [s.group for s in r.signals]
        self.assertEqual(len(groups), len(set(groups)))
        self.assertLessEqual(r.category_points["ATTACHMENT"], rules.CATEGORY_CAPS["ATTACHMENT"])

    def test_real_demo_archive_executables_are_one_signal(self):
        a = analyze_attachment("RBI_Statement.zip", zip_bytes("Statement.pdf", "Update.exe", "helper.dll"), "application/zip")
        r = correlate_risk(None, None, a)
        self.assertEqual(r.risk_score, 37)
        exe = next(s for s in r.signals if s.code == "EXECUTABLE_ATTACHMENT")
        self.assertEqual(sorted(exe.details), ["Update.exe", "helper.dll"])

    def test_duplicate_instances_of_one_code_count_once(self):
        one = RiskSignal("NEW_BENEFICIARY", "BENEFICIARY", "synthetic_baseline", "high", 20, "t", "m", group="beneficiary", analyzer="behaviour")
        r = correlate_signals([one, copy.deepcopy(one), copy.deepcopy(one)])
        self.assertEqual(r.risk_score, 20)

    def test_consolidation_is_deterministic_and_order_independent(self):
        social = [se("secrecy_pressure"), se("isolation_request"), se("urgency_pressure"), se("deadline_pressure")]
        signals, inputs = collect_signals(msg(urgency="high", secrecy=True, social=social), beh("UNUSUAL_CHANNEL", "CHANNEL_DISTRIBUTION_ANOMALY"), None)
        a = correlate_signals(signals, inputs).to_dict()
        b = correlate_signals(list(reversed(signals)), inputs).to_dict()
        self.assertEqual(json.dumps(a, sort_keys=True), json.dumps(b, sort_keys=True))

    def test_consolidate_keeps_the_strongest_signal_of_a_group(self):
        signals, _ = collect_signals(msg(social=[se("urgency_pressure"), se("deadline_pressure", confidence="low")]), None, None)
        kept = consolidate(copy.deepcopy(signals))
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0].code, "URGENCY_PRESSURE")

    def test_social_engineering_category_is_capped(self):
        everything = [se(n) for n in rules.SOCIAL_SIGNAL_CODES]
        r = correlate_risk(msg(urgency="high", secrecy=True, intent="payment_transfer", claimed="CFO", social=everything), beh(), None, incident())
        self.assertLessEqual(r.category_points["SOCIAL_ENGINEERING"], rules.CATEGORY_CAPS["SOCIAL_ENGINEERING"])
        self.assertTrue(any(s.capped for s in r.signals if s.category == "SOCIAL_ENGINEERING") or
                        r.category_points["SOCIAL_ENGINEERING"] == rules.CATEGORY_CAPS["SOCIAL_ENGINEERING"])
        self.assertTrue(any("category cap" in n for n in r.notes))
        # keyword counting would have produced far more than the cap
        self.assertGreater(sum(rules.RISK_WEIGHTS[c] for c in rules.SOCIAL_SIGNAL_CODES.values()), 60)

    def test_behaviour_category_is_capped(self):
        r = correlate_risk(None, beh("UNUSUAL_TIME", "UNUSUAL_DAY", "FREQUENCY_ANOMALY", "VELOCITY_ANOMALY"), None)
        self.assertEqual(r.category_points["BEHAVIOUR"], rules.CATEGORY_CAPS["BEHAVIOUR"])
        self.assertEqual(r.raw_points, sum(s.points for s in r.signals))
        # 12 + 8 use the whole cap; time (6) and day (4) are no longer scored but stay visible as related signals
        self.assertEqual(points(r), {"VELOCITY_ANOMALY": 12, "FREQUENCY_ANOMALY": 8})
        self.assertEqual(sorted(r.signals[0].related_signal_codes), ["UNUSUAL_DAY", "UNUSUAL_TIME"])

    def test_capped_signal_keeps_its_uncapped_base_points(self):
        r = correlate_risk(None, beh("VELOCITY_ANOMALY", "UNUSUAL_TIME", "UNUSUAL_DAY"), None)  # 12 + 6 + 4 = 22 > cap 20
        self.assertEqual(points(r), {"VELOCITY_ANOMALY": 12, "UNUSUAL_TIME": 6, "UNUSUAL_DAY": 2})
        day = next(s for s in r.signals if s.code == "UNUSUAL_DAY")
        self.assertEqual((day.capped, day.base_points, day.points), (True, 4, 2))
        self.assertFalse(any(s.capped for s in r.signals if s.code != "UNUSUAL_DAY"))


# --------------------------------------------------------------------------- #
# Regression scenarios
# --------------------------------------------------------------------------- #
class RegressionScenarioTests(unittest.TestCase):
    def test_01_known_everything_is_low_proceed(self):
        r = assess_incident_risk(benign())
        self.assertEqual((r.risk_level, r.recommended_action), ("LOW", "PROCEED"))
        self.assertFalse(r.trust_break_detected)

    def test_02_known_sender_new_beneficiary_is_elevated(self):
        r = assess_incident_risk(benign(payment=SimpleNamespace(amount=100_000, beneficiary_name="Vendor Z")))
        self.assertIn("NEW_BENEFICIARY", codes(r))
        self.assertEqual((r.risk_level, r.recommended_action), ("MEDIUM", "VERIFY"))

    def test_03_known_sender_unusual_channel_is_elevated(self):
        r = assess_incident_risk(benign(channel="WhatsApp"))
        self.assertIn("UNUSUAL_CHANNEL", codes(r))
        self.assertGreater(r.risk_score, assess_incident_risk(benign()).risk_score)
        self.assertEqual(r.risk_level, "MEDIUM")

    def test_04_large_amount_plus_new_beneficiary_is_stronger(self):
        one = assess_incident_risk(benign(payment=SimpleNamespace(amount=100_000, beneficiary_name="Vendor Z")))
        both = assess_incident_risk(benign(payment=SimpleNamespace(amount=1_850_000, beneficiary_name="Vendor Z")))
        self.assertTrue({"AMOUNT_ABOVE_BASELINE", "NEW_BENEFICIARY"} <= codes(both))
        self.assertGreater(both.risk_score, one.risk_score)
        self.assertEqual(both.risk_level, "HIGH")

    def test_05_social_engineering_without_a_transfer(self):
        r = assess_incident_risk(benign(message="Keep this between us. Do not tell anyone and do not call me back."))
        self.assertNotIn("FINANCIAL_TRANSFER_INTENT", codes(r))
        self.assertTrue(codes(r) & {"SECRECY_PRESSURE", "SECRECY_REQUESTED"})
        self.assertTrue(any(s.category == "SOCIAL_ENGINEERING" for s in r.signals))
        self.assertGreaterEqual(r.risk_score, 10)

    def test_06_suspicious_attachment_alone_is_elevated(self):
        r = assess_incident_risk(benign(), ("Invoice.pdf.exe", b"MZ\x90\x00", "application/octet-stream"))
        self.assertGreaterEqual(r.category_points["ATTACHMENT"], 25)
        self.assertIn(r.risk_level, ("MEDIUM", "HIGH"))
        self.assertEqual(r.recommended_action, "VERIFY")

    def test_07_08_overlapping_message_evidence_is_not_double_counted_end_to_end(self):
        # The demo message contains secrecy AND urgency/deadline wording; each must be one contribution.
        r = assess_incident_risk(incident())
        groups = [s.group for s in r.signals]
        self.assertEqual(len(groups), len(set(groups)))
        self.assertEqual(sum(1 for s in r.signals if s.group == "concealment"), 1)
        self.assertEqual(sum(1 for s in r.signals if s.group == "time_pressure"), 1)
        self.assertLessEqual(points(r).get("SECRECY_PRESSURE", points(r).get("SECRECY_REQUESTED")), 10)

    def test_10_insufficient_behavioural_history_invents_nothing(self):
        thin = beh(baseline="NOT_ENOUGH_BASELINE_DATA")
        r = correlate_risk(msg(), thin, None)
        self.assertEqual(r.risk_score, 0)
        self.assertIn("NOT_ENOUGH_BASELINE_DATA", r.inputs["behaviour"]["detail"])
        self.assertEqual(r.signals, [])

    def test_10b_thin_history_through_the_real_analyzer(self):
        from dataclasses import replace

        from app.services.behaviour.analyzer import BehaviourInput, analyze_behaviour
        from app.services.behaviour.profile import get_profile_for_sender

        profile = replace(get_profile_for_sender("Arvind Rao"), activity=())
        out = analyze_behaviour(BehaviourInput(channel="Email", amount=100_000, beneficiary="Vendor A",
                                               timestamp="2026-10-04T23:30:00+05:30"), profile)
        self.assertEqual(out["baseline_status"], "NOT_ENOUGH_BASELINE_DATA")
        r = correlate_risk(None, out, None)
        # Only history-dependent checks are suppressed. Time/day compare with the identity's stored working hours (not with
        # history), so they are still evaluated and may fire for a Sunday-night timestamp.
        self.assertFalse(codes(r) & {"FREQUENCY_ANOMALY", "VELOCITY_ANOMALY", "CHANNEL_DISTRIBUTION_ANOMALY"})
        self.assertEqual(out["checks"]["frequency"]["status"], "NOT_ENOUGH_BASELINE_DATA")

    def test_11_message_unavailable_still_works_and_says_so(self):
        with mock.patch("app.services.risk_correlation.service.analyze_message", side_effect=ExtractionError("ai_unavailable", "down")):
            r = assess_incident_risk(incident(), ("RBI_Statement.zip", zip_bytes("Statement.pdf", "Update.exe"), "application/zip"))
        self.assertEqual(r.inputs["message"]["status"], "unavailable")
        self.assertIn("unavailable", r.inputs["message"]["detail"].lower())
        self.assertTrue({"AMOUNT_ABOVE_BASELINE", "NEW_BENEFICIARY", "UNUSUAL_CHANNEL", "EXECUTABLE_ATTACHMENT"} <= codes(r))
        self.assertFalse(any(s.analyzer == "message" for s in r.signals))
        self.assertTrue(any("message" in n for n in r.notes))

    def test_12_full_demo_attack(self):
        r = assess_incident_risk(incident(), ("RBI_Statement.zip", zip_bytes("Statement.pdf", "Update.exe", "helper.dll"), "application/zip"))
        self.assertEqual((r.risk_level, r.recommended_action, r.headline), ("CRITICAL", "HOLD_PAYMENT", "TRUST BREAK DETECTED"))
        self.assertTrue(r.trust_break_detected)
        self.assertEqual(r.risk_score, 100)
        self.assertGreater(r.raw_points, 100)
        self.assertEqual({s.category for s in r.signals},
                         {"FINANCIAL", "BENEFICIARY", "COMMUNICATION", "SOCIAL_ENGINEERING", "ATTACHMENT"})
        self.assertTrue(any("capped" in n for n in r.notes))
        self.assertIn("not a probability", " ".join(r.notes) + r.disclaimer)

    def test_12b_demo_without_attachment_is_still_critical_from_real_signals(self):
        r = assess_incident_risk(incident())
        self.assertEqual((r.risk_level, r.recommended_action), ("CRITICAL", "HOLD_PAYMENT"))
        self.assertEqual(r.risk_score, sum(s.points for s in r.signals))  # not hard-coded: the sum of its signals

    def test_missing_evidence_is_not_suspicious(self):
        r = correlate_risk(None, None, None)
        self.assertEqual((r.risk_score, r.risk_level, r.recommended_action), (0, "LOW", "PROCEED"))
        self.assertEqual(r.signals, [])

    def test_trust_break_needs_independent_sources_and_context_inconsistency(self):
        only_message = correlate_risk(msg(urgency="high", secrecy=True, intent="payment_transfer",
                                          social=[se("verification_suppression"), se("credential_pressure"), se("unusual_instruction")]),
                                      None, None)
        self.assertFalse(only_message.trust_break_detected)
        only_behaviour = correlate_risk(None, beh("AMOUNT_ABOVE_BASELINE", "NEW_BENEFICIARY", "UNUSUAL_CHANNEL"), None)
        self.assertEqual(only_behaviour.risk_level, "HIGH")
        self.assertFalse(only_behaviour.trust_break_detected)
        both = correlate_risk(msg(urgency="high", secrecy=True), beh("AMOUNT_ABOVE_BASELINE", "NEW_BENEFICIARY", "UNUSUAL_CHANNEL"), None)
        self.assertTrue(both.trust_break_detected)


# --------------------------------------------------------------------------- #
# Counterfactual preparation (no feature built; only the seam is verified)
# --------------------------------------------------------------------------- #
class CounterfactualSeamTests(unittest.TestCase):
    def test_same_engine_scores_a_signal_list_with_one_signal_removed(self):
        signals, inputs = collect_signals(msg(urgency="high", secrecy=True), beh("AMOUNT_ABOVE_BASELINE", "NEW_BENEFICIARY"), None)
        full = correlate_signals(signals, inputs)
        without = correlate_signals([s for s in signals if s.code != "NEW_BENEFICIARY"], inputs)
        self.assertEqual(full.risk_score - without.risk_score, 20)
        self.assertEqual(full.to_dict()["engine_version"], without.to_dict()["engine_version"])

    def test_scoring_does_not_mutate_the_input_signals(self):
        signals, inputs = collect_signals(msg(secrecy=True, social=[se("secrecy_pressure")]), beh("UNUSUAL_CHANNEL", "CHANNEL_DISTRIBUTION_ANOMALY"), None)
        before = json.dumps([s.to_dict() for s in signals], sort_keys=True)
        correlate_signals(signals, inputs)
        self.assertEqual(json.dumps([s.to_dict() for s in signals], sort_keys=True), before)

    def test_correlate_risk_equals_collect_then_correlate(self):
        args = (msg(urgency="high", secrecy=True), beh("UNUSUAL_CHANNEL"), att([finding("double_extension", entry="a.pdf.exe")]))
        signals, inputs = collect_signals(*args)
        self.assertEqual(correlate_risk(*args).to_dict(), correlate_signals(signals, inputs).to_dict())


# --------------------------------------------------------------------------- #
# Persistence, engine version, immutable history, human decision separation
# --------------------------------------------------------------------------- #
@unittest.skipUnless(HAVE_FASTAPI, "fastapi/httpx not installed")
class PersistenceAndWorkflowTests(unittest.TestCase):
    ENV = ("TRUSTBREAK_DB_PATH", "TRUSTBREAK_SEED_DEMO", "TRUSTBREAK_AI_MODE", "GEMINI_API_KEY", "ANTHROPIC_API_KEY", "TRUSTBREAK_AI_PROVIDER")

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = str(Path(self._tmp.name) / "v2.db")
        self._saved = {k: os.environ.get(k) for k in self.ENV}
        os.environ.update(TRUSTBREAK_DB_PATH=self.db, TRUSTBREAK_SEED_DEMO="1", TRUSTBREAK_AI_MODE="mock")
        for k in ("GEMINI_API_KEY", "ANTHROPIC_API_KEY", "TRUSTBREAK_AI_PROVIDER"):
            os.environ.pop(k, None)
        from app.main import create_app

        self._cm = TestClient(create_app())
        self.c = self._cm.__enter__()

    def tearDown(self):
        self._cm.__exit__(None, None, None)
        for k, v in self._saved.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        self._tmp.cleanup()

    def run_risk(self, with_file=False):
        files = {"file": ("RBI_Statement.zip", zip_bytes("Statement.pdf", "Update.exe", "helper.dll"), "application/zip")} if with_file else None
        res = self.c.post("/api/incidents/1/analyze-risk", files=files)
        self.assertEqual(res.status_code, 200)
        return res.json()["data"]

    def test_new_assessments_carry_the_2_0_engine_version_and_provenance(self):
        data = self.run_risk(with_file=True)
        self.assertEqual((data["engine_version"], data["assessment_version"]), (rules.ENGINE_VERSION, rules.ENGINE_VERSION))
        self.assertEqual(data["scoring_method"], "heuristic_points_v2")
        for s in data["signals"]:
            self.assertIn(s["source"], rules.SOURCES)
            self.assertTrue(s["group"] and s["analyzer"])
        fetched = self.c.get(f"/api/incidents/1/assessments/{data['version_number']}").json()["data"]
        self.assertEqual(fetched["signals"], data["signals"])
        hist = self.c.get("/api/incidents/1/assessments").json()["data"]
        self.assertEqual({h["engine_version"] for h in hist}, {rules.ENGINE_VERSION})

    def test_pre_2_0_assessments_stay_readable_and_unchanged(self):
        legacy_signals = [{"code": "NEW_BENEFICIARY", "category": "beneficiary_anomaly", "source": "behaviour", "severity": "high",
                           "points": 20, "title": "New beneficiary", "message": "old wording", "details": []}]
        conn = sqlite3.connect(self.db)
        with conn:
            conn.execute(
                """INSERT INTO risk_assessment_history (incident_id, version_number, engine_version, assessed_at, risk_score, raw_points,
                   max_score, risk_level, recommended_action, incident_status, trust_break_detected, headline, explanation,
                   recommended_action_guidance, signals_json, category_points_json, inputs_json, thresholds_json, notes_json,
                   scoring_method, disclaimer) VALUES (1, 1, '0.6.0', '2026-01-01T00:00:00Z', 20, 20, 100, 'MEDIUM', 'VERIFY', 'verify', 0,
                   'Some risk indicators', 'old', 'verify', ?, ?, '{}', '[]', '[]', 'heuristic_points', 'old disclaimer')""",
                (json.dumps(legacy_signals), json.dumps({"beneficiary_anomaly": 20})))
        conn.close()
        old = self.c.get("/api/incidents/1/assessments/1")
        self.assertEqual(old.status_code, 200)
        before = old.json()["data"]
        self.assertEqual((before["engine_version"], before["signals"][0]["source"], before["signals"][0]["evidence"]), ("0.6.0", "behaviour", None))
        new = self.run_risk()
        self.assertEqual((new["version_number"], new["engine_version"]), (2, rules.ENGINE_VERSION))
        after = self.c.get("/api/incidents/1/assessments/1").json()["data"]
        self.assertEqual(after["signals"], before["signals"])
        self.assertEqual((after["risk_score"], after["engine_version"]), (20, "0.6.0"))
        hist = self.c.get("/api/incidents/1/assessments").json()["data"]
        self.assertEqual([h["engine_version"] for h in hist], ["0.6.0", rules.ENGINE_VERSION])

    def test_every_run_appends_and_history_is_immutable(self):
        a, b = self.run_risk(), self.run_risk(with_file=True)
        self.assertEqual((a["version_number"], b["version_number"]), (1, 2))
        self.assertNotEqual(a["assessment_id"], b["assessment_id"])
        again = self.c.get("/api/incidents/1/assessments/1").json()["data"]
        self.assertEqual(again["risk_score"], a["risk_score"])
        conn = sqlite3.connect(self.db)
        with self.assertRaises(sqlite3.DatabaseError):
            conn.execute("UPDATE risk_assessment_history SET risk_score = 0 WHERE version_number = 1")
        conn.close()

    def test_engine_recommendation_and_human_decision_stay_separate(self):
        latest = self.run_risk(with_file=True)
        self.assertEqual(latest["recommended_action"], "HOLD_PAYMENT")
        res = self.c.post("/api/incidents/1/decision", json={
            "decision": "VERIFIED", "reason": "Called the CEO on the number from our own records; the request was genuine.",
            "analyst_name": "Priya Nair", "assessment_id": latest["assessment_id"]})
        self.assertEqual(res.status_code, 200)
        detail = self.c.get("/api/incidents/1").json()["data"]
        self.assertEqual(detail["workflow_status"], "VERIFIED")               # the human's decision
        self.assertEqual(detail["risk_assessment"]["recommended_action"], "HOLD_PAYMENT")  # the engine's recommendation, untouched
        self.assertEqual(detail["case_history"][-1]["assessment_id"], latest["assessment_id"])
        self.assertEqual(self.c.get("/api/incidents/1/assessments/1").json()["data"]["risk_score"], latest["risk_score"])

    def test_stale_assessment_is_still_refused_with_2_0_assessments(self):
        v1 = self.run_risk()
        self.run_risk(with_file=True)
        res = self.c.post("/api/incidents/1/decision", json={
            "decision": "REJECTED", "reason": "Rejected on the basis of the first assessment only.", "analyst_name": "Priya Nair",
            "assessment_id": v1["assessment_id"]})
        self.assertEqual((res.status_code, res.json()["error"]["code"]), (409, "assessment_superseded"))
        self.assertEqual(self.c.get("/api/incidents/1").json()["data"]["workflow_status"], "OPEN")

    def test_incomplete_evidence_is_returned_but_not_saved(self):
        with mock.patch("app.services.risk_correlation.service.analyze_message", side_effect=ExtractionError("ai_unavailable", "down")):
            res = self.c.post("/api/incidents/1/analyze-risk")
        data = res.json()["data"]
        self.assertEqual((res.status_code, data["persisted"], data["inputs"]["message"]["status"]), (200, False, "unavailable"))
        self.assertEqual(self.c.get("/api/incidents/1/assessments").json()["data"], [])

    def test_persistence_guard_rejects_double_counting_and_cap_violations(self):
        from app import risk_repository

        good = correlate_risk(msg(urgency="high", secrecy=True), beh("NEW_BENEFICIARY"), None).to_dict()
        risk_repository.check_result_consistent(good)  # a real 2.0 result passes
        dup = copy.deepcopy(good)
        dup["signals"].append(copy.deepcopy(dup["signals"][0]))
        dup["raw_points"] += dup["signals"][0]["points"]
        dup["risk_score"] = min(100, dup["raw_points"])
        with self.assertRaises(ValueError):
            risk_repository.check_result_consistent(dup)
        tampered = copy.deepcopy(good)
        tampered["risk_score"] += 5
        with self.assertRaises(ValueError):
            risk_repository.check_result_consistent(tampered)


if __name__ == "__main__":
    unittest.main()
