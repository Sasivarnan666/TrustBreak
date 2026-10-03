"""Persistence for incidents. Plain SQL over the stdlib sqlite3 connection."""

import json
import sqlite3
from datetime import datetime, timezone
from typing import Optional

from .schemas import (
    Analysis,
    Attachment,
    EvidenceItem,
    Incident,
    IncidentCreate,
    IncidentSummary,
    Payment,
    Sender,
)
from .services.analysis import analyze_incident


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _reference(incident_id: int) -> str:
    return f"TB-{incident_id:04d}"


def create_incident(conn: sqlite3.Connection, payload: IncidentCreate) -> Incident:
    analysis = analyze_incident(payload)
    title = f"Payment request from {payload.sender_name} via {payload.channel}"
    with conn:  # commits on success, rolls back on error
        cursor = conn.execute(
            """
            INSERT INTO incidents (
                created_at, title,
                sender_name, sender_role, sender_known, sender_contact,
                channel,
                amount, currency, beneficiary_name, beneficiary_is_new,
                message,
                attachment_name, attachment_size_bytes, attachment_content_type,
                analysis_mode, risk_status, analysis_summary, recommended_action, evidence_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'INR', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _now(),
                title,
                payload.sender_name,
                payload.sender_role,
                int(payload.sender_known),
                payload.sender_contact,
                payload.channel,
                payload.amount,
                payload.beneficiary_name,
                int(payload.beneficiary_is_new),
                payload.message,
                payload.attachment_name,
                payload.attachment_size_bytes,
                payload.attachment_content_type,
                analysis.mode,
                analysis.risk_status,
                analysis.summary,
                analysis.recommended_action,
                json.dumps([item.model_dump() for item in analysis.evidence]),
            ),
        )
        new_id = cursor.lastrowid
    created = get_incident(conn, new_id)
    assert created is not None  # just inserted
    return created


def get_incident(conn: sqlite3.Connection, incident_id: int) -> Optional[Incident]:
    row = conn.execute("SELECT * FROM incidents WHERE id = ?", (incident_id,)).fetchone()
    return _row_to_incident(row) if row else None


def list_incidents(conn: sqlite3.Connection, limit: int = 100, offset: int = 0) -> list[IncidentSummary]:
    rows = conn.execute(
        "SELECT * FROM incidents ORDER BY id DESC LIMIT ? OFFSET ?", (limit, offset)
    ).fetchall()
    return [_row_to_summary(row) for row in rows]


def count_incidents(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM incidents").fetchone()[0]


def _row_to_summary(row: sqlite3.Row) -> IncidentSummary:
    return IncidentSummary(
        id=row["id"],
        reference=_reference(row["id"]),
        created_at=row["created_at"],
        title=row["title"],
        sender_name=row["sender_name"],
        sender_role=row["sender_role"],
        sender_known=bool(row["sender_known"]),
        channel=row["channel"],
        amount=row["amount"],
        currency=row["currency"],
        beneficiary_name=row["beneficiary_name"],
        beneficiary_is_new=bool(row["beneficiary_is_new"]),
        has_attachment=bool(row["attachment_name"]),
        risk_status=row["risk_status"],
    )


def _row_to_incident(row: sqlite3.Row) -> Incident:
    attachment = None
    if row["attachment_name"]:
        attachment = Attachment(
            name=row["attachment_name"],
            size_bytes=row["attachment_size_bytes"],
            content_type=row["attachment_content_type"],
        )
    return Incident(
        id=row["id"],
        reference=_reference(row["id"]),
        created_at=row["created_at"],
        title=row["title"],
        sender=Sender(
            name=row["sender_name"],
            role=row["sender_role"],
            known=bool(row["sender_known"]),
            contact=row["sender_contact"],
        ),
        channel=row["channel"],
        payment=Payment(
            amount=row["amount"],
            currency=row["currency"],
            beneficiary_name=row["beneficiary_name"],
            beneficiary_is_new=bool(row["beneficiary_is_new"]),
        ),
        message=row["message"],
        attachment=attachment,
        analysis=Analysis(
            mode=row["analysis_mode"],
            risk_status=row["risk_status"],
            summary=row["analysis_summary"],
            recommended_action=row["recommended_action"],
            evidence=[EvidenceItem(**item) for item in json.loads(row["evidence_json"])],
        ),
    )
