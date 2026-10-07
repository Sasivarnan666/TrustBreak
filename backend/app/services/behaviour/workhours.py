"""Parse the identity's stored `typical_working_hours` string, e.g. "09:00-19:00 IST, Mon-Sat".

Only IST (UTC+05:30) is understood; anything unparseable returns None, and the time/day checks then report
"not evaluated" instead of inventing an anomaly.
"""

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

IST = timezone(timedelta(hours=5, minutes=30), "IST")
_DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
_PATTERN = re.compile(
    r"^\s*(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})\s*IST\s*,\s*([A-Za-z]{3})\s*-\s*([A-Za-z]{3})\s*$"
)


@dataclass(frozen=True)
class WorkingHours:
    start_minute: int  # minutes after local midnight
    end_minute: int
    days: frozenset  # 0 = Monday ... 6 = Sunday
    label: str

    def contains_time(self, local: datetime) -> bool:
        minute = local.hour * 60 + local.minute
        return self.start_minute <= minute <= self.end_minute

    def contains_day(self, local: datetime) -> bool:
        return local.weekday() in self.days


def parse_working_hours(text: Optional[str]) -> Optional[WorkingHours]:
    match = _PATTERN.match(text or "")
    if not match:
        return None
    h1, m1, h2, m2, d1, d2 = match.groups()
    start, end = int(h1) * 60 + int(m1), int(h2) * 60 + int(m2)
    d1, d2 = d1.lower(), d2.lower()
    if d1 not in _DAYS or d2 not in _DAYS or not (0 <= start < end <= 24 * 60):
        return None
    i, j = _DAYS.index(d1), _DAYS.index(d2)
    days = frozenset(range(i, j + 1)) if i <= j else frozenset(list(range(i, 7)) + list(range(0, j + 1)))
    return WorkingHours(start, end, days, text.strip())


def parse_timestamp(value) -> Optional[datetime]:
    """ISO-8601 -> aware datetime in IST. Naive values are treated as UTC. Unknown/invalid -> None."""
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str) and value.strip():
        try:
            dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(IST)
