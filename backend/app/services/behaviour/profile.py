"""Synthetic behaviour profile model and demo registry.

Everything here is fictional demo data. No real people, accounts or banks.
Stdlib only, so it can be tested without FastAPI.
"""

from dataclasses import dataclass, field
from typing import Optional

from ..identity import get_identity, resolve_by_name
from .activity import generate_activity


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
    activity: tuple = field(default=())  # synthetic ActivityEvent history (empty = no history available)
    working_hours: Optional[str] = None  # the identity's stored typical_working_hours string

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
            "historical_activity_count": len(self.activity),
            "working_hours": self.working_hours,
        }


# --- Synthetic demo registry: derived from the trusted-identity registry (single source of truth) ---- #
def profile_from_identity(identity) -> BehaviourProfile:
    return BehaviourProfile(
        employee_id=identity.employee_id,
        name=identity.display_name,
        role=identity.role,
        normal_channels=identity.normal_channels,
        known_beneficiaries=identity.known_beneficiaries,
        historical_amounts=identity.historical_amounts,
        typical_min_amount=identity.typical_amount_min,
        typical_max_amount=identity.typical_amount_max,
        request_frequency=identity.request_frequency,
        aliases=identity.aliases,
        activity=generate_activity(identity),
        working_hours=identity.typical_working_hours,
    )


def get_profile_for_identity(identity_id: Optional[str]) -> Optional[BehaviourProfile]:
    """Preferred lookup: the stable identity id."""
    identity = get_identity(identity_id)
    return profile_from_identity(identity) if identity else None


def get_profile_for_sender(sender_name: Optional[str]) -> Optional[BehaviourProfile]:
    """Backwards-compatible fallback: exact name/alias. None if unknown."""
    identity = resolve_by_name(sender_name)
    return profile_from_identity(identity) if identity else None
