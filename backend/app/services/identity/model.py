"""Trusted identity entity. Everything here is FICTIONAL demo data; no real people, accounts or banks."""

from dataclasses import dataclass, field
from typing import Optional


def normalize(text: Optional[str]) -> str:
    """Case-insensitive, whitespace-collapsed comparison key."""
    return " ".join((text or "").casefold().split())


@dataclass(frozen=True)
class TrustedIdentity:
    identity_id: str  # stable id, e.g. "CEO-001"; the key incidents link to
    employee_id: str
    display_name: str
    role: str
    department: str
    organization: str
    corporate_email: str
    phone_reference: str  # a synthetic reference, never a real number
    normal_channels: tuple[str, ...]  # lower-case keys used for behaviour comparison
    trusted_channels: tuple[str, ...]  # channels through which a verification may be trusted
    known_beneficiaries: tuple[str, ...]
    historical_amounts: tuple[int, ...]  # whole rupees
    typical_amount_min: int
    typical_amount_max: int
    typical_working_hours: str
    restricted_channels: tuple[str, ...] = ()
    aliases: tuple[str, ...] = field(default=())
    request_frequency: Optional[str] = None  # "low" | "medium" | "high"
    profile_version: int = 1
    created_at: str = "2026-10-01T00:00:00Z"
    updated_at: str = "2026-10-01T00:00:00Z"
    active: bool = True

    def to_dict(self) -> dict:
        return {
            "identity_id": self.identity_id,
            "employee_id": self.employee_id,
            "display_name": self.display_name,
            "role": self.role,
            "department": self.department,
            "organization": self.organization,
            "corporate_email": self.corporate_email,
            "phone_reference": self.phone_reference,
            "aliases": list(self.aliases),
            "normal_channels": list(self.normal_channels),
            "trusted_channels": list(self.trusted_channels),
            "restricted_channels": list(self.restricted_channels),
            "known_beneficiaries": list(self.known_beneficiaries),
            "typical_amount_min": self.typical_amount_min,
            "typical_amount_max": self.typical_amount_max,
            "typical_working_hours": self.typical_working_hours,
            "profile_version": self.profile_version,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "active": self.active,
            "profile_status": "Trusted synthetic demo profile",
        }

    def baseline_summary(self) -> dict:
        return {
            "typical_amount_min": self.typical_amount_min,
            "typical_amount_max": self.typical_amount_max,
            "historical_payment_count": len(self.historical_amounts),
            "request_frequency": self.request_frequency,
            "known_beneficiary_count": len(self.known_beneficiaries),
            "typical_working_hours": self.typical_working_hours,
            "note": "Synthetic baseline for demonstration; not derived from real transactions.",
        }
