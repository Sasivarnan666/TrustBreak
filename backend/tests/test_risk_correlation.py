"""Unit tests for the risk correlation engine (stdlib only; no FastAPI needed).

Scores are HEURISTIC RISK POINTS, not probabilities. Thresholds are prototype
values: 0-19 LOW, 20-39 MEDIUM, 40-69 HIGH, 70+ CRITICAL.
"""

import ast
import io
import json
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from app.seed import DEMO_INCIDENT
from app.services.attachment_analysis import AttachmentError, analyze_attachment
from app.services.behaviour import analyze_incident_behaviour
from app.services.message_analysis import ExtractionError, analyze_message
from app.services.risk_correlation import (
    action_for_level,
    assess_incident_risk,
    correlate_risk,
    level_for_score,
    rules,
)

APP = Path(__file__).resolve().parents[1] / "app"


def imported_modules(path: Path) -> set:
    """Every module name a file imports (real imports only, not words in docstrings)."""
    names = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.add(("." * node.level) + (node.module or ""))
            names.update(("." * node.level) + (node.module or "") + "." + a.name for a in node.names)
    return names


def called_names(path: Path) -> set:
    out = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Call):
            fn = node.func
            out.add(fn.id if isinstance(fn, ast.Name) else getattr(fn, "attr", ""))
    return out


# --------------------------------------------------------------------------- #
# Builders
# --------------------------------------------------------------------------- #
def msg(urgency="none", secrecy=False, intent="none", claimed=None, mode="mock", deadline=None):
    return {
        "mode": mode, "model": None, "notes": [], "fallback_reason": None, "is_final_decision": False,
        "extraction": {
            "claimed_authority": claimed, "requested_action": None, "payment_amount": None, "currency": None,
            "beneficiary": None, "urgency_level": urgency, "secrecy_indicator": secrecy, "organization": None,
            "deadline": deadline, "financial_intent": intent, "extracted_entities": [], "confidence": 0.9,
        },
    }


def beh(amount=False, beneficiary=False, channel=False, found=True, role="Chief Executive Officer"):
    anomalies = []
    for flag, code in ((amount, "AMOUNT_ABOVE_BASELINE"), (beneficiary, "NEW_BENEFICIARY"), (channel, "UNUSUAL_CHANNEL")):
        if flag:
            anomalies.append({"type": "x", "code": code, "severity": "high", "message": f"{code} message"})
    return {
        "employee_id": "CEO-001" if found else None, "profile_found": found, "amount_anomaly": amount,
        "new_beneficiary": beneficiary, "channel_anomaly": channel, "frequency_anomaly": False, "checks": {},
        "anomalies": anomalies, "profile_summary": {"role": role} if found else None, "notes": [],
        "is_final_decision": False,
    }


def att(findings=(), contains_executable=False, archive=True, executable_files=()):
    return {
        "file_name": "x.zip", "archive": archive, "contains_executable": contains_executable,
        "executable_files": list(executable_files), "findings": list(findings), "notes": [],
        "is_final_decision": False,
    }


def f(type_, severity="high", entry=None):
    return {"type": type_, "severity": severity, "message": "m", "entry": entry}


def codes(result):
    return {s.code for s in result.signals}


def incident(role="Chief Executive Officer"):
    return SimpleNamespace(sender=SimpleNamespace(name="Arvind Rao", role=role))


def zip_bytes(names):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for n in names:
            z.writestr(n, "inert")
    return buf.getvalue()


def demo_incident(**overrides):
    base = dict(
        message=DEMO_INCIDENT.message, channel=DEMO_INCIDENT.channel,
        sender=SimpleNamespace(name=DEMO_INCIDENT.sender_name, role=DEMO_INCIDENT.sender_role),
        payment=SimpleNamespace(amount=DEMO_INCIDENT.amount, beneficiary_name=DEMO_INCIDENT.beneficiary_name),
    )
    base.update(overrides)
    return SimpleNamespace(**base)


# --------------------------------------------------------------------------- #
# Individual signals and scores
# --------------------------------------------------------------------------- #
class SingleSignalTests(unittest.TestCase):
    def test_no_signals_is_low_and_proceed(self):
        r = correlate_risk(msg(), beh(), att())
        self.assertEqual((r.risk_score, r.risk_level, r.recommended_action), (0, "LOW", "PROCEED"))
        self.assertEqual(r.signals, [])
        self.assertFalse(r.trust_break_detected)
        self.assertEqual(r.headline, "No risk indicators")

    def test_only_urgency_is_low(self):
        r = correlate_risk(msg(urgency="high"), None, None)
        self.assertEqual((r.risk_score, r.risk_level, r.recommended_action), (8, "LOW", "PROCEED"))
        self.assertEqual(codes(r), {"HIGH_URGENCY"})

    def test_medium_urgency_earns_no_points(self):
        self.assertEqual(correlate_risk(msg(urgency="medium"), None, None).risk_score, 0)

    def test_secrecy_is_ten_and_financial_intent_is_eight(self):  # 2.0 weights (was ten each)
        self.assertEqual(correlate_risk(msg(secrecy=True), None, None).risk_score, 10)
        self.assertEqual(correlate_risk(msg(intent="payment_transfer"), None, None).risk_score, 8)
        self.assertEqual(correlate_risk(msg(intent="none"), None, None).risk_score, 0)
        self.assertEqual(correlate_risk(msg(intent="credential_or_otp_request"), None, None).risk_score, 0)

    def test_new_beneficiary(self):
        r = correlate_risk(None, beh(beneficiary=True), None)
        self.assertEqual((r.risk_score, r.risk_level, r.recommended_action), (20, "MEDIUM", "VERIFY"))
        self.assertEqual(codes(r), {"NEW_BENEFICIARY"})

    def test_amount_anomaly(self):
        r = correlate_risk(None, beh(amount=True), None)
        self.assertEqual((r.risk_score, r.risk_level, r.recommended_action), (20, "MEDIUM", "VERIFY"))
        self.assertEqual(codes(r), {"AMOUNT_ABOVE_BASELINE"})

    def test_channel_anomaly_is_below_medium_threshold(self):
        r = correlate_risk(None, beh(channel=True), None)
        self.assertEqual((r.risk_score, r.risk_level, r.recommended_action), (15, "LOW", "PROCEED"))
        self.assertEqual(codes(r), {"UNUSUAL_CHANNEL"})

    def test_suspicious_attachment_executable(self):
        r = correlate_risk(None, None, att([f("executable_inside_archive", entry="Update.exe")], contains_executable=True))
        self.assertEqual((r.risk_score, r.risk_level, r.recommended_action), (25, "MEDIUM", "VERIFY"))
        self.assertEqual(codes(r), {"EXECUTABLE_ATTACHMENT"})

    def test_behaviour_signal_uses_upstream_message(self):
        r = correlate_risk(None, beh(amount=True), None)
        self.assertEqual(r.signals[0].message, "AMOUNT_ABOVE_BASELINE message")

    def test_severity_follows_points(self):
        r = correlate_risk(msg(urgency="high"), beh(amount=True, channel=True), None)
        sev = {s.code: s.severity for s in r.signals}
        self.assertEqual(sev, {"AMOUNT_ABOVE_BASELINE": "high", "UNUSUAL_CHANNEL": "medium", "HIGH_URGENCY": "low"})

    def test_document_double_extension_path_traversal_and_other_high(self):
        self.assertEqual(correlate_risk(None, None, att([f("document_with_executable_content", "medium")])).risk_score, 12)
        self.assertEqual(correlate_risk(None, None, att([f("double_extension", entry="a.pdf.exe")])).risk_score, 12)
        self.assertEqual(correlate_risk(None, None, att([f("path_traversal", entry="../x")])).risk_score, 12)
        self.assertEqual(correlate_risk(None, None, att([f("content_type_mismatch", "high")])).risk_score, 8)


# --------------------------------------------------------------------------- #
# Authority mismatch (only with reliable evidence)
# --------------------------------------------------------------------------- #
class AuthorityTests(unittest.TestCase):
    def test_mismatch_when_both_roles_are_known_and_differ(self):
        r = correlate_risk(msg(claimed="the CFO"), beh(), None, incident())
        self.assertEqual(r.risk_score, 15)
        self.assertEqual(codes(r), {"AUTHORITY_MISMATCH"})
        self.assertIn("recorded as", r.signals[0].message)

    def test_no_mismatch_when_roles_agree(self):
        self.assertEqual(correlate_risk(msg(claimed="CEO"), beh(), None, incident()).risk_score, 0)
        self.assertEqual(correlate_risk(msg(claimed="Chief Executive Officer"), beh(), None, incident()).risk_score, 0)

    def test_no_mismatch_without_reliable_evidence(self):
        # claimed authority missing, unknown title, or no recorded role at all
        self.assertEqual(correlate_risk(msg(claimed=None), beh(), None, incident()).risk_score, 0)
        self.assertEqual(correlate_risk(msg(claimed="the Pope"), beh(), None, incident()).risk_score, 0)
        self.assertEqual(correlate_risk(msg(claimed="CFO"), None, None, None).risk_score, 0)
        self.assertEqual(correlate_risk(msg(claimed="CFO"), None, None, incident(role="Manager")).risk_score, 0)

    def test_ambiguous_claim_is_not_a_mismatch(self):
        self.assertEqual(correlate_risk(msg(claimed="CEO and CFO"), beh(), None, incident()).risk_score, 0)

    def test_profile_role_is_preferred_over_submitted_role(self):
        r = correlate_risk(msg(claimed="CEO"), beh(role="Chief Executive Officer"), None, incident(role="Chief Financial Officer"))
        self.assertEqual(r.risk_score, 0)


# --------------------------------------------------------------------------- #
# Correlation, levels and actions
# --------------------------------------------------------------------------- #
class CorrelationTests(unittest.TestCase):
    def test_multiple_independent_signals_are_high(self):
        r = correlate_risk(msg(urgency="high"), beh(amount=True, beneficiary=True), None)
        self.assertEqual((r.risk_score, r.risk_level, r.recommended_action), (48, "HIGH", "VERIFY"))

    def test_many_signals_are_critical_hold_payment(self):
        r = correlate_risk(msg(urgency="high", secrecy=True), beh(amount=True, beneficiary=True, channel=True), None)
        self.assertEqual((r.risk_score, r.risk_level, r.recommended_action), (73, "CRITICAL", "HOLD_PAYMENT"))
        self.assertTrue(r.trust_break_detected)

    def test_score_is_capped_but_raw_points_are_reported(self):
        r = correlate_risk(
            msg(urgency="high", secrecy=True, intent="payment_transfer", claimed="CFO"),
            beh(amount=True, beneficiary=True, channel=True),
            att([f("executable_inside_archive"), f("document_with_executable_content", "medium"), f("double_extension"),
                 f("path_traversal"), f("encrypted_entries", "high")], contains_executable=True),
            incident(),
        )
        # message 8+10+8 + authority mismatch 15 + behaviour 20+20+15 + attachment (25 + 12 masquerade + 12 path
        # traversal = 49, limited to the 40-point attachment cap; the encrypted-entries finding is consolidated away)
        self.assertEqual(r.raw_points, 8 + 10 + 8 + 15 + 20 + 20 + 15 + 40)
        self.assertEqual(r.raw_points, sum(s.points for s in r.signals))
        self.assertEqual(r.risk_score, 100)
        self.assertTrue(any("capped" in n for n in r.notes))

    def test_trust_break_needs_context_inconsistency_and_two_sources(self):
        # message + attachment only: CRITICAL but no inconsistency with the sender's behaviour
        r = correlate_risk(msg(urgency="high", secrecy=True, intent="payment_transfer"),
                           None, att([f("executable_inside_archive"), f("document_with_executable_content", "medium")],
                                     contains_executable=True))
        self.assertEqual(r.risk_level, "HIGH")  # 2.0: 8+10+8 message + 25+12 attachment = 63
        self.assertFalse(r.trust_break_detected)
        self.assertEqual(r.headline, "Elevated risk indicators")
        # a single source, even if HIGH, is not a trust break
        r = correlate_risk(None, beh(amount=True, beneficiary=True), None)
        self.assertEqual(r.risk_level, "HIGH")
        self.assertFalse(r.trust_break_detected)

    def test_level_boundaries(self):
        expected = {0: "LOW", 19: "LOW", 20: "MEDIUM", 39: "MEDIUM", 40: "HIGH", 69: "HIGH", 70: "CRITICAL", 100: "CRITICAL"}
        for score, level in expected.items():
            self.assertEqual(level_for_score(score), level, score)
        for bad in (None, "x", float("nan"), True, -5):
            self.assertEqual(level_for_score(bad), "LOW")

    def test_boundaries_reached_through_real_combinations(self):
        self.assertEqual(correlate_risk(None, beh(amount=True, channel=True), None).risk_score, 35)  # MEDIUM
        r40 = correlate_risk(None, beh(amount=True, beneficiary=True), None)
        self.assertEqual((r40.risk_score, r40.risk_level), (40, "HIGH"))
        r55 = correlate_risk(None, beh(amount=True, beneficiary=True, channel=True), None)
        self.assertEqual((r55.risk_score, r55.risk_level), (55, "HIGH"))
        r70 = correlate_risk(msg(claimed="CFO"), beh(amount=True, beneficiary=True, channel=True), None, incident())
        self.assertEqual((r70.risk_score, r70.risk_level, r70.recommended_action), (70, "CRITICAL", "HOLD_PAYMENT"))

    def test_action_mapping(self):
        self.assertEqual(
            [action_for_level(x) for x in ("LOW", "MEDIUM", "HIGH", "CRITICAL")],
            ["PROCEED", "VERIFY", "VERIFY", "HOLD_PAYMENT"],
        )
        self.assertEqual(action_for_level("???"), "VERIFY")

    def test_documented_weights(self):
        expected = {
            "AUTHORITY_MISMATCH": 15, "UNUSUAL_CHANNEL": 15, "CHANNEL_DISTRIBUTION_ANOMALY": 6,
            "AMOUNT_ABOVE_BASELINE": 20, "FINANCIAL_TRANSFER_INTENT": 8, "NEW_BENEFICIARY": 20,
            "UNUSUAL_TIME": 6, "UNUSUAL_DAY": 4, "FREQUENCY_ANOMALY": 8, "VELOCITY_ANOMALY": 12,
            "HIGH_URGENCY": 8, "URGENCY_PRESSURE": 8, "DEADLINE_PRESSURE": 8, "SECRECY_REQUESTED": 10,
            "SECRECY_PRESSURE": 10, "ISOLATION_REQUEST": 8, "VERIFICATION_SUPPRESSION": 12, "FEAR_OR_THREAT": 8,
            "PAYMENT_PRESSURE": 5, "CREDENTIAL_PRESSURE": 12, "IMPERSONATION_CUE": 8, "UNUSUAL_INSTRUCTION": 10,
            "AUTHORITY_PRESSURE": 5, "EXECUTABLE_ATTACHMENT": 25, "RISKY_EXTENSION": 20,
            "DOCUMENT_WITH_EXECUTABLE": 12, "DOUBLE_EXTENSION": 12, "PATH_TRAVERSAL": 12,
            "OTHER_HIGH_SEVERITY_ATTACHMENT_FINDING": 8, "SUSPICIOUS_STRUCTURE": 5,
        }
        self.assertEqual(rules.RISK_WEIGHTS, expected)
        self.assertEqual({r.code: r.weight for r in rules.RULES}, expected)
        self.assertEqual(len(rules.RULES_BY_CODE), len(rules.RULES))  # one rule per code


# --------------------------------------------------------------------------- #
# Missing / odd input
# --------------------------------------------------------------------------- #
class RobustnessTests(unittest.TestCase):
    def test_everything_missing(self):
        r = correlate_risk(None, None, None, None)
        self.assertEqual((r.risk_score, r.risk_level, r.recommended_action), (0, "LOW", "PROCEED"))
        self.assertEqual({v["status"] for v in r.inputs.values()}, {"not_provided"})
        self.assertTrue(r.notes)

    def test_no_message_analysis(self):
        r = correlate_risk(None, beh(amount=True), att())
        self.assertEqual(r.inputs["message"]["status"], "not_provided")
        self.assertEqual(r.risk_score, 20)

    def test_unavailable_message_reason_is_reported(self):
        r = correlate_risk(None, beh(), None, unavailable={"message": "Message analysis was unavailable (ai_unavailable)."})
        self.assertEqual(r.inputs["message"]["status"], "unavailable")
        self.assertIn("ai_unavailable", r.inputs["message"]["detail"])

    def test_skipped_message_analysis_adds_nothing(self):
        r = correlate_risk(msg(urgency="high", mode="skipped"), None, None)
        self.assertEqual(r.risk_score, 0)
        self.assertEqual(r.inputs["message"]["status"], "not_evaluated")

    def test_no_behaviour_profile(self):
        r = correlate_risk(msg(urgency="high"), beh(found=False), None)
        self.assertEqual(r.inputs["behaviour"]["status"], "not_evaluated")
        self.assertEqual(r.risk_score, 8)
        # flags without a found profile are ignored
        flagged = beh(amount=True, beneficiary=True, found=False)
        self.assertEqual(correlate_risk(None, flagged, None).risk_score, 0)

    def test_no_behaviour_analysis_at_all(self):
        self.assertEqual(correlate_risk(msg(urgency="high"), None, None).inputs["behaviour"]["status"], "not_provided")

    def test_no_attachment(self):
        r = correlate_risk(msg(), beh(), None)
        self.assertEqual(r.inputs["attachment"]["status"], "not_provided")
        self.assertEqual(r.risk_score, 0)

    def test_duplicate_executables_do_not_inflate_the_score(self):
        many = [f("executable_inside_archive", entry=f"f{i}.exe") for i in range(12)]
        r = correlate_risk(None, None, att(many, contains_executable=True, executable_files=[f"f{i}.exe" for i in range(12)]))
        self.assertEqual(r.risk_score, 25)
        self.assertEqual(len(r.signals), 1)
        self.assertEqual(len(r.signals[0].details), 10)  # detail list is bounded

    def test_exe_and_dll_with_real_analyzer_is_one_signal(self):
        a = analyze_attachment("RBI_Statement.zip", zip_bytes(["Statement.pdf", "Update.exe", "helper.dll"]), "application/zip")
        r = correlate_risk(None, None, a)
        self.assertEqual(codes(r), {"EXECUTABLE_ATTACHMENT", "DOCUMENT_WITH_EXECUTABLE"})
        self.assertEqual(r.risk_score, 37)  # 2.0: executable 25 + document-looking archive 12 (was 25 + 20)
        exe = next(s for s in r.signals if s.code == "EXECUTABLE_ATTACHMENT")
        self.assertEqual(sorted(exe.details), ["Update.exe", "helper.dll"])

    def test_duplicate_double_extension_and_other_high_findings_count_once(self):
        r = correlate_risk(None, None, att([f("double_extension", entry="a.pdf.exe"), f("double_extension", entry="b.doc.scr"),
                                            f("content_type_mismatch", "high"), f("risky_extension", "high")]))
        # 2.0: double extension 12 (masquerade) + risky extension 20 (executable group) + other high finding 8
        self.assertEqual(codes(r), {"DOUBLE_EXTENSION", "RISKY_EXTENSION", "OTHER_HIGH_SEVERITY_ATTACHMENT_FINDING"})
        self.assertEqual(r.risk_score, 12 + 20 + 8)

    def test_unknown_signals_are_ignored(self):
        a = att([f("brand_new_finding", "low"), f("another_new_finding", "info"), f("odd", "medium")])
        r = correlate_risk(msg(urgency="shouting", intent="telepathy"), {"surprise": 1, "anomalies": ["x", 3]}, a)
        self.assertEqual(r.risk_score, 0)

    def test_unknown_high_severity_finding_counts_once_as_other(self):
        a = att([f("brand_new_finding", "high"), f("another_new_finding", "high")])
        r = correlate_risk(None, None, a)
        self.assertEqual(codes(r), {"OTHER_HIGH_SEVERITY_ATTACHMENT_FINDING"})
        self.assertEqual(r.risk_score, 8)

    def test_garbage_inputs_never_raise(self):
        for bad in ("text", 42, [], [1, 2], object(), {"extraction": "x"}, {"findings": "x", "archive": "yes"}):
            r = correlate_risk(bad, bad, bad, bad)
            self.assertEqual(r.risk_score, 0)

    def test_objects_with_to_dict_are_accepted(self):
        class Boxed:
            def __init__(self, d): self.d = d
            def to_dict(self): return self.d
        r = correlate_risk(Boxed(msg(urgency="high")), Boxed(beh(beneficiary=True)), Boxed(att()))
        self.assertEqual(r.risk_score, 28)

    def test_deterministic(self):
        args = (msg(urgency="high", secrecy=True), beh(amount=True, channel=True), att([f("double_extension")]))
        first = json.dumps(correlate_risk(*args).to_dict(), sort_keys=True)
        for _ in range(3):
            self.assertEqual(json.dumps(correlate_risk(*args).to_dict(), sort_keys=True), first)

    def test_result_shape_and_flags(self):
        d = correlate_risk(msg(urgency="high"), beh(amount=True), att()).to_dict()
        for key in ("risk_score", "risk_level", "recommended_action", "signals", "is_final_decision", "payment_blocked",
                    "thresholds", "scoring_method", "engine_version", "disclaimer", "inputs", "category_points"):
            self.assertIn(key, d)
        self.assertEqual(set(d["signals"][0]), {
            "code", "category", "source", "severity", "points", "title", "message", "details", "why", "evidence", "confidence",
            "group", "analyzer", "base_points", "capped", "related_signal_codes", "corroborating_sources"})
        self.assertFalse(d["payment_blocked"])
        self.assertEqual(d["scoring_method"], "heuristic_points_v2")
        self.assertEqual(d["engine_version"], rules.ENGINE_VERSION)
        self.assertIn("not proof of fraud", d["disclaimer"])
        per_category = {}
        for sig in d["signals"]:
            per_category[sig["category"]] = per_category.get(sig["category"], 0) + sig["points"]
        self.assertEqual(d["category_points"], per_category)
        self.assertEqual(d["risk_score"], sum(d["category_points"].values()))


# --------------------------------------------------------------------------- #
# End-to-end scenarios through the REAL analyzers
# --------------------------------------------------------------------------- #
class ScenarioTests(unittest.TestCase):
    def test_ceo_demo_scenario_is_critical_hold_payment(self):
        inc = demo_incident()
        r = assess_incident_risk(inc, ("RBI_Statement.zip", zip_bytes(["Statement.pdf", "Update.exe", "helper.dll"]), "application/zip"))
        self.assertEqual((r.risk_level, r.recommended_action), ("CRITICAL", "HOLD_PAYMENT"))
        self.assertEqual(r.risk_score, 100)
        self.assertGreater(r.raw_points, 100)  # the displayed score is capped; raw points are preserved
        self.assertEqual(r.raw_points, sum(sig.points for sig in r.signals))
        self.assertTrue(r.trust_break_detected)
        self.assertEqual(r.headline, "TRUST BREAK DETECTED")
        # No hard-coded score: the result emerges from real signals across every category.
        self.assertTrue(
            {"AMOUNT_ABOVE_BASELINE", "NEW_BENEFICIARY", "UNUSUAL_CHANNEL", "FINANCIAL_TRANSFER_INTENT",
             "EXECUTABLE_ATTACHMENT", "DOCUMENT_WITH_EXECUTABLE"} <= codes(r))
        self.assertTrue({"SECRECY_PRESSURE", "DEADLINE_PRESSURE", "VERIFICATION_SUPPRESSION"} <= codes(r))
        self.assertEqual({s.analyzer for s in r.signals}, {"message", "behaviour", "attachment"})
        self.assertTrue({"synthetic_baseline", "attachment_static"} <= {s.source for s in r.signals})
        self.assertNotIn("AI", {s.source for s in r.signals})  # no key in the test environment: never labelled AI
        self.assertNotIn("hack", r.explanation.lower())
        self.assertNotIn("compromised", r.explanation.lower())
        self.assertFalse(r.payment_blocked)

    def test_ceo_demo_without_the_file_is_still_critical(self):
        r = assess_incident_risk(demo_incident())
        self.assertEqual((r.risk_score, r.risk_level, r.recommended_action), (93, "CRITICAL", "HOLD_PAYMENT"))
        self.assertEqual(r.inputs["attachment"]["status"], "not_provided")

    def test_normal_payment_is_low_and_proceed(self):
        inc = demo_incident(
            message="Please pay the monthly invoice as usual.", channel="Email",
            payment=SimpleNamespace(amount=100_000, beneficiary_name="Vendor A"),
        )
        r = assess_incident_risk(inc)
        # Only the ordinary "a payment is requested" point (+8); no behavioural anomaly, no urgency, no secrecy.
        self.assertEqual((r.risk_score, r.risk_level, r.recommended_action), (8, "LOW", "PROCEED"))
        self.assertEqual(codes(r), {"FINANCIAL_TRANSFER_INTENT"})
        self.assertFalse(r.trust_break_detected)

    def test_unknown_sender_only_gets_message_evidence(self):
        inc = demo_incident(sender=SimpleNamespace(name="Someone Else", role="Manager"))
        r = assess_incident_risk(inc)
        self.assertEqual(r.inputs["behaviour"]["status"], "not_evaluated")
        self.assertEqual({s.analyzer for s in r.signals}, {"message"})
        self.assertNotIn("synthetic_baseline", {s.source for s in r.signals})
        self.assertFalse(r.trust_break_detected)

    def test_message_analysis_failure_is_reported_not_hidden(self):
        with mock.patch("app.services.risk_correlation.service.analyze_message",
                        side_effect=ExtractionError("ai_unavailable", "down")):
            r = assess_incident_risk(demo_incident())
        self.assertEqual(r.inputs["message"]["status"], "unavailable")
        self.assertIn("ai_unavailable", r.inputs["message"]["detail"])
        self.assertEqual(codes(r), {"AMOUNT_ABOVE_BASELINE", "NEW_BENEFICIARY", "UNUSUAL_CHANNEL"})

    def test_bad_attachment_raises_attachment_error(self):
        with self.assertRaises(AttachmentError):
            assess_incident_risk(demo_incident(), ("a.zip", b"", "application/zip"))

    def test_existing_analyzers_still_work_independently(self):
        self.assertTrue(analyze_message(DEMO_INCIDENT.message).extraction.secrecy_indicator)
        b = analyze_incident_behaviour("Arvind Rao", "WhatsApp", 1_850_000, "New Vendor X")
        self.assertTrue(b["amount_anomaly"] and b["new_beneficiary"] and b["channel_anomaly"])
        a = analyze_attachment("RBI_Statement.zip", zip_bytes(["Statement.pdf", "Update.exe"]), "application/zip")
        self.assertTrue(a["contains_executable"])
        for out in (b, a):
            self.assertFalse(out["is_final_decision"])
            self.assertNotIn("risk_score", out)


# --------------------------------------------------------------------------- #
# Architecture and safety guards
# --------------------------------------------------------------------------- #
class ArchitectureTests(unittest.TestCase):
    PKGS = ("message_analysis", "behaviour", "attachment_analysis")

    def test_analyzers_do_not_import_each_other_or_the_risk_engine(self):
        for pkg in self.PKGS:
            for path in (APP / "services" / pkg).glob("*.py"):
                for module in imported_modules(path):
                    for other in set(self.PKGS) - {pkg}:
                        self.assertNotIn(other, module, f"{pkg}/{path.name} imports {module}")
                    self.assertNotIn("risk_correlation", module, f"{pkg}/{path.name} imports {module}")
                    self.assertNotIn("services.analysis", module, f"{pkg}/{path.name} imports {module}")

    def test_pure_engine_does_not_import_analyzers_or_web_framework(self):
        for name in ("engine.py", "rules.py"):
            for module in imported_modules(APP / "services" / "risk_correlation" / name):
                for forbidden in (*self.PKGS, "schemas", "fastapi", "pydantic", "repository"):
                    self.assertNotIn(forbidden, module, f"{name} imports {module}")

    def test_only_the_service_module_imports_the_analyzers(self):
        for path in (APP / "services" / "risk_correlation").glob("*.py"):
            uses = any(p in m for m in imported_modules(path) for p in self.PKGS)
            self.assertEqual(uses, path.name == "service.py", path.name)

    def test_no_llm_network_payment_or_execution_code(self):
        banned_imports = {"urllib", "urllib.request", "http", "http.client", "requests", "httpx", "socket", "anthropic",
                          "subprocess", "os", "random", "tempfile", "shutil", "ctypes", "importlib", "sqlite3"}
        banned_calls = {"eval", "exec", "system", "popen", "open", "urlopen"}
        for path in (APP / "services" / "risk_correlation").glob("*.py"):
            for module in imported_modules(path):
                self.assertNotIn(module, banned_imports, f"{path.name} imports {module}")
                self.assertNotIn("ai_provider", module, f"{path.name} imports {module}")
            self.assertFalse(called_names(path) & banned_calls, f"{path.name}: {called_names(path) & banned_calls}")


if __name__ == "__main__":
    unittest.main()
