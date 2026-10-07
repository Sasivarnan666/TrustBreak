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
from . import case_repository, risk_repository
from .services import case_workflow
from .services.analysis import analyze_incident
from .services.identity import resolve_identity
from .services.risk_correlation.incident_status import NOT_ASSESSED, label_for_status


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _reference(incident_id: int) -> str:
    return f"TB-{incident_id:04d}"


def reference_for(incident_id: int) -> str:
    return _reference(incident_id)


def create_incident(conn: sqlite3.Connection, payload: IncidentCreate, scenario_id: Optional[str] = None) -> Incident:
    analysis = analyze_incident(payload)
    identity, identity_source = resolve_identity(payload.sender_identity_id, payload.sender_name)
    created_at = _now()
    title = f"Payment request from {payload.sender_name} via {payload.channel}"
    with conn:  # commits on success, rolls back on error
        cursor = conn.execute(
            """
            INSERT INTO incidents (
                created_at, title,
                sender_name, sender_role, sender_known, sender_contact,
                sender_identity_id, sender_identity_source,
                channel,
                amount, currency, beneficiary_name, beneficiary_is_new,
                message,
                attachment_name, attachment_size_bytes, attachment_content_type,
                analysis_mode, risk_status, analysis_summary, recommended_action, evidence_json,
                received_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'INR', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                created_at,
                title,
                payload.sender_name,
                payload.sender_role,
                int(payload.sender_known),
                payload.sender_contact,
                identity.identity_id if identity else None,
                identity_source,
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
                payload.received_at,
            ),
        )
        new_id = cursor.lastrowid
        if scenario_id:
            conn.execute("UPDATE incidents SET scenario_id = ? WHERE id = ?", (scenario_id, new_id))
        case_workflow.open_case(conn, new_id, created_at)  # same transaction: no incident without a case
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
        incident.assessment_history = risk_repository.list_assessment_history(conn, incident_id)
        incident.incident_status = assessment.incident_status
        incident.incident_status_label = assessment.incident_status_label
    # Workflow state lives in its own table; the assessment above is left exactly as stored.
    history = case_workflow.case_history(conn, incident_id)
    incident.case_history = history
    status = history[-1].new_status if history else case_workflow.OPEN
    incident.workflow_status = status
    incident.workflow_status_label = case_workflow.label_for_status(status)
    return incident


def list_incidents(conn: sqlite3.Connection, limit: int = 100, offset: int = 0) -> list[IncidentSummary]:
    # One query: the latest assessment is a single row per incident, so a LEFT JOIN avoids N+1.
    rows = conn.execute(
        f"""
        SELECT i.*,
               r.risk_level AS r_risk_level, r.risk_score AS r_risk_score,
               r.recommended_action AS r_recommended_action, r.incident_status AS r_incident_status,
               r.trust_break_detected AS r_trust_break, r.assessed_at AS r_assessed_at,
               {case_repository.STATUS_SQL} AS workflow_status
        FROM incidents i
        LEFT JOIN latest_risk_assessments r ON r.incident_id = i.id
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
        workflow_status=row["workflow_status"],
        workflow_status_label=case_workflow.label_for_status(row["workflow_status"]),
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
        scenario_id=row["scenario_id"],
        is_synthetic=bool(row["scenario_id"]),
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
        received_at=row["received_at"],
        scenario_id=row["scenario_id"],
        is_synthetic=bool(row["scenario_id"]),
        title=row["title"],
        sender=Sender(
            name=row["sender_name"],
            role=row["sender_role"],
            known=bool(row["sender_known"]),
            contact=row["sender_contact"],
            identity_id=row["sender_identity_id"],
            identity_source=row["sender_identity_source"] or "none",
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


def list_prior_request_times(conn: sqlite3.Connection, identity_id: Optional[str], before_id: int) -> Optional[tuple]:
    """received_at of EARLIER incidents (lower id) linked to the same trusted identity.

    Only rows with an explicit received_at count (the wall-clock created_at is when a record was typed in, not
    when a request arrived). None when the incident has no linked identity (history unavailable, not "zero").
    These are real stored values - nothing is synthesized.
    """
    if not identity_id:
        return None
    rows = conn.execute(
        "SELECT received_at FROM incidents WHERE sender_identity_id = ? AND id < ? AND received_at IS NOT NULL ORDER BY id", (identity_id, before_id)
    ).fetchall()
    return tuple(r["received_at"] for r in rows)
