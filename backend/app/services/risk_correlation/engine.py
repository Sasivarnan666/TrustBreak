"""Risk Engine 2.0: deterministic risk correlation (pure, no I/O, no LLM, stdlib only).

Pipeline:

    analyzer outputs --adapters--> normalized RiskSignal list
        --consolidate--> one contribution per consolidation group (no double counting)
        --category caps--> bounded category totals
        --sum / cap at 100--> score --thresholds--> level --> recommended action

`correlate_risk()` takes the three analyzer outputs. `correlate_signals()` takes already-normalized signals, so a
future phase can re-run the SAME engine on "this incident with signal X removed" without any other change.

Every point comes from this deterministic code. AI output is only ever evidence (a signal with source "AI" whose
quote was verified against the message); no model decides a weight, score, level or action. The engine only
recommends; it never blocks or executes a payment, and it does not import the analyzers.
"""

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Optional

from . import adapters, rules
from .signals import RiskSignal

# Social-engineering indicators carry a verbatim quote; prefer that as the primary evidence when points tie.
_QUOTED_CODES = frozenset(rules.SOCIAL_SIGNAL_CODES.values())
_CATEGORY_ORDER = {c: i for i, c in enumerate(rules.CATEGORIES)}


# --------------------------------------------------------------------------- #
# Result type
# --------------------------------------------------------------------------- #
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
    scoring_method: str = rules.SCORING_METHOD
    engine_version: str = rules.ENGINE_VERSION
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
            "scoring_method": self.scoring_method, "engine_version": self.engine_version, "disclaimer": self.disclaimer,
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
# Deterministic consolidation (the anti-double-counting rules)
# --------------------------------------------------------------------------- #
def _pick_key(sig: RiskSignal):
    """Which signal of a group is scored: most points, then quoted evidence, then source preference, then code."""
    pref = rules.SOURCE_PREFERENCE.index(sig.source) if sig.source in rules.SOURCE_PREFERENCE else len(rules.SOURCE_PREFERENCE)
    return (-sig.points, 0 if sig.code in _QUOTED_CODES else 1, pref, sig.code)


def consolidate(signals: Iterable[RiskSignal]) -> list:
    """Keep ONE signal per consolidation group; record the others on it (`related_signal_codes`).

    Rule 1: a code appears once (the strongest instance wins).
    Rule 2: signals sharing a group (rules.CONSOLIDATION_GROUPS) describe the same underlying evidence, so only the
            strongest is scored; the rest are listed as related and their sources as corroborating.
    """
    by_code: dict = {}
    for sig in signals:
        if sig.code in rules.RULES_BY_CODE:  # unknown codes are ignored, never scored
            best = by_code.get(sig.code)
            if best is None or _pick_key(sig) < _pick_key(best):
                by_code[sig.code] = sig
    groups: dict = {}
    for sig in by_code.values():
        groups.setdefault(rules.GROUP_FOR_CODE[sig.code], []).append(sig)
    out = []
    for members in groups.values():
        members.sort(key=_pick_key)
        primary, rest = members[0], members[1:]
        primary.related_signal_codes = [m.code for m in rest]
        primary.corroborating_sources = list(dict.fromkeys(m.source for m in rest if m.source != primary.source))
        out.append(primary)
    return out


def _apply_category_caps(signals: list, notes: list) -> list:
    """Reduce a category's total to rules.CATEGORY_CAPS. Strongest signals keep their points first."""
    kept = list(signals)
    for category, cap in rules.CATEGORY_CAPS.items():
        members = sorted((s for s in kept if s.category == category), key=lambda s: (-s.points, s.code))
        if sum(s.points for s in members) <= cap:
            continue
        remaining, dropped = cap, []
        for s in members:
            give = min(s.points, remaining)
            if give < s.points:
                s.capped, s.points, s.severity = True, give, rules.severity_for_points(give)
            remaining -= give
            if give == 0:
                dropped.append(s)
        for s in dropped:
            kept.remove(s)
            members[0].related_signal_codes.append(s.code)
        notes.append(f"{rules.CATEGORY_LABELS[category]} points are limited to {cap} (prototype category cap); "
                     "the underlying indicators are still listed.")
    return kept


# --------------------------------------------------------------------------- #
# Core: normalized signals -> assessment
# --------------------------------------------------------------------------- #
def correlate_signals(candidates: Iterable[RiskSignal], inputs: Optional[dict] = None, notes: Optional[list] = None) -> RiskCorrelationResult:
    """Score already-normalized signals. This is the single scoring path (counterfactual-ready: pass fewer signals)."""
    inputs = inputs or {}
    notes = list(notes or [])
    # Work on copies so the caller's signals are never mutated (a later run can reuse them).
    fresh = [RiskSignal(**{**s.__dict__, "details": list(s.details), "related_signal_codes": [], "corroborating_sources": []}) for s in candidates]
    merged = consolidate(fresh)
    n_merged = sum(len(s.related_signal_codes) for s in merged)
    if n_merged:
        notes.append(f"{n_merged} overlapping indicator(s) describe evidence already counted and were consolidated, not added.")
    signals = _apply_category_caps(merged, notes)
    signals.sort(key=lambda s: (-s.points, _CATEGORY_ORDER[s.category], s.code))

    raw = sum(s.points for s in signals)
    score = min(rules.MAX_SCORE, raw)
    level = level_for_score(score)
    action = action_for_level(level)

    analyzers = {s.analyzer for s in signals if s.analyzer}
    context_hits = [s for s in signals if s.code in rules.CONTEXT_INCONSISTENCY_CODES]
    trust_break = level in (rules.HIGH, rules.CRITICAL) and len(analyzers) >= 2 and bool(context_hits)

    missing = [name for name, i in inputs.items() if i.get("status") != "used"]
    if missing:
        notes.append("Not all evidence was available (" + ", ".join(missing) + "); the assessment reflects only the inputs that were used.")
    if raw > rules.MAX_SCORE:
        notes.append(f"Raw points ({raw}) exceed the {rules.MAX_SCORE}-point display cap; the displayed score is capped. "
                     "A capped score is not a probability.")

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
        explanation = ("A limited number of risk indicators were found. Verification is advisable." if level == rules.MEDIUM
                       else "Only minor risk indicators were found.")
    else:
        headline = "No risk indicators"
        explanation = "No risk indicators were found in the evidence that was available."

    category_points: dict = {}
    for s in signals:
        category_points[s.category] = category_points.get(s.category, 0) + s.points
    return RiskCorrelationResult(
        risk_score=score, raw_points=raw, max_score=rules.MAX_SCORE, risk_level=level,
        recommended_action=action, recommended_action_label=rules.ACTION_LABELS[action],
        recommended_action_guidance=rules.ACTION_GUIDANCE[action], trust_break_detected=trust_break,
        headline=headline, explanation=explanation, signals=signals, category_points=category_points,
        inputs=inputs, notes=notes,
    )


# --------------------------------------------------------------------------- #
# Public entry point (analyzer outputs)
# --------------------------------------------------------------------------- #
def collect_signals(message_analysis: Any, behaviour_analysis: Any, attachment_analysis: Any, incident: Any = None,
                    *, unavailable: Optional[Mapping[str, str]] = None) -> tuple:
    """Normalize the analyzer outputs. Returns (signals, inputs). Missing evidence adds nothing and never raises."""
    unavailable = unavailable or {}
    message, behaviour, attachment = adapters.as_dict(message_analysis), adapters.as_dict(behaviour_analysis), adapters.as_dict(attachment_analysis)
    facts = adapters.incident_facts(incident)
    msg_sigs, msg_in = adapters.message_signals(message, behaviour, facts, unavailable.get("message"))
    beh_sigs, beh_in = adapters.behaviour_signals(behaviour)
    att_sigs, att_in = adapters.attachment_signals(attachment)
    return msg_sigs + beh_sigs + att_sigs, {"message": msg_in, "behaviour": beh_in, "attachment": att_in}


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
    signals, inputs = collect_signals(message_analysis, behaviour_analysis, attachment_analysis, incident, unavailable=unavailable)
    return correlate_signals(signals, inputs)
