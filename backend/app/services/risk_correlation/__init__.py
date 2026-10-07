"""Risk Engine 2.0: combines message, behaviour and attachment evidence into normalized, consolidated signals.

Deterministic, explainable, heuristic points (NOT probabilities). It only
recommends an action; it never blocks or executes a payment.

Public interface: `correlate_risk(...)` (pure) and `assess_incident_risk(...)`
(runs the analyzers first). See rules.py for weights and thresholds.
"""

from .engine import RiskCorrelationResult, action_for_level, collect_signals, consolidate, correlate_risk, correlate_signals, level_for_score
from .signals import RiskSignal
from .service import assess_incident_risk

__all__ = [
    "RiskCorrelationResult",
    "RiskSignal",
    "action_for_level",
    "assess_incident_risk",
    "collect_signals",
    "consolidate",
    "correlate_risk",
    "correlate_signals",
    "level_for_score",
]
