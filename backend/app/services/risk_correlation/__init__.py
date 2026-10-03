"""Risk correlation engine: combines message, behaviour and attachment evidence.

Deterministic, explainable, heuristic points (NOT probabilities). It only
recommends an action; it never blocks or executes a payment.

Public interface: `correlate_risk(...)` (pure) and `assess_incident_risk(...)`
(runs the analyzers first). See rules.py for weights and thresholds.
"""

from .engine import RiskCorrelationResult, RiskSignal, action_for_level, correlate_risk, level_for_score
from .service import assess_incident_risk

__all__ = [
    "RiskCorrelationResult",
    "RiskSignal",
    "action_for_level",
    "assess_incident_risk",
    "correlate_risk",
    "level_for_score",
]
