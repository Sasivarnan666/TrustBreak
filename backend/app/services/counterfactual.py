"""Counterfactual risk analysis ("What would reduce the risk?").

Read-only and deterministic. It takes the incident's latest STORED assessment, rebuilds the normalized signals it
was scored from, removes one signal group at a time and re-runs the SAME engine (`correlate_signals`). There is no
second scoring system: every number below is the engine's output for a modified signal list. Nothing is persisted,
mutated or appended to the assessment history.

Limits (also stated to the analyst): stored signals are already consolidated and category-capped, so removing a
group removes that group's whole contribution; a capped category keeps its already-capped points.
"""

from itertools import combinations
from typing import Any, Optional

from .risk_correlation import rules
from .risk_correlation.engine import correlate_signals
from .risk_correlation.signals import RiskSignal

DISCLAIMER = (
    "Counterfactuals are deterministic simulations using the same Risk Engine. "
    "They do not modify the incident or assessment history."
)

_LEVEL_RANK = {rules.LOW: 0, rules.MEDIUM: 1, rules.HIGH: 2, rules.CRITICAL: 3}
_SIGNAL_FIELDS = frozenset(RiskSignal.__dataclass_fields__)


class CounterfactualDef:
    def __init__(self, cid: str, label: str, description: str, codes=(), categories=()):
        self.id, self.label, self.description = cid, label, description
        self.codes, self.categories = frozenset(codes), frozenset(categories)

    def matches(self, sig: RiskSignal) -> bool:
        return sig.code in self.codes or sig.category in self.categories


# The what-if catalogue. Each entry names WHICH evidence is assumed away; the score change is computed.
DEFINITIONS = (
    CounterfactualDef("known_beneficiary", "Known beneficiary", "The beneficiary was already known to the sender.",
                      codes=("NEW_BENEFICIARY",)),
    CounterfactualDef("trusted_channel", "Trusted channel", "The request arrived on a channel the sender normally uses.",
                      codes=("UNUSUAL_CHANNEL", "CHANNEL_DISTRIBUTION_ANOMALY")),
    CounterfactualDef("normal_amount", "Normal transaction amount", "The amount was within the sender's normal range.",
                      codes=("AMOUNT_ABOVE_BASELINE",)),
    CounterfactualDef("no_social_engineering", "Remove social-engineering pressure",
                      "The message contained no urgency, secrecy, verification-suppression or similar pressure.",
                      categories=(rules.SOCIAL_ENGINEERING,)),
    CounterfactualDef("no_suspicious_attachment", "Remove suspicious attachment",
                      "No attachment findings were present.", categories=(rules.ATTACHMENT,)),
    CounterfactualDef("no_executable_evidence", "Remove executable attachment evidence",
                      "The attachment showed no executable content or document disguise (other structural findings stay).",
                      codes=("EXECUTABLE_ATTACHMENT", "RISKY_EXTENSION", "DOCUMENT_WITH_EXECUTABLE", "DOUBLE_EXTENSION")),
    CounterfactualDef("normal_working_hours", "Normal working-hour context",
                      "The request fell within the sender's usual working time and days.",
                      codes=("UNUSUAL_TIME", "UNUSUAL_DAY")),
)


def _signals_from_stored(assessment: dict) -> list:
    out = []
    for raw in assessment.get("signals") or []:
        data = {k: v for k, v in raw.items() if k in _SIGNAL_FIELDS}
        data["details"] = list(data.get("details") or [])
        data["related_signal_codes"], data["corroborating_sources"] = [], []
        out.append(RiskSignal(**data))
    return out


def _run(signals: list, inputs: dict):
    return correlate_signals(signals, inputs)


def _snapshot(res) -> dict:
    return {"score": res.risk_score, "raw": res.raw_points, "level": res.risk_level,
            "action": res.recommended_action, "trust_break": res.trust_break_detected}


def _explain(label: str, affected: list, base: dict, new: dict, max_score: int) -> str:
    names = ", ".join(a["title"] for a in affected)
    removed = sum(a["points"] for a in affected)
    if new["score"] < base["score"]:
        text = f"Without {names} ({removed} pts) the score is {new['score']} instead of {base['score']}."
    elif new["raw"] < base["raw"]:
        text = (f"Without {names} ({removed} pts) raw points fall from {base['raw']} to {new['raw']}, but the score stays "
                f"{new['score']} because raw points still reach the {max_score}-point display cap. This factor alone does not change the outcome.")
    else:
        text = f"Removing {names} does not change the score."
    if new["level"] != base["level"]:
        text += f" The risk level would change from {base['level']} to {new['level']}."
    return text


def analyze(assessment: Optional[dict]) -> dict:
    """Counterfactuals for a stored assessment dict (latest). Never raises for an unusable assessment."""
    base_out: dict = {"available": False, "reason": None, "disclaimer": DISCLAIMER, "is_simulation": True,
                      "current": None, "counterfactuals": [], "largest_reduction": None, "smallest_downgrade": None,
                      "notes": []}
    if not assessment:
        base_out["reason"] = "No stored risk assessment exists for this incident yet. Run the risk assessment first."
        return base_out
    signals = _signals_from_stored(assessment)
    inputs = assessment.get("inputs") or {}
    baseline = _run(signals, inputs)
    stored = {"score": assessment.get("risk_score"), "raw": assessment.get("raw_points"), "level": assessment.get("risk_level")}
    if (baseline.risk_score, baseline.raw_points, baseline.risk_level) != (stored["score"], stored["raw"], stored["level"]):
        base_out["reason"] = ("This assessment was produced by an earlier engine version and cannot be re-scored exactly, "
                              "so no counterfactuals are shown. Run a new assessment to enable them.")
        return base_out
    base = _snapshot(baseline)
    base_out["available"] = True
    base_out["current"] = {"risk_score": base["score"], "raw_points": base["raw"], "risk_level": base["level"],
                           "recommended_action": base["action"], "trust_break_detected": base["trust_break"],
                           "assessment_version": assessment.get("version_number")}
    max_score = baseline.max_score

    applicable, results = [], []
    for d in DEFINITIONS:
        hit = [s for s in signals if d.matches(s)]
        if not hit:
            continue
        applicable.append((d, hit))
    for order, (d, hit) in enumerate(applicable):
        remaining = [s for s in signals if not d.matches(s)]
        new = _snapshot(_run(remaining, inputs))
        affected = [{"code": s.code, "title": s.title, "category": s.category, "points": s.points} for s in hit]
        results.append({
            "id": d.id, "label": d.label, "description": d.description, "affected_signals": affected,
            "original_score": base["score"], "new_score": new["score"], "score_delta": new["score"] - base["score"],
            "original_raw_points": base["raw"], "new_raw_points": new["raw"], "raw_delta": new["raw"] - base["raw"],
            "original_level": base["level"], "new_level": new["level"],
            "original_action": base["action"], "new_action": new["action"],
            "level_changed": new["level"] != base["level"], "trust_break_after": new["trust_break"],
            "explanation": _explain(d.label, affected, base, new, max_score), "_order": order,
        })
    results.sort(key=lambda r: (r["score_delta"], r["raw_delta"], r["_order"]))  # biggest reduction first (most negative)
    for r in results:
        r.pop("_order")
    base_out["counterfactuals"] = results

    if results and (results[0]["score_delta"] < 0 or results[0]["raw_delta"] < 0):
        top = results[0]
        base_out["largest_reduction"] = {"id": top["id"], "label": top["label"], "score_delta": top["score_delta"],
                                         "raw_delta": top["raw_delta"]}
    # Smallest combination of what-ifs that lowers the risk level (exhaustive; at most 2^7 engine runs).
    best = None
    for size in range(2, len(applicable) + 1):
        for combo in combinations(range(len(applicable)), size):
            defs = [applicable[i][0] for i in combo]
            remaining = [s for s in signals if not any(d.matches(s) for d in defs)]
            snap = _snapshot(_run(remaining, inputs))
            if _LEVEL_RANK[snap["level"]] < _LEVEL_RANK[base["level"]]:
                key = (snap["score"], combo)
                if best is None or key < best[0]:
                    best = (key, defs, snap)
        if best:
            break
    singles_lower = [r for r in results if r["level_changed"]]
    if singles_lower:
        r = singles_lower[0]
        base_out["smallest_downgrade"] = {"ids": [r["id"]], "labels": [r["label"]], "new_score": r["new_score"],
                                          "new_level": r["new_level"], "new_action": r["new_action"]}
    elif best:
        _, defs, snap = best
        base_out["smallest_downgrade"] = {"ids": [d.id for d in defs], "labels": [d.label for d in defs],
                                          "new_score": snap["score"], "new_level": snap["level"], "new_action": snap["action"]}
    if base["raw"] > max_score:
        base_out["notes"].append(
            f"The current score is capped: raw points are {base['raw']} against a {max_score}-point display cap, so a single change "
            "may lower raw points without lowering the displayed score.")
    base_out["notes"].append("Simulations remove whole evidence groups from the stored, already-consolidated assessment; "
                             "they are analytical what-ifs, not historical facts.")
    return base_out
