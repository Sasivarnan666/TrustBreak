"""Analyst command-centre aggregates (0.13.0). Read-only; every number is counted from persisted rows."""

import json
import sqlite3

from .. import __version__, case_repository, config, risk_repository, verification_repository
from .risk_correlation import rules

TRUST_CATEGORIES = (rules.COMMUNICATION, rules.FINANCIAL, rules.BENEFICIARY, rules.BEHAVIOUR, rules.SOCIAL_ENGINEERING, rules.ATTACHMENT)


def _ai_status(conn: sqlite3.Connection) -> dict:
    """Honest AI state: configuration + the message-analysis state of the most recent persisted assessment."""
    mode, provider = config.get_ai_mode(), config.get_ai_provider()
    has_key = bool(config.get_ai_api_key(provider))
    row = conn.execute("SELECT inputs_json FROM risk_assessment_history ORDER BY id DESC LIMIT 1").fetchone()
    last = None
    if row:
        last = (json.loads(row["inputs_json"]).get("message") or {}).get("analysis_state")
    if mode == "mock" or provider == "mock" or not has_key:
        state, label = "fallback", "AI unavailable — deterministic fallback active"
    elif last == "ai":
        state, label = "ai", "AI analysis active (last extraction used the model)"
    elif last in ("fallback", "mock"):
        state, label = "fallback", "AI unavailable — deterministic fallback active"
    else:
        state, label = "configured", "AI configured — not yet exercised in this database"
    return {"state": state, "label": label, "provider_configured": has_key and mode != "mock" and provider != "mock",
            "last_extraction_state": last}


def build_dashboard(conn: sqlite3.Connection) -> dict:
    risk = risk_repository.risk_summary(conn)
    case = case_repository.case_summary(conn)
    rows = conn.execute(
        f"""
        SELECT i.id, i.title, i.sender_name, i.sender_identity_id, i.amount, i.currency, i.scenario_id,
               r.risk_score, r.risk_level, r.recommended_action, r.trust_break_detected, r.assessed_at, r.version_number,
               r.category_points_json,
               {case_repository.STATUS_SQL} AS workflow_status,
               COALESCE((SELECT state_after FROM verification_events v WHERE v.incident_id = i.id ORDER BY v.id DESC LIMIT 1), 'NOT_STARTED') AS verification_state
        FROM incidents i JOIN latest_risk_assessments r ON r.incident_id = i.id
        ORDER BY r.risk_score DESC, i.id DESC
        """
    ).fetchall()
    categories = {c: 0 for c in rules.CATEGORIES}
    items = []
    for r in rows:
        points = json.loads(r["category_points_json"] or "{}")
        # A LOW assessment (e.g. a routine payment instruction) is not a broken-trust finding: it counts no dimensions.
        violated = [c for c in rules.CATEGORIES if points.get(c, 0) > 0] if r["risk_level"] != rules.LOW else []
        for c in violated:
            categories[c] += 1
        items.append({
            "incident_id": r["id"], "reference": f"TB-{r['id']:04d}", "title": r["title"], "identity_name": r["sender_name"],
            "identity_id": r["sender_identity_id"], "amount": r["amount"], "currency": r["currency"],
            "risk_score": r["risk_score"], "risk_level": r["risk_level"], "recommended_action": r["recommended_action"],
            "trust_break_detected": bool(r["trust_break_detected"]), "trust_dimensions": len(violated),
            "workflow_status": r["workflow_status"], "verification_state": r["verification_state"],
            "assessed_at": r["assessed_at"], "is_synthetic": bool(r["scenario_id"]),
        })
    active = [i for i in items if i["risk_level"] in ("HIGH", "CRITICAL") and i["workflow_status"] == "OPEN"][:10]
    recent_critical = sorted((i for i in items if i["risk_level"] == "CRITICAL"), key=lambda i: i["assessed_at"], reverse=True)[:5]
    ai = _ai_status(conn)
    return {
        "kpis": {"critical": risk["critical"], "high": risk["high"], "open_cases": case["open"], "verified": case["verified"],
                 "rejected": case["rejected"], "total_incidents": risk["total"], "not_assessed": risk["not_assessed"]},
        "risk_distribution": {"critical": risk["critical"], "high": risk["high"], "medium": risk["medium"], "low": risk["low"],
                              "assessed": risk["assessed"]},
        "trust_break_categories": [{"category": c, "label": rules.CATEGORY_LABELS[c], "incidents": categories[c]}
                                   for c in TRUST_CATEGORIES],
        "active_high_risk": active, "recent_critical": recent_critical,
        "verification": verification_repository.summary(conn),
        "system_status": {
            "backend": {"status": "ok", "version": __version__},
            "risk_engine": {"status": "ok", "engine_version": rules.ENGINE_VERSION, "mode": "deterministic prototype heuristics"},
            "ai_extraction": ai,
            "attachment_analyzer": {"status": "ok", "mode": "static structural analysis only; nothing is executed"},
        },
        "note": "Counts come from persisted incidents and their latest risk assessments. Scores are prototype heuristics, not probabilities.",
    }
