"""Deterministic risk correlation (pure function, no I/O, no LLM, stdlib only).

correlate_risk() consumes the STRUCTURED outputs of message analysis, behaviour
analysis and attachment analysis (as dicts or objects with `to_dict()`), turns
them into at most one signal per category, adds the points and maps the total
to a level and a recommended action.

It never blocks or executes a payment: it only recommends. It does not import
the analyzers, so each analyzer stays independently usable.
"""

import re
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional

from . import rules
from .rules import RULES_BY_CATEGORY, RULES_BY_CODE, SignalRule

MAX_DETAIL_ITEMS = 10


# --------------------------------------------------------------------------- #
# Result types
# --------------------------------------------------------------------------- #
@dataclass
class RiskSignal:
    code: str
    category: str
    source: str
    severity: str
    points: int
    title: str
    message: str
    details: list = field(default_factory=list)  # e.g. executable file names

    def to_dict(self) -> dict:
        return {
            "code": self.code, "category": self.category, "source": self.source,
            "severity": self.severity, "points": self.points, "title": self.title,
            "message": self.message, "details": list(self.details),
        }


@dataclass
class RiskCorrelationResult:
    risk_score: int
    raw_points: int
    max_score: int
    risk_level: str
    recommended_action: str
    recommended_action_label: str
    recommended_action_guidance: str
    trust_break_detected: bool
    headline: str
    explanation: str
    signals: list
    category_points: dict
    inputs: dict
    notes: list
    scoring_method: str = "heuristic_points"
    disclaimer: str = rules.DISCLAIMER
    payment_blocked: bool = False  # the engine only recommends; it never blocks or executes a payment
    is_final_decision: bool = True  # final output of the analysis pipeline, NOT proof of fraud

    def to_dict(self) -> dict:
        return {
            "risk_score": self.risk_score, "raw_points": self.raw_points, "max_score": self.max_score,
            "risk_level": self.risk_level, "recommended_action": self.recommended_action,
            "recommended_action_label": self.recommended_action_label,
            "recommended_action_guidance": self.recommended_action_guidance,
            "trust_break_detected": self.trust_break_detected, "headline": self.headline,
            "explanation": self.explanation, "signals": [s.to_dict() for s in self.signals],
            "category_points": dict(self.category_points), "inputs": self.inputs, "notes": list(self.notes),
            "scoring_method": self.scoring_method, "disclaimer": self.disclaimer,
            "thresholds": [{"min_score": lo, "level": lvl} for lo, lvl in sorted(rules.LEVEL_THRESHOLDS)],
            "payment_blocked": self.payment_blocked, "is_final_decision": self.is_final_decision,
        }


# --------------------------------------------------------------------------- #
# Score -> level -> action
# --------------------------------------------------------------------------- #
def level_for_score(score: Any) -> str:
    """Map a score to a level using the prototype thresholds (invalid -> LOW)."""
    if isinstance(score, bool) or not isinstance(score, (int, float)) or score != score:
        return rules.LOW
    for lowest, level in rules.LEVEL_THRESHOLDS:
        if score >= lowest:
            return level
    return rules.LOW


def action_for_level(level: str) -> str:
    return rules.ACTION_FOR_LEVEL.get(level, rules.VERIFY)  # unknown level -> the cautious non-blocking action


# --------------------------------------------------------------------------- #
# Defensive input helpers (inputs are untrusted-shaped: anything may be missing)
# --------------------------------------------------------------------------- #
def _as_dict(value: Any) -> Optional[dict]:
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
    """Read obj.path... from dicts or attribute objects; None when absent."""
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


def _signal(rule: SignalRule, message: Optional[str] = None, details: Optional[list] = None) -> RiskSignal:
    return RiskSignal(
        code=rule.code, category=rule.category, source=rule.source,
        severity=rules.severity_for_points(rule.points), points=rule.points, title=rule.title,
        message=message or rule.default_message, details=(details or [])[:MAX_DETAIL_ITEMS],
    )


def _incident_facts(incident: Any) -> dict:
    """Pull the few incident facts the engine needs (all optional)."""
    inc = _as_dict(incident) or {}
    sender = inc.get("sender") if isinstance(inc.get("sender"), Mapping) else _as_dict(_get(incident, "sender")) or {}
    return {"sender_name": _text(sender.get("name")), "sender_role": _text(sender.get("role"))}


# --------------------------------------------------------------------------- #
# Per-source signal extraction (each returns signals + an `inputs` status entry)
# --------------------------------------------------------------------------- #
def _message_signals(message: Optional[dict], behaviour: Optional[dict], facts: dict, unavailable: Optional[str]):
    if message is None:
        status = "unavailable" if unavailable else "not_provided"
        return [], {"status": status, "detail": unavailable or "No message analysis was provided."}
    mode = message.get("mode")
    extraction = _as_dict(message.get("extraction")) or {}
    if mode == "skipped" or not extraction:
        return [], {"status": "not_evaluated", "mode": mode, "detail": "The message could not be analyzed (empty or no extraction)."}

    signals: list[RiskSignal] = []
    if extraction.get("urgency_level") in rules.HIGH_URGENCY_LEVELS:
        deadline = _text(extraction.get("deadline"))
        signals.append(_signal(RULES_BY_CODE["HIGH_URGENCY"],
                               "The message requests immediate action" + (f" (deadline: {deadline})." if deadline else "."),
                               [deadline] if deadline else None))
    if extraction.get("secrecy_indicator") is True:
        signals.append(_signal(RULES_BY_CODE["SECRECY_REQUESTED"]))
    if extraction.get("financial_intent") in rules.FINANCIAL_TRANSFER_INTENTS:
        signals.append(_signal(RULES_BY_CODE["FINANCIAL_TRANSFER_INTENT"],
                               f"The message asks for a financial action ({extraction['financial_intent'].replace('_', ' ')})."))

    # Authority mismatch only with reliable evidence: BOTH the claimed authority and a
    # recorded role resolve to ONE known role each, and the two differ.
    claimed = _text(extraction.get("claimed_authority"))
    recorded_role = _text(_get(behaviour, "profile_summary", "role")) if _get(behaviour, "profile_found") is True else None
    recorded_role = recorded_role or facts.get("sender_role")
    claimed_role, actual_role = _canonical_role(claimed), _canonical_role(recorded_role)
    if claimed_role and actual_role and claimed_role != actual_role:
        signals.append(_signal(RULES_BY_CODE["AUTHORITY_MISMATCH"],
                               f"The message claims the authority of '{claimed}', but the sender is recorded as '{recorded_role}'.",
                               [claimed, recorded_role]))
    return signals, {"status": "used", "mode": mode, "detail": f"Message analysis ({mode}) used."}


def _behaviour_signals(behaviour: Optional[dict]):
    if behaviour is None:
        return [], {"status": "not_provided", "detail": "No behaviour analysis was provided."}
    if behaviour.get("profile_found") is not True:
        return [], {"status": "not_evaluated", "detail": "No behaviour profile exists for this sender, so no behavioural evidence is available."}

    anomalies = [a for a in _list(behaviour.get("anomalies")) if isinstance(a, Mapping)]
    by_code = {a.get("code"): a for a in anomalies}
    signals: list[RiskSignal] = []
    for flag, code in (("amount_anomaly", "AMOUNT_ABOVE_BASELINE"), ("new_beneficiary", "NEW_BENEFICIARY"),
                       ("channel_anomaly", "UNUSUAL_CHANNEL")):
        if behaviour.get(flag) is True or code in by_code:
            note = by_code.get(code, {}).get("message")
            signals.append(_signal(RULES_BY_CODE[code], _text(note)))
    return signals, {"status": "used", "detail": "Behaviour analysis used."}


def _attachment_signals(attachment: Optional[dict]):
    if attachment is None:
        return [], {"status": "not_provided", "detail": "No attachment file was analyzed."}

    findings = [f for f in _list(attachment.get("findings")) if isinstance(f, Mapping)]
    types = {f.get("type") for f in findings}
    is_archive = attachment.get("archive") is True
    exec_names = [str(n) for n in _list(attachment.get("executable_files"))]
    exec_names += [str(f["entry"]) for f in findings if f.get("type") in rules.EXECUTABLE_FINDING_TYPES and f.get("entry")]
    exec_names = list(dict.fromkeys(exec_names))  # de-duplicate, keep order

    signals: list[RiskSignal] = []
    if attachment.get("contains_executable") is True or types & rules.EXECUTABLE_FINDING_TYPES:
        signals.append(_signal(RULES_BY_CODE["EXECUTABLE_ATTACHMENT"],
                               "The uploaded archive contains executable content." if is_archive
                               else "The uploaded file is or contains executable content.", exec_names))
    if types & rules.DOCUMENT_DECEPTION_FINDING_TYPES:
        signals.append(_signal(RULES_BY_CODE["DOCUMENT_WITH_EXECUTABLE"]))
    if types & rules.DOUBLE_EXTENSION_FINDING_TYPES:
        names = [str(f["entry"]) for f in findings if f.get("type") == "double_extension" and f.get("entry")]
        signals.append(_signal(RULES_BY_CODE["DOUBLE_EXTENSION"], details=list(dict.fromkeys(names))))
    if types & rules.PATH_TRAVERSAL_FINDING_TYPES:
        names = [str(f["entry"]) for f in findings if f.get("type") == "path_traversal" and f.get("entry")]
        signals.append(_signal(RULES_BY_CODE["PATH_TRAVERSAL"], details=list(dict.fromkeys(names))))
    other_high = [f for f in findings if f.get("severity") == "high" and f.get("type") not in rules.DEDICATED_FINDING_TYPES]
    if other_high:
        kinds = list(dict.fromkeys(str(f.get("type")) for f in other_high))
        signals.append(_signal(RULES_BY_CODE["OTHER_HIGH_SEVERITY_ATTACHMENT_FINDING"], details=kinds))
    return signals, {"status": "used", "detail": "Attachment analysis used."}


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #
def correlate_risk(
    message_analysis: Any,
    behaviour_analysis: Any,
    attachment_analysis: Any,
    incident: Any = None,
    *,
    unavailable: Optional[Mapping[str, str]] = None,
) -> RiskCorrelationResult:
    """Correlate the independent evidence sources into an explainable risk assessment.

    Any input may be None; missing evidence never raises and never adds points.
    `unavailable` optionally records WHY an input is None ({"message": "reason"}).
    """
    unavailable = unavailable or {}
    message, behaviour, attachment = _as_dict(message_analysis), _as_dict(behaviour_analysis), _as_dict(attachment_analysis)
    facts = _incident_facts(incident)

    msg_sigs, msg_in = _message_signals(message, behaviour, facts, unavailable.get("message"))
    beh_sigs, beh_in = _behaviour_signals(behaviour)
    att_sigs, att_in = _attachment_signals(attachment)

    # One signal per category (defensive; the extractors already emit at most one).
    chosen: dict[str, RiskSignal] = {}
    for sig in msg_sigs + beh_sigs + att_sigs:
        if sig.category in RULES_BY_CATEGORY:
            chosen.setdefault(sig.category, sig)
    order = {r.category: i for i, r in enumerate(rules.RULES)}
    signals = sorted(chosen.values(), key=lambda s: (-s.points, order[s.category]))

    raw = sum(s.points for s in signals)
    score = min(rules.MAX_SCORE, raw)
    level = level_for_score(score)
    action = action_for_level(level)

    sources = {s.source for s in signals}
    context_hits = [s for s in signals if s.category in rules.CONTEXT_INCONSISTENCY_CATEGORIES]
    trust_break = level in (rules.HIGH, rules.CRITICAL) and len(sources) >= 2 and bool(context_hits)

    inputs = {"message": msg_in, "behaviour": beh_in, "attachment": att_in}
    notes = []
    missing = [name for name, i in inputs.items() if i["status"] != "used"]
    if missing:
        notes.append("Not all evidence was available (" + ", ".join(missing) + "); the assessment reflects only the inputs that were used.")
    if raw > rules.MAX_SCORE:
        notes.append(f"Raw points ({raw}) exceed the {rules.MAX_SCORE}-point display cap; the score is capped.")

    if trust_break:
        headline = "TRUST BREAK DETECTED"
        explanation = ("The request is inconsistent with the sender's established behaviour and contains multiple "
                       "independent indicators of elevated financial-fraud risk.")
    elif level in (rules.HIGH, rules.CRITICAL):
        headline = "Elevated risk indicators"
        explanation = ("Multiple risk indicators were found, but none shows the request departing from the sender's "
                       "established behaviour.")
    elif signals:
        headline = "Some risk indicators"
        explanation = "A limited number of risk indicators were found. Verification is advisable." if level == rules.MEDIUM \
            else "Only minor risk indicators were found."
    else:
        headline = "No risk indicators"
        explanation = "No risk indicators were found in the evidence that was available."

    return RiskCorrelationResult(
        risk_score=score, raw_points=raw, max_score=rules.MAX_SCORE, risk_level=level,
        recommended_action=action, recommended_action_label=rules.ACTION_LABELS[action],
        recommended_action_guidance=rules.ACTION_GUIDANCE[action], trust_break_detected=trust_break,
        headline=headline, explanation=explanation, signals=signals,
        category_points={s.category: s.points for s in signals}, inputs=inputs, notes=notes,
    )
