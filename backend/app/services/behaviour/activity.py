"""Deterministic SYNTHETIC historical activity for the demo trusted identities.

This is fictional demo data generated from the identity registry with a fixed-seed integer generator: the same
identity yields byte-identical history on every run (no `random`, no clock, no I/O). It is NOT real enterprise
behavioural data and must never be presented as such.

Consistency with the registry (single source of truth): channels come from `normal_channels`, beneficiaries from
`known_beneficiaries`, amounts stay inside `typical_amount_min..typical_amount_max`, and every event falls inside
`typical_working_hours`. At most one event per day, so synthetic history never contains a burst.
"""

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import lru_cache
from typing import Optional

from .workhours import IST, parse_working_hours

ACTIVITY_START = datetime(2026, 1, 5, tzinfo=IST)  # fixed anchor (a Monday); never "now"
ACTIVITY_DAYS = 270
SYNTHETIC_LABEL = "Synthetic behavioural baseline (fictional demo data)"

# identity_id -> (event count, channel weights, beneficiary weights). Weights align with the identity's tuples.
_SPECS = {
    "CEO-001": (87, (68, 32), (5, 3, 2)),
    "CFO-001": (64, (45, 35, 20), (4, 3, 2, 1)),
}


@dataclass(frozen=True)
class ActivityEvent:
    activity_id: str
    identity_id: str
    timestamp: str  # ISO-8601 with +05:30
    channel: str
    amount: int
    currency: str
    beneficiary: str
    action: str
    status: str

    def to_dict(self) -> dict:
        return dict(self.__dict__)


class _Lcg:
    """Tiny fixed LCG (Numerical Recipes constants); deterministic across platforms and Python versions."""

    def __init__(self, seed_text: str):
        self.state = int.from_bytes(hashlib.sha256(seed_text.encode()).digest()[:8], "big") % (2**32)

    def next(self) -> int:
        self.state = (1664525 * self.state + 1013904223) % (2**32)
        return self.state >> 8

    def below(self, n: int) -> int:
        return self.next() % n

    def pick(self, items, weights):
        roll = self.below(sum(weights))
        for item, w in zip(items, weights):
            if roll < w:
                return item
            roll -= w
        return items[-1]


def _round(amount: int) -> int:
    return int(round(amount / 5000.0) * 5000)


@lru_cache(maxsize=None)
def generate_activity(identity) -> tuple:
    """Return the synthetic activity tuple for a TrustedIdentity (empty if it has no spec or unusable hours)."""
    spec = _SPECS.get(identity.identity_id)
    hours = parse_working_hours(identity.typical_working_hours)
    if spec is None or hours is None:
        return ()
    count, channel_w, bene_w = spec
    channels = identity.normal_channels
    benes = identity.known_beneficiaries
    if len(channels) != len(channel_w) or len(benes) != len(bene_w):
        return ()
    rng = _Lcg(f"trustbreak-synthetic-baseline:{identity.identity_id}:v1")
    lo, hi = identity.typical_amount_min, identity.typical_amount_max
    ladder = sorted(set(identity.historical_amounts)) or [lo, hi]

    events, used_days = [], set()
    for i in range(count):
        day = (i * ACTIVITY_DAYS) // count + rng.below(3)
        while True:  # next permitted working day with no event yet
            moment = ACTIVITY_START + timedelta(days=day)
            if moment.weekday() in hours.days and day not in used_days:
                break
            day += 1
        used_days.add(day)
        minute = hours.start_minute + rng.below(hours.end_minute - hours.start_minute)
        ts = moment.replace(hour=minute // 60, minute=minute % 60)
        base = ladder[rng.below(len(ladder))]
        amount = min(hi, max(lo, _round(base * (80 + rng.below(41)) // 100)))
        status = "completed" if rng.below(100) < 94 else "cancelled"
        events.append((ts, rng.pick(channels, channel_w), amount, rng.pick(benes, bene_w), status))

    events.sort(key=lambda e: e[0])
    return tuple(
        ActivityEvent(
            activity_id=f"{identity.identity_id}-A{n:03d}",
            identity_id=identity.identity_id,
            timestamp=ts.isoformat(timespec="minutes"),
            channel=channel,
            amount=amount,
            currency="INR",
            beneficiary=beneficiary,
            action="payment_request",
            status=status,
        )
        for n, (ts, channel, amount, beneficiary, status) in enumerate(events, start=1)
    )


def activity_for(identity) -> Optional[tuple]:
    return generate_activity(identity) if identity is not None else None
