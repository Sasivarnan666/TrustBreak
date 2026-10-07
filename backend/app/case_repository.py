"""SQL for the case workflow audit trail (v0.7.0). Knows nothing about risk scoring."""

import sqlite3
from typing import Optional

OPEN = "OPEN"


def append_action(
    conn: sqlite3.Connection,
    *,
    incident_id: int,
    previous_status: Optional[str],
    new_status: str,
    decision: str,
    reason: str,
    analyst_name: Optional[str],
    created_at: str,
    assessment_id: Optional[int] = None,
) -> int:
    """Insert one audit row. Does NOT commit: the caller owns the transaction."""
    cursor = conn.execute(
        """
        INSERT INTO case_actions (incident_id, previous_status, new_status, decision, reason, analyst_name, created_at,
                                  assessment_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (incident_id, previous_status, new_status, decision, reason, analyst_name, created_at, assessment_id),
    )
    return cursor.lastrowid


def current_status(conn: sqlite3.Connection, incident_id: int) -> str:
    row = conn.execute(
        "SELECT new_status FROM case_actions WHERE incident_id = ? ORDER BY id DESC LIMIT 1", (incident_id,)
    ).fetchone()
    return row["new_status"] if row else OPEN


def list_actions(conn: sqlite3.Connection, incident_id: int) -> list[sqlite3.Row]:
    """Oldest first (insertion order)."""
    return conn.execute(
        """
        SELECT a.id, a.previous_status, a.new_status, a.decision, a.reason, a.analyst_name, a.created_at,
               a.assessment_id, h.version_number AS assessment_number,
               h.risk_score AS assessment_risk_score, h.risk_level AS assessment_risk_level
        FROM case_actions a
        LEFT JOIN risk_assessment_history h ON h.id = a.assessment_id
        WHERE a.incident_id = ? ORDER BY a.id ASC
        """,
        (incident_id,),
    ).fetchall()


OPENED_REASON = "Case opened automatically for human review. No analyst decision has been recorded."


def backfill_opened(conn: sqlite3.Connection) -> int:
    """Give incidents that predate v0.7.0 their CASE_OPENED row (dated at incident creation). Idempotent."""
    cursor = conn.execute(
        """
        INSERT INTO case_actions (incident_id, previous_status, new_status, decision, reason, analyst_name, created_at)
        SELECT i.id, NULL, 'OPEN', 'CASE_OPENED', ?, NULL, i.created_at
        FROM incidents i
        WHERE NOT EXISTS (SELECT 1 FROM case_actions a WHERE a.incident_id = i.id)
        """,
        (OPENED_REASON,),
    )
    return cursor.rowcount


def case_summary(conn: sqlite3.Connection) -> dict:
    """Counts of incidents per current workflow status, computed from persisted rows only."""
    total = conn.execute("SELECT COUNT(*) FROM incidents").fetchone()[0]
    counts = {"VERIFIED": 0, "REJECTED": 0}
    rows = conn.execute(
        """
        SELECT a.new_status AS status, COUNT(*) AS n
        FROM case_actions a
        WHERE a.id = (SELECT MAX(id) FROM case_actions WHERE incident_id = a.incident_id)
        GROUP BY a.new_status
        """
    ).fetchall()
    for row in rows:
        if row["status"] in counts:
            counts[row["status"]] = row["n"]
    closed = counts["VERIFIED"] + counts["REJECTED"]
    return {"total": total, "open": max(total - closed, 0), "verified": counts["VERIFIED"], "rejected": counts["REJECTED"]}


STATUS_SQL = "COALESCE((SELECT new_status FROM case_actions c WHERE c.incident_id = i.id ORDER BY c.id DESC LIMIT 1), 'OPEN')"
