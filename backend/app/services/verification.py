"""Independent verification workflow (0.13.0).

Deliberately separate from (1) the system risk assessment, which it never reads for scoring or changes, and
(2) the human final case decision (VERIFIED / REJECTED). It records HOW an analyst tried to confirm a request through
an independent channel and what happened. Nothing is blocked, approved or executed.

Hard rule: verification is never recommended or accepted through the suspicious channel itself. The allowed
methods below do not include "reply to the message"; the "previously trusted channel" suggestions exclude the
channel the request arrived on.
"""

import sqlite3
from datetime import datetime, timezone
from typing import Optional

from .. import repository, risk_repository, verification_repository
from ..errors import AppError, NotFoundError
from .identity import resolve_identity

NOT_STARTED, IN_PROGRESS, CONFIRMED, FAILED = "NOT_STARTED", "IN_PROGRESS", "CONFIRMED", "FAILED"
STATE_LABELS = {NOT_STARTED: "Not started", IN_PROGRESS: "In progress", CONFIRMED: "Confirmed", FAILED: "Failed"}
START, CONFIRM, FAIL = "START", "CONFIRM", "FAIL"
EVENT_FOR_ACTION = {START: ("VERIFICATION_STARTED", IN_PROGRESS), CONFIRM: ("VERIFICATION_CONFIRMED", CONFIRMED),
                    FAIL: ("VERIFICATION_FAILED", FAILED)}
EVENT_LABELS = {"VERIFICATION_STARTED": "Verification started", "VERIFICATION_CONFIRMED": "Verification confirmed",
                "VERIFICATION_FAILED": "Verification failed"}
# allowed (state -> actions). CONFIRMED is terminal; a FAILED attempt may be retried with another method.
TRANSITIONS = {NOT_STARTED: {START}, IN_PROGRESS: {CONFIRM, FAIL}, FAILED: {START}, CONFIRMED: set()}
APPLICABLE_ACTIONS = ("VERIFY", "HOLD_PAYMENT")

METHODS = {
    "known_corporate_phone": ("Known corporate phone",
                              "Call the sender on a phone number from your own records. Never use a number or link from the message."),
    "finance_erp_confirmation": ("Finance / ERP confirmation",
                                 "Check the request and its approvals in the ERP or with the finance team."),
    "approved_vendor_directory": ("Approved vendor directory",
                                  "Confirm the beneficiary and bank details against the approved vendor directory."),
    "previously_trusted_channel": ("Previously trusted communication channel",
                                   "Contact the sender on a channel they have used before - not the channel of this request."),
}
WARNING = ("Do not verify through the suspicious channel itself: do not reply to the message, call a number it gives, "
           "or open its links or attachments.")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _trusted_alternatives(incident) -> list:
    """The sender's trusted channels from the identity registry, minus the channel this request arrived on."""
    identity, _ = resolve_identity(incident.sender.identity_id, incident.sender.name)
    if identity is None:
        return []
    used = (incident.channel or "").strip().casefold()
    return [c for c in identity.trusted_channels if c.strip().casefold() != used]


def _recommended_methods(incident) -> list:
    alternatives = _trusted_alternatives(incident)
    out = []
    for key, (label, description) in METHODS.items():
        item = {"method": key, "label": label, "description": description, "channels": []}
        if key == "previously_trusted_channel":
            item["channels"] = alternatives
            if not alternatives:
                continue  # nothing independent is known for this sender: do not suggest it
        out.append(item)
    return out


def verification_state(conn: sqlite3.Connection, incident_id: int, incident=None) -> dict:
    incident = incident or repository.get_incident(conn, incident_id)
    if incident is None:
        raise NotFoundError(f"Incident {incident_id} was not found.")
    latest = incident.risk_assessment
    applicable = bool(latest and latest.recommended_action in APPLICABLE_ACTIONS)
    state = verification_repository.current_state(conn, incident_id)
    events = [
        {
            "event_type": r["event_type"], "event_label": EVENT_LABELS.get(r["event_type"], r["event_type"]),
            "state_after": r["state_after"], "state_label": STATE_LABELS.get(r["state_after"], r["state_after"]),
            "method": r["method"], "method_label": METHODS[r["method"]][0] if r["method"] in METHODS else None,
            "reason": r["reason"], "analyst_name": r["analyst_name"], "created_at": r["created_at"],
            "assessment_id": r["assessment_id"], "assessment_number": r["assessment_number"],
        }
        for r in verification_repository.list_events(conn, incident_id)
    ]
    if not applicable and not events:
        reason = ("No risk assessment has been run yet." if latest is None
                  else "The latest assessment recommends proceeding, so independent verification is not required.")
    else:
        reason = None
    return {
        "incident_id": incident_id, "applicable": applicable or bool(events), "not_applicable_reason": reason,
        "state": state, "state_label": STATE_LABELS[state], "allowed_actions": sorted(TRANSITIONS.get(state, set())),
        "recommended_methods": _recommended_methods(incident) if (applicable or events) else [],
        "warning": WARNING, "events": events,
        "note": "Verification is recorded separately from the system risk assessment and from the final case decision.",
    }


def record(conn: sqlite3.Connection, incident_id: int, action: str, method: Optional[str], reason: str, analyst_name: str) -> dict:
    incident = repository.get_incident(conn, incident_id)
    if incident is None:
        raise NotFoundError(f"Incident {incident_id} was not found.")
    latest = incident.risk_assessment
    current = verification_repository.current_state(conn, incident_id)
    if latest is None or (latest.recommended_action not in APPLICABLE_ACTIONS and current == NOT_STARTED):
        raise AppError("verification_not_applicable",
                       "Independent verification applies only when the latest assessment recommends verifying or holding the payment.",
                       status_code=409)
    if action not in TRANSITIONS.get(current, set()):
        raise AppError("invalid_verification_transition",
                       f"Cannot {action.lower()} while verification is {STATE_LABELS[current].lower()}.", status_code=409,
                       details=[{"field": "action", "message": f"Current verification state is {current}."}])
    if action == START:
        if method not in METHODS:
            raise AppError("method_required", "Choose an independent verification method.", status_code=422,
                           details=[{"field": "method", "message": "A verification method is required to start."}])
        if method == "previously_trusted_channel" and not _trusted_alternatives(incident):
            raise AppError("no_independent_channel", "No independent trusted channel is known for this sender.", status_code=422,
                           details=[{"field": "method", "message": "Choose another method."}])
    else:  # CONFIRM / FAIL inherit the method recorded when verification started
        started = [e for e in verification_repository.list_events(conn, incident_id) if e["event_type"] == "VERIFICATION_STARTED"]
        method = (started[-1]["method"] if started else None) or method
    event_type, state_after = EVENT_FOR_ACTION[action]
    with conn:
        verification_repository.append_event(
            conn, incident_id=incident_id, event_type=event_type, state_after=state_after, method=method, reason=reason,
            analyst_name=analyst_name, created_at=_now(), assessment_id=latest.assessment_id,
        )
    return verification_state(conn, incident_id)
