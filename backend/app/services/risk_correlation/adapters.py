"""Adapters: analyzer outputs -> normalized `RiskSignal` objects (pure, stdlib only, never raises).

One adapter per evidence source. Adapters decide WHAT evidence exists and WHERE it came from; they contain no
scoring numbers (weights live in rules.py) and they do not consolidate (the engine does).

Source labelling is strict: AI only when a model reported grounded evidence, `fallback` when the deterministic
extractor ran because the AI provider failed, `rule` for deterministic pattern detection, `synthetic_baseline`
for comparisons with the synthetic behavioural baseline, `attachment_static` for static archive inspection.
"""

import re
from typing import Any, Mapping, Optional

from . import rules
from .rules import RULES_BY_CODE
from .signals import RiskSignal

MAX_DETAIL_ITEMS = 10


# --------------------------------------------------------------------------- #
# Defensive input helpers (inputs are untrusted-shaped: anything may be missing)
# --------------------------------------------------------------------------- #
def as_dict(value: Any) -> Optional[dict]:
    if value is None:
        return None
    if isinstance(value, Mapping):
        return dict(value)
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        try:
            out = to_dict()
        except Exception:  # a broken object must not break the assessment
            return None
        return dict(out) if isinstance(out, Mapping) else None
    return None


def _get(obj: Any, *path: str) -> Any:
    for key in path:
        if obj is None:
            return None
        obj = obj.get(key) if isinstance(obj, Mapping) else getattr(obj, key, None)
    return obj


def _text(value: Any) -> Optional[str]:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _list(value: Any) -> list:
    return list(value) if isinstance(value, (list, tuple)) else []


def _canonical_role(text: Optional[str]) -> Optional[str]:
    """Resolve a title to ONE canonical role; None when absent or ambiguous."""
    if not text:
        return None
    lowered = " ".join(text.casefold().split())
    found = {
        role for role, aliases in rules.ROLE_ALIASES.items()
        if any(re.search(rf"(?<![a-z0-9]){re.escape(a)}(?![a-z0-9])", lowered) for a in aliases)
    }
    return next(iter(found)) if len(found) == 1 else None


def make_signal(code: str, *, source: str, analyzer: str, message: Optional[str] = None, evidence: Optional[str] = None,
                confidence: Optional[str] = None, details: Optional[list] = None) -> RiskSignal:
    """Build one normalized signal from its rule. Points = weight x confidence factor (rules.py)."""
    rule = RULES_BY_CODE[code]
    points = rules.scaled_points(rule.weight, confidence)
    return RiskSignal(
        code=code, category=rule.category, source=source, severity=rules.severity_for_points(points), points=points,
        title=rule.title, message=message or rule.default_message, details=[str(d) for d in (details or [])][:MAX_DETAIL_ITEMS],
        why=rule.rationale, evidence=evidence, confidence=confidence if confidence in rules.CONFIDENCE_FACTOR else None,
        group=rule.group, analyzer=analyzer, base_points=points,
    )


def incident_facts(incident: Any) -> dict:
    inc = as_dict(incident) or {}
    sender = inc.get("sender") if isinstance(inc.get("sender"), Mapping) else as_dict(_get(incident, "sender")) or {}
    return {"sender_name": _text(sender.get("name")), "sender_role": _text(sender.get("role"))}


# --------------------------------------------------------------------------- #
# Message extraction + social-engineering indicators
# --------------------------------------------------------------------------- #
def _extraction_source(message: dict) -> str:
    """Origin of the extracted flags: AI only when a validated model reply was used."""
    state = message.get("analysis_state") or ("ai" if message.get("mode") == "ai" else "mock")
    return {"ai": rules.SRC_AI, "fallback": rules.SRC_FALLBACK}.get(state, rules.SRC_RULE)


def message_signals(message: Optional[dict], behaviour: Optional[dict], facts: dict, unavailable: Optional[str]):
    """Returns (signals, input_status)."""
    if message is None:
        status = "unavailable" if unavailable else "not_provided"
        return [], {"status": status, "detail": unavailable or "No message analysis was provided."}
    mode = message.get("mode")
    extraction = as_dict(message.get("extraction")) or {}
    if mode == "skipped" or not extraction:
        return [], {"status": "not_evaluated", "mode": mode, "detail": "The message could not be analyzed (empty or no extraction)."}

    A = rules.AN_MESSAGE
    src = _extraction_source(message)
    signals: list[RiskSignal] = []

    if extraction.get("urgency_level") in rules.HIGH_URGENCY_LEVELS:
        deadline = _text(extraction.get("deadline"))
        signals.append(make_signal(
            "HIGH_URGENCY", source=src, analyzer=A,
            message="The message requests immediate action" + (f" (deadline: {deadline})." if deadline else "."),
            evidence="Message analysis rated the urgency as high" + (f" with deadline \"{deadline}\"." if deadline else "."),
            details=[deadline] if deadline else None))
    if extraction.get("secrecy_indicator") is True:
        signals.append(make_signal("SECRECY_REQUESTED", source=src, analyzer=A,
                                   evidence="Message analysis flagged a request to keep the matter confidential."))
    intent = extraction.get("financial_intent")
    if intent in rules.FINANCIAL_TRANSFER_INTENTS:
        action = _text(extraction.get("requested_action"))
        signals.append(make_signal(
            "FINANCIAL_TRANSFER_INTENT", source=src, analyzer=A,
            message=f"The message asks for a financial action ({intent.replace('_', ' ')}).",
            evidence=f"Requested action: \"{action}\"" if action else f"Message analysis classified the intent as {intent.replace('_', ' ')}."))

    # Authority mismatch only with reliable evidence: BOTH the claimed authority and a recorded role resolve to
    # ONE known role each, and the two differ. The comparison itself is a deterministic rule.
    claimed = _text(extraction.get("claimed_authority"))
    recorded_role = _text(_get(behaviour, "profile_summary", "role")) if _get(behaviour, "profile_found") is True else None
    recorded_role = recorded_role or facts.get("sender_role")
    claimed_role, actual_role = _canonical_role(claimed), _canonical_role(recorded_role)
    if claimed_role and actual_role and claimed_role != actual_role:
        signals.append(make_signal(
            "AUTHORITY_MISMATCH", source=rules.SRC_RULE, analyzer=A,
            message=f"The message claims the authority of '{claimed}', but the sender is recorded as '{recorded_role}'.",
            evidence=f"Claimed authority \"{claimed}\" vs recorded role \"{recorded_role}\".", details=[claimed, recorded_role]))

    # Structured social-engineering indicators (each carries its own source: AI / rule / fallback).
    block = as_dict(message.get("social_engineering")) or {}
    for item in _list(block.get("signals")):
        if not isinstance(item, Mapping) or item.get("detected") is not True:
            continue
        code = rules.SOCIAL_SIGNAL_CODES.get(item.get("signal"))
        if code is None:
            continue
        item_src = item.get("source")
        item_src = item_src if item_src in (rules.SRC_AI, rules.SRC_RULE, rules.SRC_FALLBACK) else rules.SRC_RULE
        signals.append(make_signal(code, source=item_src, analyzer=A, evidence=_text(item.get("evidence")),
                                   confidence=item.get("confidence"),
                                   details=[item["matched_phrase"]] if _text(item.get("matched_phrase")) else None))

    state = message.get("analysis_state") or ("ai" if mode == "ai" else "mock")
    detail = {
        "ai": "Message extraction by an AI model (validated) used.",
        "fallback": "Deterministic fallback extraction used because the AI provider was unavailable; this is not AI output.",
        "mock": "Deterministic demo extraction used (rule-based, not AI).",
    }.get(state, f"Message analysis ({mode}) used.")
    return signals, {
        "status": "used", "mode": mode, "detail": detail, "analysis_state": state,
        "provider": message.get("provider"), "failure_kind": message.get("failure_kind"),
    }


# --------------------------------------------------------------------------- #
# Behaviour (synthetic baseline)
# --------------------------------------------------------------------------- #
def behaviour_signals(behaviour: Optional[dict]):
    if behaviour is None:
        return [], {"status": "not_provided", "detail": "No behaviour analysis was provided."}
    if behaviour.get("profile_found") is not True:
        return [], {"status": "not_evaluated", "detail": "No behaviour profile exists for this sender, so no behavioural evidence is available."}

    by_code = {a.get("code"): a for a in _list(behaviour.get("anomalies")) if isinstance(a, Mapping)}
    wanted = list(rules.BEHAVIOUR_ANOMALY_CODES)
    flagged = {code for flag, code in rules.BEHAVIOUR_FLAG_CODES if behaviour.get(flag) is True}
    signals: list[RiskSignal] = []
    for code in wanted:
        if code in by_code or code in flagged:
            note = _text(by_code.get(code, {}).get("message"))
            signals.append(make_signal(code, source=rules.SRC_BASELINE, analyzer=rules.AN_BEHAVIOUR, message=None, evidence=note))
            if note:  # keep the analyzer's own sentence as the explanation of this specific case
                signals[-1].message = note
    detail = "Behaviour analysis used."
    if behaviour.get("baseline_status") == "NOT_ENOUGH_BASELINE_DATA":
        detail += " History-based checks reported NOT_ENOUGH_BASELINE_DATA; no history-based anomaly was inferred."
    return signals, {"status": "used", "detail": detail}


# --------------------------------------------------------------------------- #
# Attachment (static analysis)
# --------------------------------------------------------------------------- #
def _finding_evidence(findings: list, types: frozenset) -> Optional[str]:
    parts = []
    for f in findings:
        if f.get("type") in types:
            msg, entry = _text(f.get("message")), _text(f.get("entry"))
            parts.append(f"{msg} [{entry}]" if msg and entry else (msg or entry or ""))
    parts = [p for p in dict.fromkeys(parts) if p]
    return "; ".join(parts[:3]) if parts else None


def _entries(findings: list, types: frozenset) -> list:
    return list(dict.fromkeys(str(f["entry"]) for f in findings if f.get("type") in types and f.get("entry")))


def attachment_signals(attachment: Optional[dict]):
    if attachment is None:
        return [], {"status": "not_provided", "detail": "No attachment file was analyzed."}

    A, S = rules.AN_ATTACHMENT, rules.SRC_ATTACHMENT
    findings = [f for f in _list(attachment.get("findings")) if isinstance(f, Mapping)]
    types = {f.get("type") for f in findings}
    is_archive = attachment.get("archive") is True
    exec_names = [str(n) for n in _list(attachment.get("executable_files"))] + _entries(findings, rules.EXECUTABLE_FINDING_TYPES)
    exec_names = list(dict.fromkeys(exec_names))  # de-duplicate, keep order

    signals: list[RiskSignal] = []
    if attachment.get("contains_executable") is True or types & rules.EXECUTABLE_FINDING_TYPES:
        signals.append(make_signal(
            "EXECUTABLE_ATTACHMENT", source=S, analyzer=A,
            message="The uploaded archive contains executable content." if is_archive else "The uploaded file is or contains executable content.",
            evidence=_finding_evidence(findings, rules.EXECUTABLE_FINDING_TYPES) or "Attachment analysis reports executable content.",
            details=exec_names))
    if types & rules.RISKY_EXTENSION_FINDING_TYPES:
        signals.append(make_signal("RISKY_EXTENSION", source=S, analyzer=A, evidence=_finding_evidence(findings, rules.RISKY_EXTENSION_FINDING_TYPES)))
    if types & rules.DOCUMENT_DECEPTION_FINDING_TYPES:
        signals.append(make_signal("DOCUMENT_WITH_EXECUTABLE", source=S, analyzer=A, evidence=_finding_evidence(findings, rules.DOCUMENT_DECEPTION_FINDING_TYPES)))
    if types & rules.DOUBLE_EXTENSION_FINDING_TYPES:
        signals.append(make_signal("DOUBLE_EXTENSION", source=S, analyzer=A, evidence=_finding_evidence(findings, rules.DOUBLE_EXTENSION_FINDING_TYPES),
                                   details=_entries(findings, rules.DOUBLE_EXTENSION_FINDING_TYPES)))
    if types & rules.PATH_TRAVERSAL_FINDING_TYPES:
        signals.append(make_signal("PATH_TRAVERSAL", source=S, analyzer=A, evidence=_finding_evidence(findings, rules.PATH_TRAVERSAL_FINDING_TYPES),
                                   details=_entries(findings, rules.PATH_TRAVERSAL_FINDING_TYPES)))
    other_high = [f for f in findings if f.get("severity") == "high" and f.get("type") not in rules.DEDICATED_FINDING_TYPES]
    if other_high:
        kinds = list(dict.fromkeys(str(f.get("type")) for f in other_high))
        signals.append(make_signal("OTHER_HIGH_SEVERITY_ATTACHMENT_FINDING", source=S, analyzer=A,
                                   evidence=_finding_evidence(other_high, frozenset(kinds)), details=kinds))
    if types & rules.STRUCTURAL_FINDING_TYPES:
        kinds = [t for t in dict.fromkeys(f.get("type") for f in findings) if t in rules.STRUCTURAL_FINDING_TYPES]
        signals.append(make_signal("SUSPICIOUS_STRUCTURE", source=S, analyzer=A,
                                   evidence=_finding_evidence(findings, rules.STRUCTURAL_FINDING_TYPES), details=kinds))
    return signals, {"status": "used", "detail": "Static attachment analysis used (nothing was executed or extracted)."}
