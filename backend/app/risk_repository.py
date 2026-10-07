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

from .schemas import AssessmentSummaryOut, StoredRiskAssessmentOut
from .services.risk_correlation import rules
from .services.risk_correlation.incident_status import label_for_status, status_for_level

# Source of truth is rules.ENGINE_VERSION. Bump it when weights, groups, caps, thresholds or the stored shape change.
ASSESSMENT_VERSION = rules.ENGINE_VERSION  # Risk Engine 2.0; older stored rows keep the engine_version they were written with

_REQUIRED_KEYS = (
    "risk_score", "raw_points", "max_score", "risk_level", "recommended_action", "recommended_action_guidance",
    "trust_break_detected", "headline", "explanation", "signals", "inputs", "notes", "disclaimer",
)


def check_result_consistent(result: dict) -> None:
    """Refuse to persist an assessment whose parts contradict each other.

    Called by the API layer before `save_risk_assessment` (which stays a plain store so its
    storage-mechanics tests can use hand-built rows).

    The engine is the only authority on score/level/action. This guard recomputes nothing
    from the engine; it only checks that the stored fields agree with the signals and
    thresholds carried in the same result, so a bug or tampering can never write a
    score that its own evidence does not explain. Raises ValueError (nothing is written).
    """
    signals = result["signals"]
    if not isinstance(signals, list):
        raise ValueError("signals must be a list")
    try:
        points = [int(sig["points"]) for sig in signals]
        categories = [sig["category"] for sig in signals]
    except (KeyError, TypeError, ValueError):
        raise ValueError("every signal needs a category and integer points") from None
    # Double-counting guard. Risk Engine 2.0 signals carry a consolidation `group` (one contribution per group);
    # pre-2.0 signals had no group and were limited to one signal per category.
    if all(sig.get("group") for sig in signals) and signals:
        groups = [sig["group"] for sig in signals]
        if len(set(groups)) != len(groups):
            raise ValueError("more than one signal in the same consolidation group (double counting)")
        codes = [sig.get("code") for sig in signals]
        if len(set(codes)) != len(codes):
            raise ValueError("the same signal code appears twice (double counting)")
        for category, cap in rules.CATEGORY_CAPS.items():
            if sum(p for p, c in zip(points, categories) if c == category) > cap:
                raise ValueError(f"{category} points exceed the category cap")
    elif len(set(categories)) != len(categories):
        raise ValueError("more than one signal in the same category (double counting)")
    raw, cap = sum(points), result["max_score"]
    if result["raw_points"] != raw:
        raise ValueError("raw_points does not equal the sum of signal points")
    if result["risk_score"] != min(cap, raw):
        raise ValueError("risk_score does not equal min(max_score, raw_points)")
    cat_points = result.get("category_points")
    if cat_points is not None:
        expected: dict = {}
        for category, pts in zip(categories, points):
            expected[category] = expected.get(category, 0) + pts
        if cat_points != expected:
            raise ValueError("category_points does not match the signals")
    thresholds = result.get("thresholds") or []
    if thresholds:
        level = next((t["level"] for t in sorted(thresholds, key=lambda t: -t["min_score"]) if result["risk_score"] >= t["min_score"]), None)
        if level != result["risk_level"]:
            raise ValueError("risk_level does not match the score and thresholds")
    if rules.ACTION_FOR_LEVEL.get(result["risk_level"]) != result["recommended_action"]:
        raise ValueError("recommended_action does not match the risk level")


class IncidentNotFound(LookupError):
    """Raised when saving an assessment for an incident that does not exist."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


_COLUMNS = (
    "incident_id, version_number, engine_version, assessed_at, risk_score, raw_points, max_score, risk_level, "
    "recommended_action, incident_status, trust_break_detected, headline, explanation, recommended_action_guidance, "
    "signals_json, category_points_json, inputs_json, thresholds_json, notes_json, scoring_method, disclaimer"
)


def save_risk_assessment(
    conn: sqlite3.Connection,
    incident_id: int,
    result: dict,
    assessed_at: Optional[str] = None,
) -> StoredRiskAssessmentOut:
    """Append a NEW immutable assessment (version = previous + 1) and return it as stored.

    Older assessments are never changed. `result` is `RiskCorrelationResult.to_dict()`. Raises
    IncidentNotFound for an unknown incident and ValueError for a malformed result (nothing is written).
    """
    missing = [key for key in _REQUIRED_KEYS if key not in result]
    if missing:
        raise ValueError(f"Risk result is missing: {', '.join(missing)}")
    when = assessed_at or _now()
    with conn:  # one transaction: existence check + insert
        if conn.execute("SELECT 1 FROM incidents WHERE id = ?", (incident_id,)).fetchone() is None:
            raise IncidentNotFound(f"Incident {incident_id} was not found.")
        # The next version number is computed inside the INSERT so concurrent runs cannot take the same one
        # (UNIQUE (incident_id, version_number) is the backstop).
        cursor = conn.execute(
            f"""
            INSERT INTO risk_assessment_history ({_COLUMNS})
            VALUES (?, (SELECT COALESCE(MAX(version_number), 0) + 1 FROM risk_assessment_history WHERE incident_id = ?),
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                incident_id, incident_id, result.get("engine_version") or ASSESSMENT_VERSION, when,
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
        new_id = cursor.lastrowid
    stored = get_assessment_by_id(conn, new_id)
    assert stored is not None  # just written
    return stored


def get_assessment_by_id(conn: sqlite3.Connection, assessment_id: int) -> Optional[StoredRiskAssessmentOut]:
    row = conn.execute("SELECT * FROM risk_assessment_history WHERE id = ?", (assessment_id,)).fetchone()
    return row_to_assessment(row, is_latest=_is_latest(conn, row)) if row else None


def _is_latest(conn: sqlite3.Connection, row: sqlite3.Row) -> bool:
    top = conn.execute("SELECT MAX(version_number) FROM risk_assessment_history WHERE incident_id = ?", (row["incident_id"],)).fetchone()[0]
    return row["version_number"] == top


def get_latest_risk_assessment(conn: sqlite3.Connection, incident_id: int) -> Optional[StoredRiskAssessmentOut]:
    """Latest persisted assessment for the incident, or None (also for an unknown incident)."""
    row = conn.execute("SELECT * FROM latest_risk_assessments WHERE incident_id = ?", (incident_id,)).fetchone()
    return row_to_assessment(row, is_latest=True) if row else None


def get_assessment_version(conn: sqlite3.Connection, incident_id: int, version_number: int) -> Optional[StoredRiskAssessmentOut]:
    row = conn.execute(
        "SELECT * FROM risk_assessment_history WHERE incident_id = ? AND version_number = ?", (incident_id, version_number)
    ).fetchone()
    return row_to_assessment(row, is_latest=_is_latest(conn, row)) if row else None


def list_assessment_history(conn: sqlite3.Connection, incident_id: int) -> list[AssessmentSummaryOut]:
    """Oldest first (v1, v2, ...). Summaries only; use get_assessment_version for the evidence."""
    rows = conn.execute(
        "SELECT * FROM risk_assessment_history WHERE incident_id = ? ORDER BY version_number ASC", (incident_id,)
    ).fetchall()
    last = rows[-1]["version_number"] if rows else None
    return [
        AssessmentSummaryOut(
            assessment_id=r["id"], version_number=r["version_number"], engine_version=r["engine_version"],
            assessed_at=r["assessed_at"], risk_score=r["risk_score"], risk_level=r["risk_level"],
            recommended_action=r["recommended_action"],
            recommended_action_label=_ACTION_LABELS.get(r["recommended_action"], r["recommended_action"]),
            trust_break_detected=bool(r["trust_break_detected"]), signal_count=len(json.loads(r["signals_json"])),
            is_latest=r["version_number"] == last,
        )
        for r in rows
    ]


def latest_assessment_ref(conn: sqlite3.Connection, incident_id: int) -> Optional[tuple]:
    """(assessment_id, version_number) of the latest assessment, or None. Identity only: no scoring data."""
    row = conn.execute("SELECT id, version_number FROM latest_risk_assessments WHERE incident_id = ?", (incident_id,)).fetchone()
    return (row["id"], row["version_number"]) if row else None


def assessment_belongs_to(conn: sqlite3.Connection, incident_id: int, assessment_id: int) -> bool:
    return conn.execute(
        "SELECT 1 FROM risk_assessment_history WHERE id = ? AND incident_id = ?", (assessment_id, incident_id)
    ).fetchone() is not None


def row_to_assessment(row: sqlite3.Row, is_latest: bool = True) -> StoredRiskAssessmentOut:
    return StoredRiskAssessmentOut(
        incident_id=row["incident_id"],
        assessment_id=row["id"],
        version_number=row["version_number"],
        engine_version=row["engine_version"],
        is_latest=is_latest,
        assessment_version=row["engine_version"],  # legacy field (pre-0.8.0 name for the engine version)
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
    for row in conn.execute("SELECT risk_level, COUNT(*) AS n FROM latest_risk_assessments GROUP BY risk_level"):
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
