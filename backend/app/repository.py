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
from . import risk_repository
from .services.analysis import analyze_incident
from .services.risk_correlation.incident_status import NOT_ASSESSED, label_for_status


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
    if not row:
        return None
    incident = _row_to_incident(row)
    assessment = risk_repository.get_latest_risk_assessment(conn, incident_id)
    if assessment is not None:
        incident.risk_assessment = assessment
        incident.incident_status = assessment.incident_status
        incident.incident_status_label = assessment.incident_status_label
    return incident


def list_incidents(conn: sqlite3.Connection, limit: int = 100, offset: int = 0) -> list[IncidentSummary]:
    # One query: the latest assessment is a single row per incident, so a LEFT JOIN avoids N+1.
    rows = conn.execute(
        """
        SELECT i.*,
               r.risk_level AS r_risk_level, r.risk_score AS r_risk_score,
               r.recommended_action AS r_recommended_action, r.incident_status AS r_incident_status,
               r.trust_break_detected AS r_trust_break, r.assessed_at AS r_assessed_at
        FROM incidents i
        LEFT JOIN risk_assessments r ON r.incident_id = i.id
        ORDER BY i.id DESC LIMIT ? OFFSET ?
        """,
        (limit, offset),
    ).fetchall()
    return [_row_to_summary(row) for row in rows]


def count_incidents(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM incidents").fetchone()[0]


def _row_to_summary(row: sqlite3.Row) -> IncidentSummary:
    assessed = row["r_risk_level"] is not None
    action = row["r_recommended_action"] if assessed else None
    return IncidentSummary(
        incident_status=row["r_incident_status"] if assessed else NOT_ASSESSED,
        incident_status_label=label_for_status(row["r_incident_status"] if assessed else NOT_ASSESSED),
        risk_level=row["r_risk_level"],
        risk_score=row["r_risk_score"],
        recommended_action=action,
        recommended_action_label=risk_repository._ACTION_LABELS.get(action) if assessed else None,
        trust_break_detected=bool(row["r_trust_break"]) if assessed else False,
        assessed_at=row["r_assessed_at"],
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
