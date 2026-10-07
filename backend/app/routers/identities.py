"""/api/identities: read-only synthetic trusted identities (no writes, no real personal data)."""

import sqlite3

from fastapi import APIRouter, Depends

from ..database import get_db
from ..errors import NotFoundError
from ..schemas import (
    IdentityActivityOut,
    IdentityDetailOut,
    IdentityDetailResponse,
    IdentityListResponse,
    TrustedIdentityOut,
)
from ..services.identity import get_identity, list_identities

router = APIRouter(prefix="/api/identities", tags=["identities"])


def _activity(conn: sqlite3.Connection, identity) -> IdentityActivityOut:
    """Historical activity from stored incidents linked by id (or, for pre-0.9.0 rows without an id, by exact name)."""
    rows = conn.execute(
        """
        SELECT created_at, channel, beneficiary_name, amount FROM incidents
        WHERE sender_identity_id = ? OR (sender_identity_id IS NULL AND lower(trim(sender_name)) = lower(?))
        ORDER BY id
        """,
        (identity.identity_id, identity.display_name),
    ).fetchall()
    return IdentityActivityOut(
        incident_count=len(rows),
        last_incident_at=rows[-1]["created_at"] if rows else None,
        channels_seen=sorted({r["channel"] for r in rows}),
        beneficiaries_seen=sorted({r["beneficiary_name"] for r in rows}),
        max_amount_seen=max((r["amount"] for r in rows), default=None),
    )


@router.get("", response_model=IdentityListResponse)
def list_all():
    return IdentityListResponse(data=[TrustedIdentityOut(**i.to_dict()) for i in list_identities()])


@router.get("/{identity_id}", response_model=IdentityDetailResponse)
def get_one(identity_id: str, db: sqlite3.Connection = Depends(get_db)):
    identity = get_identity(identity_id)
    if identity is None:
        raise NotFoundError(f"Trusted identity '{identity_id}' was not found.")
    return IdentityDetailResponse(
        data=IdentityDetailOut(
            identity=TrustedIdentityOut(**identity.to_dict()),
            baseline=identity.baseline_summary(),
            activity=_activity(db, identity),
        )
    )
