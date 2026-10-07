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

Baseline 2.0 adds checks against a deterministic SYNTHETIC activity history (see activity.py / baseline.py):
  amount evidence    ratio to the typical maximum (9.25x for 18.5L vs 2L) and, only when a real sample rank exists,
                     the historical percentile
  channel_distribution  channel is a normal channel but < 10% of historical events -> CHANNEL_DISTRIBUTION_ANOMALY
  frequency   requests in the trailing 7 days (incl. this one) above the historical weekly maximum
  velocity    >= 3 requests inside 10 minutes and more than the historical maximum burst
  time / day  incident timestamp outside the identity's stored typical_working_hours (never when timestamp unknown)
History-dependent checks report status NOT_ENOUGH_BASELINE_DATA instead of inventing anomalies.
Frequency/velocity need real prior incidents supplied by the caller (`recent_request_times`); none are fabricated.
"""

from dataclasses import dataclass
from datetime import timedelta
from typing import Optional

from .baseline import BURST_WINDOW_MINUTES, MIN_BASELINE_EVENTS, amount_percentile, compute_baseline
from .profile import BehaviourProfile, normalize
from .workhours import parse_timestamp, parse_working_hours

AMOUNT_HIGH_DEVIATION = 1.0  # more than 2x the typical maximum
RARE_CHANNEL_SHARE = 0.10
VELOCITY_MIN_REQUESTS = 3
FREQUENCY_WINDOW_DAYS = 7
NOT_ENOUGH = "NOT_ENOUGH_BASELINE_DATA"
SOURCE = "synthetic_baseline"
FREQUENCY_NOTE = "Frequency and velocity are only evaluated when a synthetic baseline and prior incidents for this identity exist."


@dataclass(frozen=True)
class BehaviourInput:
    channel: Optional[str] = None
    amount: Optional[int] = None
    beneficiary: Optional[str] = None
    timestamp: Optional[str] = None  # when the request was recorded (ISO-8601); None = unknown -> no time checks
    # ISO timestamps of OTHER earlier incidents from the same identity; None = history unavailable (not "zero").
    recent_request_times: Optional[tuple] = None


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
        "baseline": None,
        "baseline_status": NOT_ENOUGH,
        "notes": [],
        "is_final_decision": False,
    }


def _anomaly(type_: str, code: str, severity: str, message: str, evidence: dict) -> dict:
    return {"type": type_, "code": code, "severity": severity, "message": message, "source": SOURCE, "evidence": evidence}


def _history_checks(data: BehaviourInput, profile: BehaviourProfile, result: dict, checks: dict, anomalies: list, notes: list) -> None:
    """Baseline 2.0 checks. Only signal when there is enough synthetic baseline; never invent anomalies."""
    baseline = compute_baseline(profile.activity) if profile.activity else None
    enough = bool(baseline and baseline["sufficient"])
    result["baseline"] = baseline
    result["baseline_status"] = "SYNTHETIC_BASELINE_AVAILABLE" if enough else NOT_ENOUGH
    if baseline:
        # attach the historical distributions to the legacy checks so the UI/evidence can show them
        if "channel" in checks and checks["channel"].get("status") in {"normal", "unusual"}:
            checks["channel"]["historical_distribution"] = baseline["channels"]
            absent = normalize(data.channel) not in baseline["channels"]
            checks["channel"]["absent_from_history"] = absent
            if checks["channel"]["status"] == "unusual" and absent:
                anomalies_by = {a["code"]: a for a in anomalies}
                if "UNUSUAL_CHANNEL" in anomalies_by:
                    anomalies_by["UNUSUAL_CHANNEL"]["evidence"]["historical_distribution"] = baseline["channels"]
                    anomalies_by["UNUSUAL_CHANNEL"]["evidence"]["absent_from_history"] = True
        if "beneficiary" in checks and checks["beneficiary"].get("status") in {"new", "known"}:
            checks["beneficiary"]["historical_frequency"] = baseline["beneficiaries"]
    not_enough = {"status": NOT_ENOUGH, "reason": f"Fewer than {MIN_BASELINE_EVENTS} synthetic historical events (or too short a period)."}

    # ---- channel distribution (rare-but-known channel; absent channels are UNUSUAL_CHANNEL, not double counted) ---- #
    if not normalize(data.channel):
        checks["channel_distribution"] = {"status": "not_evaluated", "reason": "No communication channel was provided."}
    elif not enough:
        checks["channel_distribution"] = dict(not_enough)
    else:
        entry = baseline["channels"].get(normalize(data.channel))
        if entry is None:
            checks["channel_distribution"] = {"status": "absent_from_history", "reason": "Covered by the unusual-channel check.", "distribution": baseline["channels"]}
        elif entry["share"] < RARE_CHANNEL_SHARE:
            checks["channel_distribution"] = {"status": "rare", "share": entry["share"], "distribution": baseline["channels"]}
            anomalies.append(_anomaly(
                "channel_distribution", "CHANNEL_DISTRIBUTION_ANOMALY", "medium",
                f"{data.channel} accounts for only {entry['share'] * 100:.0f}% of this identity's synthetic historical activity.",
                {"observed": data.channel, "share": entry["share"], "distribution": baseline["channels"]},
            ))
        else:
            checks["channel_distribution"] = {"status": "usual", "share": entry["share"], "distribution": baseline["channels"]}

    # ---- time / day against the identity's stored working hours ------------------------------------------------ #
    moment = parse_timestamp(data.timestamp)
    hours = parse_working_hours(profile.working_hours)
    if moment is None:
        checks["time"] = checks["day"] = {"status": "not_evaluated", "reason": "The request timestamp is unknown."}
        notes.append("Time and day checks skipped: request timestamp unknown.")
    elif hours is None:
        checks["time"] = checks["day"] = {"status": "not_evaluated", "reason": "No parseable working hours are stored for this identity."}
    else:
        local = moment.strftime("%a %H:%M IST")
        in_time, in_day = hours.contains_time(moment), hours.contains_day(moment)
        checks["time"] = {"status": "usual" if in_time else "unusual", "observed": local, "working_hours": hours.label}
        checks["day"] = {"status": "usual" if in_day else "unusual", "observed": moment.strftime("%A"), "working_hours": hours.label}
        if not in_time:
            anomalies.append(_anomaly("time", "UNUSUAL_TIME", "medium",
                                      f"Request recorded at {local}, outside the usual working hours ({hours.label}).",
                                      {"observed": local, "working_hours": hours.label}))
        if not in_day:
            anomalies.append(_anomaly("day", "UNUSUAL_DAY", "medium",
                                      f"Request recorded on {moment.strftime('%A')}, outside the usual working days ({hours.label}).",
                                      {"observed": moment.strftime("%A"), "working_hours": hours.label}))

    # ---- frequency / velocity: need real prior incidents for this identity ------------------------------------- #
    if not enough:
        checks["frequency"] = dict(not_enough)
        checks["velocity"] = dict(not_enough)
    elif moment is None or data.recent_request_times is None:
        reason = "The request timestamp is unknown." if moment is None else "No prior-incident history was supplied."
        checks["frequency"] = checks["velocity"] = {"status": "not_evaluated", "reason": reason}
    else:
        prior = sorted(t for t in (parse_timestamp(v) for v in data.recent_request_times) if t is not None and t <= moment)
        week = 1 + sum(1 for t in prior if t > moment - timedelta(days=FREQUENCY_WINDOW_DAYS))
        burst = 1 + sum(1 for t in prior if t > moment - timedelta(minutes=BURST_WINDOW_MINUTES))
        hist_week = baseline["frequency"]["per_week_max"]
        hist_burst = baseline["frequency"]["max_burst_in_window"]
        is_freq = week > hist_week
        is_vel = burst >= VELOCITY_MIN_REQUESTS and burst > hist_burst
        result["frequency_anomaly"] = is_freq
        checks["frequency"] = {"status": "above_baseline" if is_freq else "within_baseline", "requests_last_7_days": week,
                               "historical_weekly_max": hist_week, "historical_weekly_mean": baseline["frequency"]["per_week_mean"]}
        checks["velocity"] = {"status": "above_baseline" if is_vel else "within_baseline",
                              "requests_in_window": burst, "window_minutes": BURST_WINDOW_MINUTES,
                              "historical_max_in_window": hist_burst}
        if is_freq:
            anomalies.append(_anomaly("frequency", "FREQUENCY_ANOMALY", "medium",
                                      f"{week} requests in the last {FREQUENCY_WINDOW_DAYS} days vs a historical weekly maximum of {hist_week}.",
                                      checks["frequency"]))
        if is_vel:
            anomalies.append(_anomaly("velocity", "VELOCITY_ANOMALY", "high",
                                      f"{burst} requests within {BURST_WINDOW_MINUTES} minutes vs a historical maximum of {hist_burst}.",
                                      checks["velocity"]))


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
            "ratio_to_typical_max": round(data.amount / typical_max, 2),
        }
        done_amounts = [e.amount for e in profile.activity if e.status == "completed"]
        if len(done_amounts) >= MIN_BASELINE_EVENTS:
            checks["amount"]["percentile"] = amount_percentile(done_amounts, data.amount)
        if is_anomaly:
            high = deviation > AMOUNT_HIGH_DEVIATION
            anomalies.append(
                {
                    "type": "amount",
                    "code": "AMOUNT_ABOVE_BASELINE",
                    "severity": "high" if high else "medium",
                    "source": SOURCE,
                    "evidence": {
                        "requested": data.amount,
                        "typical_max": typical_max,
                        "typical_min": profile.min_amount,
                        "ratio_to_typical_max": round(data.amount / typical_max, 2),
                        "percentile": checks["amount"].get("percentile"),
                    },
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
        checks["beneficiary"] = {
            "status": "new" if is_new else "known",
            "beneficiary": data.beneficiary,
            "known_beneficiaries": list(profile.known_beneficiaries),
        }
        if is_new:
            anomalies.append(
                {
                    "type": "beneficiary",
                    "code": "NEW_BENEFICIARY",
                    "severity": "high",
                    "source": SOURCE,
                    "evidence": {"observed": data.beneficiary, "known_beneficiaries": list(profile.known_beneficiaries)},
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
        checks["channel"] = {
            "status": "unusual" if unusual else "normal",
            "channel": data.channel,
            "normal_channels": list(profile.normal_channels),
        }
        if unusual:
            anomalies.append(
                {
                    "type": "channel",
                    "code": "UNUSUAL_CHANNEL",
                    "severity": "medium",
                    "source": SOURCE,
                    "evidence": {"observed": data.channel, "normal_channels": list(profile.normal_channels)},
                    "message": f"{data.channel} is not a normal payment-authorization channel for this sender.",
                }
            )

    _history_checks(data, profile, result, checks, anomalies, notes)
    result["checks"] = checks
    result["anomalies"] = anomalies
    result["notes"] = notes
    return result
