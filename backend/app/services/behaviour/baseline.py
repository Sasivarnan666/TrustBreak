"""Descriptive metrics over a synthetic activity history (pure, stdlib only).

These are plain descriptive statistics of fictional demo data - not a trained model and not statistically
significant evidence. Percentiles use the nearest-rank method on completed events only.
"""

import math
from collections import Counter
from datetime import timedelta
from statistics import mean, median
from typing import Optional, Sequence

from .profile import normalize
from .workhours import parse_timestamp

MIN_BASELINE_EVENTS = 20  # below this, history-based checks report NOT_ENOUGH_BASELINE_DATA
MIN_BASELINE_SPAN_DAYS = 28
BURST_WINDOW_MINUTES = 10


def percentile(sorted_values: Sequence[int], p: float) -> Optional[int]:
    """Nearest-rank percentile (p in 0..100) of an ascending list."""
    if not sorted_values:
        return None
    rank = max(1, math.ceil(p / 100.0 * len(sorted_values)))
    return sorted_values[min(rank, len(sorted_values)) - 1]


def _share(counter: Counter, total: int) -> dict:
    return {k: {"count": v, "share": round(v / total, 4)} for k, v in sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))}


def max_burst(times: Sequence, window_minutes: int = BURST_WINDOW_MINUTES) -> int:
    """Largest number of events inside any window of `window_minutes` (times: ascending aware datetimes)."""
    best, lo = 0, 0
    span = timedelta(minutes=window_minutes)
    for hi in range(len(times)):
        while times[hi] - times[lo] > span:
            lo += 1
        best = max(best, hi - lo + 1)
    return best


def weekly_counts(times: Sequence) -> list:
    """Event counts per calendar week (Monday start) from the first to the last event, including empty weeks."""
    if not times:
        return []
    monday = lambda t: (t - timedelta(days=t.weekday())).date()
    counts = Counter(monday(t) for t in times)
    week, last, out = monday(times[0]), monday(times[-1]), []
    while week <= last:
        out.append(counts.get(week, 0))
        week += timedelta(days=7)
    return out


def compute_baseline(events: Sequence) -> Optional[dict]:
    """Summary metrics for a tuple of ActivityEvent, or None when there is no history."""
    done = [e for e in events if e.status == "completed"]
    stamped = sorted((parse_timestamp(e.timestamp), e) for e in done)
    stamped = [(t, e) for t, e in stamped if t is not None]
    if not stamped:
        return None
    times = [t for t, _ in stamped]
    amounts = sorted(e.amount for _, e in stamped)
    n = len(stamped)
    span_days = (times[-1] - times[0]).days
    weekly = weekly_counts(times)
    sufficient = n >= MIN_BASELINE_EVENTS and span_days >= MIN_BASELINE_SPAN_DAYS
    return {
        "label": "Synthetic behavioural baseline",
        "event_count": len(events),
        "completed_event_count": n,
        "period_start": times[0].isoformat(timespec="minutes"),
        "period_end": times[-1].isoformat(timespec="minutes"),
        "span_days": span_days,
        "sufficient": sufficient,
        "minimum_events_required": MIN_BASELINE_EVENTS,
        "amount": {
            "min": amounts[0], "max": amounts[-1], "mean": round(mean(amounts)), "median": round(median(amounts)),
            "p25": percentile(amounts, 25), "p75": percentile(amounts, 75), "p90": percentile(amounts, 90),
            "p95": percentile(amounts, 95), "p99": percentile(amounts, 99),
        },
        "frequency": {
            "per_week_mean": round(mean(weekly), 2) if weekly else 0.0,
            "per_week_max": max(weekly) if weekly else 0,
            "weeks_observed": len(weekly),
            "max_burst_in_window": max_burst(times),
            "burst_window_minutes": BURST_WINDOW_MINUTES,
        },
        "channels": _share(Counter(normalize(e.channel) for _, e in stamped), n),
        "beneficiaries": _share(Counter(e.beneficiary for _, e in stamped), n),
        "hour_distribution": {f"{h:02d}": c for h, c in sorted(Counter(t.hour for t in times).items())},
        "weekday_distribution": {d: c for d, c in sorted(Counter(t.strftime("%a") for t in times).items(), key=lambda kv: ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].index(kv[0]))},
    }


def amount_percentile(amounts: Sequence[int], value: int) -> dict:
    """Where `value` sits among historical completed amounts (sample rank, not a probability)."""
    n = len(amounts)
    at_or_below = sum(1 for a in amounts if a <= value)
    rank_pct = round(100.0 * at_or_below / n, 1) if n else None
    above_all = n > 0 and value > max(amounts)
    label = None
    if above_all:
        # ">99th percentile" is only claimed when the sample is large enough for that to be true (>= 100 events).
        label = ">99th percentile" if n >= 100 else f"Above every one of the {n} historical events"
    elif n:
        label = f"About the {rank_pct:g}th percentile of {n} historical events"
    return {"rank_percent": rank_pct, "above_all_history": above_all, "sample_size": n, "label": label}
