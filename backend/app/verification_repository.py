"""SQL for the independent-verification audit trail (0.13.0). Append-only; knows nothing about risk scoring."""

import sqlite3
from typing import Optional


def append_event(conn: sqlite3.Connection, *, incident_id: int, event_type: str, state_after: str, method: Optional[str],
                 reason: str, analyst_name: str, created_at: str, assessment_id: Optional[int]) -> int:
    """Insert one immutable event. Does NOT commit: the caller owns the transaction."""
    cursor = conn.execute(
        """
        INSERT INTO verification_events (incident_id, event_type, state_after, method, reason, analyst_name, created_at, based_on_assessment_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (incident_id, event_type, state_after, method, reason, analyst_name, created_at, assessment_id),
    )
    return cursor.lastrowid


def list_events(conn: sqlite3.Connection, incident_id: int) -> list:
    """Oldest first."""
    return conn.execute(
        """
        SELECT v.id, v.event_type, v.state_after, v.method, v.reason, v.analyst_name, v.created_at, v.based_on_assessment_id AS assessment_id,
               h.version_number AS assessment_number
        FROM verification_events v
        LEFT JOIN risk_assessment_history h ON h.id = v.based_on_assessment_id
        WHERE v.incident_id = ? ORDER BY v.id ASC
        """,
        (incident_id,),
    ).fetchall()


def current_state(conn: sqlite3.Connection, incident_id: int) -> str:
    row = conn.execute("SELECT state_after FROM verification_events WHERE incident_id = ? ORDER BY id DESC LIMIT 1", (incident_id,)).fetchone()
    return row["state_after"] if row else "NOT_STARTED"


def summary(conn: sqlite3.Connection) -> dict:
    """Counts of incidents per CURRENT verification state (incidents with no event are not counted)."""
    counts = {"IN_PROGRESS": 0, "CONFIRMED": 0, "FAILED": 0}
    for row in conn.execute(
        """
        SELECT v.state_after AS state, COUNT(*) AS n FROM verification_events v
        WHERE v.id = (SELECT MAX(id) FROM verification_events WHERE incident_id = v.incident_id) GROUP BY v.state_after
        """
    ):
        if row["state"] in counts:
            counts[row["state"]] = row["n"]
    return {"in_progress": counts["IN_PROGRESS"], "confirmed": counts["CONFIRMED"], "failed": counts["FAILED"]}
