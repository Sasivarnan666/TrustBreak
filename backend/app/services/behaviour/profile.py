"""Synthetic behaviour profile model and demo registry.

Everything here is fictional demo data. No real people, accounts or banks.
Stdlib only, so it can be tested without FastAPI.
"""

from dataclasses import dataclass, field
from typing import Optional


def normalize(text: Optional[str]) -> str:
    """Case-insensitive, whitespace-collapsed comparison key."""
    return " ".join((text or "").casefold().split())


@dataclass(frozen=True)
class BehaviourProfile:
    employee_id: str
    name: str
    role: str
    normal_channels: tuple[str, ...]  # lower-case keys, e.g. "email", "erp"
    known_beneficiaries: tuple[str, ...]
    historical_amounts: tuple[int, ...]  # whole rupees
    typical_min_amount: Optional[int] = None  # defaults to min(history)
    typical_max_amount: Optional[int] = None  # defaults to max(history)
    request_frequency: Optional[str] = None  # "low" | "medium" | "high"; informational only for now
    aliases: tuple[str, ...] = field(default=())

    @property
    def min_amount(self) -> Optional[int]:
        if self.typical_min_amount is not None:
            return self.typical_min_amount
        return min(self.historical_amounts) if self.historical_amounts else None

    @property
    def max_amount(self) -> Optional[int]:
        if self.typical_max_amount is not None:
            return self.typical_max_amount
        return max(self.historical_amounts) if self.historical_amounts else None

    def to_dict(self) -> dict:
        return {
            "employee_id": self.employee_id,
            "name": self.name,
            "role": self.role,
            "normal_channels": list(self.normal_channels),
            "known_beneficiaries": list(self.known_beneficiaries),
            "typical_min_amount": self.min_amount,
            "typical_max_amount": self.max_amount,
            "historical_payment_count": len(self.historical_amounts),
            "request_frequency": self.request_frequency,
        }


# --- Synthetic demo registry (matches the seeded demo incident's sender) ----- #
_DEMO_PROFILES = (
    BehaviourProfile(
        employee_id="CEO-001",
        name="Arvind Rao",
        role="Chief Executive Officer",
        normal_channels=("email", "erp"),
        known_beneficiaries=("Vendor A", "Vendor B", "Vendor C"),
        historical_amounts=(10_000, 25_000, 50_000, 75_000, 120_000, 200_000),
        typical_max_amount=200_000,
        request_frequency="low",
    ),
    BehaviourProfile(
        employee_id="CFO-001",
        name="Meera Iyer",
        role="Chief Financial Officer",
        normal_channels=("email", "erp", "phone call"),
        known_beneficiaries=("Vendor A", "Vendor B", "Vendor D", "Vendor E"),
        historical_amounts=(50_000, 150_000, 400_000, 750_000, 1_200_000),
        request_frequency="medium",
    ),
)


def get_profile_for_sender(sender_name: Optional[str]) -> Optional[BehaviourProfile]:
    """Look up a synthetic profile by sender name (or alias). None if unknown."""
    key = normalize(sender_name)
    if not key:
        return None
    for profile in _DEMO_PROFILES:
        if key == normalize(profile.name) or key in {normalize(a) for a in profile.aliases}:
            return profile
    return None
