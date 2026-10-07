"""Synthetic identity registry (code-resident, no DB table).

Resolution order used by the system:
  1. explicit `identity_id` (stable id)                    -> source "explicit"
  2. exact display name / alias (backwards-compat fallback) -> source "name_match"
  3. nothing                                               -> None
Role or substring matching is never used.
"""

from typing import Optional

from .model import TrustedIdentity, normalize

_IDENTITIES = (
    TrustedIdentity(
        identity_id="CEO-001",
        employee_id="CEO-001",
        display_name="Arvind Rao",
        role="Chief Executive Officer",
        department="Executive",
        organization="NovaTech Industries",
        corporate_email="arvind.rao@novatech.example",
        phone_reference="NT-EXEC-PHONE-001 (known corporate phone)",
        normal_channels=("email", "erp"),
        trusted_channels=("email", "erp", "known corporate phone"),
        restricted_channels=("whatsapp", "sms"),
        known_beneficiaries=("Vendor A", "Vendor B", "Vendor C"),
        historical_amounts=(20_000, 25_000, 50_000, 75_000, 120_000, 200_000),
        typical_amount_min=20_000,
        typical_amount_max=200_000,
        typical_working_hours="09:00-19:00 IST, Mon-Sat",
        request_frequency="low",
    ),
    TrustedIdentity(
        identity_id="CFO-001",
        employee_id="CFO-001",
        display_name="Meera Iyer",
        role="Chief Financial Officer",
        department="Finance",
        organization="NovaTech Industries",
        corporate_email="meera.iyer@novatech.example",
        phone_reference="NT-FIN-PHONE-001 (known corporate phone)",
        normal_channels=("email", "erp", "phone call"),
        trusted_channels=("email", "erp", "phone call"),
        restricted_channels=("whatsapp",),
        known_beneficiaries=("Vendor A", "Vendor B", "Vendor D", "Vendor E"),
        historical_amounts=(50_000, 150_000, 400_000, 750_000, 1_200_000),
        typical_amount_min=50_000,
        typical_amount_max=1_200_000,
        typical_working_hours="09:30-18:30 IST, Mon-Fri",
        request_frequency="medium",
    ),
)

_BY_ID = {i.identity_id: i for i in _IDENTITIES}


def list_identities() -> list[TrustedIdentity]:
    return [i for i in _IDENTITIES if i.active]


def get_identity(identity_id: Optional[str]) -> Optional[TrustedIdentity]:
    if not identity_id:
        return None
    return _BY_ID.get(identity_id.strip().upper())


def resolve_by_name(name: Optional[str]) -> Optional[TrustedIdentity]:
    """Backwards-compatible fallback: exact display name or alias, casefold + whitespace collapse."""
    key = normalize(name)
    if not key:
        return None
    for identity in _IDENTITIES:
        if key == normalize(identity.display_name) or key in {normalize(a) for a in identity.aliases}:
            return identity
    return None


def resolve_identity(identity_id: Optional[str], name: Optional[str]) -> tuple[Optional[TrustedIdentity], str]:
    """Return (identity, source). An explicit id that is unknown does NOT fall back to the name."""
    if identity_id:
        found = get_identity(identity_id)
        return (found, "explicit") if found else (None, "unknown_id")
    found = resolve_by_name(name)
    return (found, "name_match") if found else (None, "none")
