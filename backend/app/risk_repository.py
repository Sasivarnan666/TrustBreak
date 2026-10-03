"""Persistence for risk assessments (plain SQL over stdlib sqlite3).

The risk engine stays pure; this module only stores and loads the engine's
output. One row per incident holds the LATEST assessment snapshot: running the
assessment again replaces it. Uploaded attachment bytes never reach this module
- only the structured result (signals, input statuses, notes) is stored.
"""

import json
import sqlite3
from datetime import datetime, timezone
from typing import Optional

from .schemas import StoredRiskAssessmentOut
from .services.risk_correlation.incident_status import label_for_status, status_for_level

# Bump when weights, thresholds or the stored shape change, so old snapshots stay interpretable.
ASSESSMENT_VERSION = "0.6.0"

_REQUIRED_KEYS = (
    "risk_score", "raw_points", "max_score", "risk_level", "recommended_action", "recommended_action_guidance",
    "trust_break_detected", "headline", "explanation", "signals", "inputs", "notes", "disclaimer",
)


class IncidentNotFound(LookupError):
    """Raised when saving an assessment for an incident that does not exist."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def save_risk_assessment(
    conn: sqlite3.Connection,
    incident_id: int,
    result: dict,
    assessed_at: Optional[str] = None,
) -> StoredRiskAssessmentOut:
    """Insert or replace the latest assessment for an incident and return it as stored.

    `result` is `RiskCorrelationResult.to_dict()`. Raises IncidentNotFound for an
    unknown incident and ValueError for a malformed result (nothing is written).
    """
    missing = [key for key in _REQUIRED_KEYS if key not in result]
    if missing:
        raise ValueError(f"Risk result is missing: {', '.join(missing)}")
    when = assessed_at or _now()
    with conn:  # one transaction: existence check + upsert
        if conn.execute("SELECT 1 FROM incidents WHERE id = ?", (incident_id,)).fetchone() is None:
            raise IncidentNotFound(f"Incident {incident_id} was not found.")
        conn.execute(
            """
            INSERT INTO risk_assessments (
                incident_id, assessment_version, assessed_at,
                risk_score, raw_points, max_score, risk_level, recommended_action, incident_status,
                trust_break_detected, headline, explanation, recommended_action_guidance,
                signals_json, category_points_json, inputs_json, thresholds_json, notes_json,
                scoring_method, disclaimer
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(incident_id) DO UPDATE SET
                assessment_version = excluded.assessment_version, assessed_at = excluded.assessed_at,
                risk_score = excluded.risk_score, raw_points = excluded.raw_points, max_score = excluded.max_score,
                risk_level = excluded.risk_level, recommended_action = excluded.recommended_action,
                incident_status = excluded.incident_status, trust_break_detected = excluded.trust_break_detected,
                headline = excluded.headline, explanation = excluded.explanation,
                recommended_action_guidance = excluded.recommended_action_guidance,
                signals_json = excluded.signals_json, category_points_json = excluded.category_points_json,
                inputs_json = excluded.inputs_json, thresholds_json = excluded.thresholds_json,
                notes_json = excluded.notes_json, scoring_method = excluded.scoring_method,
                disclaimer = excluded.disclaimer
            """,
            (
                incident_id, ASSESSMENT_VERSION, when,
                result["risk_score"], result["raw_points"], result["max_score"], result["risk_level"],
                result["recommended_action"], status_for_level(result["risk_level"]),
                int(bool(result["trust_break_detected"])), result["headline"], result["explanation"],
                result["recommended_action_guidance"],
                json.dumps(result["signals"]), json.dumps(result.get("category_points", {})),
                json.dumps(result["inputs"]), json.dumps(result.get("thresholds", [])),
                json.dumps(result["notes"]),
                result.get("scoring_method", "heuristic_points"), result["disclaimer"],
            ),
        )
    stored = get_latest_risk_assessment(conn, incident_id)
    assert stored is not None  # just written
    return stored


def get_latest_risk_assessment(conn: sqlite3.Connection, incident_id: int) -> Optional[StoredRiskAssessmentOut]:
    """Latest persisted assessment for the incident, or None (also for an unknown incident)."""
    row = conn.execute("SELECT * FROM risk_assessments WHERE incident_id = ?", (incident_id,)).fetchone()
    return row_to_assessment(row) if row else None


def row_to_assessment(row: sqlite3.Row) -> StoredRiskAssessmentOut:
    return StoredRiskAssessmentOut(
        incident_id=row["incident_id"],
        assessment_version=row["assessment_version"],
        assessed_at=row["assessed_at"],
        persisted=True,
        incident_status=row["incident_status"],
        incident_status_label=label_for_status(row["incident_status"]),
        risk_score=row["risk_score"],
        raw_points=row["raw_points"],
        max_score=row["max_score"],
        risk_level=row["risk_level"],
        recommended_action=row["recommended_action"],
        recommended_action_label=_ACTION_LABELS.get(row["recommended_action"], row["recommended_action"]),
        recommended_action_guidance=row["recommended_action_guidance"],
        trust_break_detected=bool(row["trust_break_detected"]),
        headline=row["headline"],
        explanation=row["explanation"],
        signals=json.loads(row["signals_json"]),
        category_points=json.loads(row["category_points_json"]),
        inputs=json.loads(row["inputs_json"]),
        thresholds=json.loads(row["thresholds_json"]),
        notes=json.loads(row["notes_json"]),
        scoring_method=row["scoring_method"],
        disclaimer=row["disclaimer"],
    )


def risk_summary(conn: sqlite3.Connection) -> dict:
    """Counts of incidents per latest risk level, computed in SQL from persisted assessments."""
    total = conn.execute("SELECT COUNT(*) FROM incidents").fetchone()[0]
    counts = {"LOW": 0, "MEDIUM": 0, "HIGH": 0, "CRITICAL": 0}
    for row in conn.execute("SELECT risk_level, COUNT(*) AS n FROM risk_assessments GROUP BY risk_level"):
        if row["risk_level"] in counts:
            counts[row["risk_level"]] = row["n"]
    assessed = sum(counts.values())
    return {
        "total": total,
        "critical": counts["CRITICAL"], "high": counts["HIGH"], "medium": counts["MEDIUM"], "low": counts["LOW"],
        "assessed": assessed,
        "not_assessed": max(total - assessed, 0),
    }


def _action_labels() -> dict:
    from .services.risk_correlation import rules

    return dict(rules.ACTION_LABELS)


_ACTION_LABELS = _action_labels()
