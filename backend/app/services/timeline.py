"""Forensic incident timeline (0.13.0): a deterministic, read-only view built ONLY from persisted records.

Sources: the incident row (created / identity / reported received time), the immutable assessment history (each run
carries the analyzers' persisted outcomes in its signals and input statuses), the verification audit trail and the
case-decision audit trail. Nothing is invented: an event takes the timestamp of the record it was derived from, and
an event whose record has no timestamp is shown with `timestamp: null` rather than a made-up time.
Analyzer outputs are not stored as separate rows; their persisted outcome lives inside the assessment of the run in
which they executed, so those events carry that assessment's timestamp and say so.
"""

from datetime import datetime, timezone
from typing import Optional

from .risk_correlation import rules

ACTION_LABEL = {"PROCEED": "PROCEED", "VERIFY": "VERIFY BEFORE PAYING", "HOLD_PAYMENT": "HOLD PAYMENT"}


def _parse(ts: Optional[str]):
    if not ts:
        return None
    try:
        d = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _ev(ts, code, event, source, explanation, order):
    return {"timestamp": ts, "event_code": code, "event": event, "source": source, "explanation": explanation, "_order": order}


def _assessment_events(a: dict, first: bool) -> list:
    ts = a.get("assessed_at")
    tag = f"assessment v{a['version_number']}"
    sigs = a.get("signals") or []
    inputs = a.get("inputs") or {}
    out = []
    msg = inputs.get("message") or {}
    if msg.get("status") == "used":
        state = {"ai": "AI analysis", "fallback": "deterministic fallback (AI unavailable)", "mock": "deterministic demo mode"}.get(msg.get("analysis_state"), "message analysis")
        n_se = sum(1 for s in sigs if s.get("category") == rules.SOCIAL_ENGINEERING)
        out.append(_ev(ts, "MESSAGE_ANALYZED", "Message analyzed", "Message analysis",
                       f"{state}; {n_se} social-engineering signal(s) scored ({tag}).", 10))
    else:
        out.append(_ev(ts, "MESSAGE_ANALYZED", "Message analysis unavailable", "Message analysis", f"{msg.get('detail', 'Not available')} ({tag}).", 10))
    beh = inputs.get("behaviour") or {}
    n_beh = sum(1 for s in sigs if s.get("analyzer") == "behaviour")
    if beh.get("status") == "used":
        out.append(_ev(ts, "BEHAVIOUR_ANALYZED", "Behaviour analyzed", "Synthetic behavioural baseline",
                       f"{n_beh} baseline deviation(s) scored ({tag}).", 20))
    else:
        out.append(_ev(ts, "BEHAVIOUR_ANALYZED", "Behaviour not evaluated", "Synthetic behavioural baseline", f"{beh.get('detail', 'No baseline available')} ({tag}).", 20))
    att = inputs.get("attachment") or {}
    att_sigs = [s for s in sigs if s.get("category") == rules.ATTACHMENT]
    if att.get("status") == "used":
        exe = any(s.get("code") in ("EXECUTABLE_ATTACHMENT", "RISKY_EXTENSION") for s in att_sigs)
        out.append(_ev(ts, "ATTACHMENT_ANALYZED", "Attachment analyzed", "Static attachment analysis",
                       ("Executable content detected (static structural analysis only)" if exe else f"{len(att_sigs)} structural finding(s)")
                       + f" ({tag}).", 30))
    else:
        out.append(_ev(ts, "ATTACHMENT_ANALYZED", "No attachment evidence", "Static attachment analysis",
                       f"No attachment file was analyzed in this run ({tag}).", 30))
    verb = "Risk assessed" if first else "Risk reassessed"
    out.append(_ev(ts, "RISK_ASSESSED" if first else "RISK_REASSESSED", verb, "Risk Engine",
                   f"{a['risk_score']} / {a['risk_level']} (engine {a.get('engine_version')}, {tag}). Prototype heuristic score.", 40))
    out.append(_ev(ts, "RECOMMENDATION", "Recommendation", "Risk Engine",
                   f"{ACTION_LABEL.get(a['recommended_action'], a['recommended_action'])} - decision support, not a block ({tag}).", 50))
    return out


def build_timeline(incident, assessments: list, verification_events: list) -> list:
    """`incident`: Incident model; `assessments`: full assessment dicts, oldest first; `verification_events`: verification_state()['events']."""
    events = [_ev(incident.created_at, "INCIDENT_CREATED", "Incident created", "System",
                  f"{incident.reference} created from the submitted request.", 0)]
    s = incident.sender
    if s.identity_id:
        events.append(_ev(incident.created_at, "IDENTITY_RESOLVED", "Identity resolved", "Trusted identity registry",
                          f"{s.name} / {s.identity_id} ({s.identity_source.replace('_', ' ')}).", 1))
    else:
        events.append(_ev(incident.created_at, "IDENTITY_RESOLVED", "Identity not resolved", "Trusted identity registry",
                          f"{s.name} is not linked to a trusted identity, so no behavioural baseline applies.", 1))
    if incident.received_at:
        events.append(_ev(incident.received_at, "REQUEST_RECEIVED", "Request received (as reported)", "Submitter",
                          "Time supplied with the incident; not independently verified.", 2))
    for i, a in enumerate(assessments):
        events.extend(_assessment_events(a, first=(i == 0)))
    for v in verification_events:
        code = {"VERIFICATION_STARTED": "VERIFICATION_STARTED", "VERIFICATION_CONFIRMED": "VERIFICATION_CONFIRMED",
                "VERIFICATION_FAILED": "VERIFICATION_FAILED"}[v["event_type"]]
        method = f" via {v['method_label']}" if v.get("method_label") else ""
        events.append(_ev(v["created_at"], code, v["event_label"], f"Analyst ({v['analyst_name']})", f"{v['reason']}{method}.", 60))
    for c in incident.case_history:
        if c.decision == "CASE_OPENED":
            events.append(_ev(c.created_at, "CASE_OPENED", "Case opened", "Case workflow", "Opened automatically for human review.", 5))
        else:
            events.append(_ev(c.created_at, "ANALYST_DECISION", f"Analyst decision: {c.new_status}", f"Analyst ({c.analyst_name})",
                              f"{c.reason} (based on assessment v{c.assessment_number})." if c.assessment_number else c.reason, 70))
    far = datetime.max.replace(tzinfo=timezone.utc)
    events.sort(key=lambda e: (_parse(e["timestamp"]) or far, e["_order"]))
    for n, e in enumerate(events, 1):
        e["seq"] = n
        e.pop("_order")
    return events
