"""Human case workflow (v0.7.0): transition rules and the decision use-case.

Separate from the risk engine on purpose: risk level is what TrustBreak calculated; workflow status is what a
human analyst recorded. Recording a decision only reads the IDENTITY (id, version number) of the latest assessment,
to link the decision to exactly what the analyst reviewed (v0.8.0). It never changes an assessment, never reads
scoring data and never moves money.
"""

import sqlite3
from typing import Optional
from datetime import datetime, timezone

from .. import case_repository, risk_repository
from ..errors import AppError, NotFoundError
from ..schemas import CaseActionOut, CaseStateOut, CaseSummaryOut

OPEN, VERIFIED, REJECTED = "OPEN", "VERIFIED", "REJECTED"
CASE_OPENED = "CASE_OPENED"

STATUS_LABELS = {OPEN: "Open", VERIFIED: "Verified", REJECTED: "Rejected"}
DECISION_LABELS = {
    CASE_OPENED: "Case opened",
    VERIFIED: "Analyst verified the request",
    REJECTED: "Analyst rejected the case",
}
ALLOWED_DECISIONS = (VERIFIED, REJECTED)

# Explicit transition table. There is no reopening mechanism in v0.7.0, so closed states have no exits.
TRANSITIONS = {OPEN: frozenset({VERIFIED, REJECTED}), VERIFIED: frozenset(), REJECTED: frozenset()}

OPENED_REASON = case_repository.OPENED_REASON


def label_for_status(status: str) -> str:
    return STATUS_LABELS.get(status, status.title())


def can_transition(current: str, target: str) -> bool:
    return target in TRANSITIONS.get(current, frozenset())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def open_case(conn: sqlite3.Connection, incident_id: int, created_at: str) -> None:
    """Write the initial CASE_OPENED audit row. Runs inside the caller's transaction (no commit)."""
    case_repository.append_action(
        conn, incident_id=incident_id, previous_status=None, new_status=OPEN, decision=CASE_OPENED,
        reason=OPENED_REASON, analyst_name=None, created_at=created_at,
    )


def record_decision(
    conn: sqlite3.Connection,
    incident_id: int,
    decision: str,
    reason: str,
    analyst_name: str,
    assessment_id: Optional[int] = None,
) -> None:
    """Validate the transition, append the audit row and thereby update the current status, atomically."""
    if decision not in ALLOWED_DECISIONS:  # defence in depth; the request schema already restricts this
        raise AppError("invalid_decision", "Decision must be VERIFIED or REJECTED.", status_code=422)
    conn.execute("BEGIN IMMEDIATE")  # take the write lock first so check-and-write cannot interleave
    try:
        if conn.execute("SELECT 1 FROM incidents WHERE id = ?", (incident_id,)).fetchone() is None:
            raise NotFoundError(f"Incident {incident_id} was not found.")
        current = case_repository.current_status(conn, incident_id)
        if not can_transition(current, decision):
            raise _closed(current)
        latest = risk_repository.latest_assessment_ref(conn, incident_id)
        if assessment_id is not None:
            if not risk_repository.assessment_belongs_to(conn, incident_id, assessment_id):
                raise AppError(
                    "assessment_not_found", "That assessment does not belong to this incident.", status_code=422,
                    details=[{"field": "assessment_id", "message": "Unknown assessment for this incident."}],
                )
            if latest is None or latest[0] != assessment_id:
                raise AppError(
                    "assessment_superseded",
                    f"A newer assessment (v{latest[1]}) exists. Review it before recording a decision.",
                    status_code=409,
                    details=[{"field": "assessment_id", "message": f"Latest assessment is v{latest[1]}."}],
                )
        linked = latest[0] if latest else None  # explicit id was verified above to equal the latest
        case_repository.append_action(
            conn, incident_id=incident_id, previous_status=current, new_status=decision, decision=decision,
            reason=reason, analyst_name=analyst_name, created_at=_now(), assessment_id=linked,
        )
        conn.commit()
    except sqlite3.IntegrityError:  # unique one-decision index: a concurrent request closed the case first
        conn.rollback()
        raise _closed(case_repository.current_status(conn, incident_id))
    except BaseException:
        conn.rollback()
        raise


def _closed(current: str) -> AppError:
    return AppError(
        "case_already_closed",
        f"This case is already {label_for_status(current).lower()} and cannot be decided again.",
        status_code=409,
        details=[{"field": "decision", "message": f"Current case status is {current}."}],
    )


def case_history(conn: sqlite3.Connection, incident_id: int) -> list[CaseActionOut]:
    """The audit trail, oldest first. Database column names and row ids are not exposed."""
    return [
        CaseActionOut(
            previous_status=row["previous_status"],
            new_status=row["new_status"],
            new_status_label=label_for_status(row["new_status"]),
            decision=row["decision"],
            decision_label=DECISION_LABELS.get(row["decision"], row["decision"]),
            reason=row["reason"],
            analyst_name=row["analyst_name"],
            created_at=row["created_at"],
            assessment_id=row["assessment_id"],
            assessment_number=row["assessment_number"],
            assessment_risk_score=row["assessment_risk_score"],
            assessment_risk_level=row["assessment_risk_level"],
        )
        for row in case_repository.list_actions(conn, incident_id)
    ]


def case_state(conn: sqlite3.Connection, incident_id: int, reference: str) -> CaseStateOut:
    status = case_repository.current_status(conn, incident_id)
    return CaseStateOut(
        incident_id=incident_id,
        reference=reference,
        workflow_status=status,
        workflow_status_label=label_for_status(status),
        case_history=case_history(conn, incident_id),
    )


def case_summary(conn: sqlite3.Connection) -> CaseSummaryOut:
    return CaseSummaryOut(**case_repository.case_summary(conn))
