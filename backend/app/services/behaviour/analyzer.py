"""Deterministic behaviour analyzer.

Compares one payment request with a synthetic BehaviourProfile and returns
structured anomaly SIGNALS. This is not a risk score or a fraud verdict and it
is deliberately independent of message analysis and of `analyze_incident`.

Rules (all explainable, no statistics beyond a ratio to the profile maximum):
  amount      deviation = (amount - typical_max) / typical_max, floored at 0.
              <= 0            -> within baseline (no signal)
              0 < d <= 1.0    -> medium  (up to 2x the typical maximum)
              d > 1.0         -> high    (more than 2x the typical maximum)
  beneficiary not in the profile's known beneficiaries (case/space-insensitive)
              -> NEW_BENEFICIARY, high
  channel     not in the profile's normal channels (case/space-insensitive)
              -> UNUSUAL_CHANNEL, medium
  frequency   NOT evaluated: needs per-sender request history (future work).
"""

from dataclasses import dataclass
from typing import Optional

from .profile import BehaviourProfile, normalize

AMOUNT_HIGH_DEVIATION = 1.0  # more than 2x the typical maximum
FREQUENCY_NOTE = "Frequency is not evaluated: it needs per-sender request history, which does not exist yet."


@dataclass(frozen=True)
class BehaviourInput:
    channel: Optional[str] = None
    amount: Optional[int] = None
    beneficiary: Optional[str] = None


def _inr(amount: int) -> str:
    """Indian digit grouping: 1850000 -> ₹18,50,000."""
    s = str(abs(int(amount)))
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ",".join(parts + [tail])
    return "₹" + s


def _empty_result(employee_id: Optional[str]) -> dict:
    return {
        "employee_id": employee_id,
        "profile_found": False,
        "amount_anomaly": False,
        "amount_deviation": None,
        "new_beneficiary": False,
        "channel_anomaly": False,
        "frequency_anomaly": False,
        "checks": {},
        "anomalies": [],
        "profile_summary": None,
        "notes": [],
        "is_final_decision": False,
    }


def analyze_behaviour(data: BehaviourInput, profile: Optional[BehaviourProfile]) -> dict:
    """Return the structured behaviour result. Never raises on missing data."""
    if profile is None:
        result = _empty_result(None)
        result["notes"] = ["No behaviour profile exists for this sender, so nothing was compared.", FREQUENCY_NOTE]
        return result

    result = _empty_result(profile.employee_id)
    result["profile_found"] = True
    result["profile_summary"] = profile.to_dict()
    anomalies: list[dict] = []
    checks: dict = {}
    notes: list[str] = [FREQUENCY_NOTE]

    # ---- amount ---------------------------------------------------------- #
    typical_max = profile.max_amount
    if data.amount is None or data.amount <= 0:
        checks["amount"] = {"status": "not_evaluated", "reason": "No payment amount was provided."}
        notes.append("Amount check skipped: no amount provided.")
    elif typical_max is None or typical_max <= 0:
        checks["amount"] = {"status": "not_evaluated", "reason": "The profile has no payment history."}
        notes.append("Amount check skipped: profile has no payment history.")
    else:
        deviation = max(0.0, (data.amount - typical_max) / typical_max)
        result["amount_deviation"] = round(deviation, 2)
        is_anomaly = data.amount > typical_max
        result["amount_anomaly"] = is_anomaly
        checks["amount"] = {
            "status": "above_baseline" if is_anomaly else "within_baseline",
            "requested": data.amount,
            "typical_min": profile.min_amount,
            "typical_max": typical_max,
            "deviation": round(deviation, 2),
        }
        if is_anomaly:
            high = deviation > AMOUNT_HIGH_DEVIATION
            anomalies.append(
                {
                    "type": "amount",
                    "code": "AMOUNT_ABOVE_BASELINE",
                    "severity": "high" if high else "medium",
                    "message": (
                        f"Payment amount is {'significantly ' if high else ''}above the normal range: "
                        f"{_inr(data.amount)} requested vs a typical maximum of {_inr(typical_max)} "
                        f"({deviation:.2f}x above the maximum)."
                    ),
                }
            )

    # ---- beneficiary ----------------------------------------------------- #
    if not normalize(data.beneficiary):
        checks["beneficiary"] = {"status": "not_evaluated", "reason": "No beneficiary was provided."}
        notes.append("Beneficiary check skipped: no beneficiary provided.")
    else:
        known = {normalize(b) for b in profile.known_beneficiaries}
        is_new = normalize(data.beneficiary) not in known
        result["new_beneficiary"] = is_new
        checks["beneficiary"] = {"status": "new" if is_new else "known", "beneficiary": data.beneficiary}
        if is_new:
            anomalies.append(
                {
                    "type": "beneficiary",
                    "code": "NEW_BENEFICIARY",
                    "severity": "high",
                    "message": f"Beneficiary '{data.beneficiary}' has not appeared in the historical profile.",
                }
            )

    # ---- channel --------------------------------------------------------- #
    if not normalize(data.channel):
        checks["channel"] = {"status": "not_evaluated", "reason": "No communication channel was provided."}
        notes.append("Channel check skipped: no channel provided.")
    else:
        normal = {normalize(c) for c in profile.normal_channels}
        unusual = normalize(data.channel) not in normal
        result["channel_anomaly"] = unusual
        checks["channel"] = {"status": "unusual" if unusual else "normal", "channel": data.channel}
        if unusual:
            anomalies.append(
                {
                    "type": "channel",
                    "code": "UNUSUAL_CHANNEL",
                    "severity": "medium",
                    "message": f"{data.channel} is not a normal payment-authorization channel for this sender.",
                }
            )

    checks["frequency"] = {"status": "not_evaluated", "reason": "Needs request history (future enhancement)."}
    result["checks"] = checks
    result["anomalies"] = anomalies
    result["notes"] = notes
    return result
