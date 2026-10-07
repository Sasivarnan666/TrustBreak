"""/api/incidents endpoints. Thin: validation in schemas, SQL in repository."""

import sqlite3
from typing import Optional

from fastapi import APIRouter, Depends, File, Path, Query, UploadFile, status
from fastapi.responses import HTMLResponse

from .. import repository, risk_repository
from ..database import get_db
from ..errors import AppError, NotFoundError
from ..schemas import (
    AssessmentHistoryResponse,
    AttachmentAnalysisOut,
    CaseDecisionRequest,
    CaseDecisionResponse,
    CaseSummaryResponse,
    CounterfactualOut,
    CounterfactualResponse,
    AttachmentAnalysisResponse,
    BehaviourAnalysisOut,
    BehaviourAnalysisResponse,
    IncidentCreate,
    IncidentListMeta,
    IncidentListResponse,
    IncidentResponse,
    MessageAnalysisOut,
    MessageAnalysisResponse,
    RiskCorrelationResponse,
    RiskSummaryOut,
    RiskSummaryResponse,
    StoredRiskAssessmentOut,
    TrustGraphOut,
    TimelineOut,
    TimelineResponse,
    TrustGraphResponse,
    VerificationOut,
    VerificationRequest,
    VerificationResponse,
)
from .. import __version__
from ..services import case_workflow, counterfactual, report, scenarios as scenario_service, timeline, verification
from ..services.evidence_graph import build_trust_graph
from ..services.identity import resolve_identity
from ..services.attachment_analysis import AttachmentError, analyze_attachment
from ..services.attachment_analysis import config as attachment_config
from ..services.behaviour import analyze_incident_behaviour
from ..services.message_analysis import ExtractionError, analyze_message
from ..services.risk_correlation import assess_incident_risk
from ..services.risk_correlation.incident_status import label_for_status, status_for_level

router = APIRouter(prefix="/api/incidents", tags=["incidents"])

SQLITE_MAX_INT = 9_223_372_036_854_775_807


@router.post("", response_model=IncidentResponse, status_code=status.HTTP_201_CREATED)
def create_incident(payload: IncidentCreate, db: sqlite3.Connection = Depends(get_db)):
    incident = repository.create_incident(db, payload)
    return IncidentResponse(data=incident)


@router.get("", response_model=IncidentListResponse)
def list_incidents(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: sqlite3.Connection = Depends(get_db),
):
    items = repository.list_incidents(db, limit=limit, offset=offset)
    total = repository.count_incidents(db)
    return IncidentListResponse(
        data=items,
        meta=IncidentListMeta(total=total, count=len(items), limit=limit, offset=offset),
    )


@router.get("/risk-summary", response_model=RiskSummaryResponse)
def risk_summary(db: sqlite3.Connection = Depends(get_db)):
    """Incident counts per latest persisted risk level (plus not assessed). Nothing is derived from the placeholder."""
    return RiskSummaryResponse(data=RiskSummaryOut(**risk_repository.risk_summary(db)))


@router.get("/case-summary", response_model=CaseSummaryResponse)
def case_summary(db: sqlite3.Connection = Depends(get_db)):
    """Incident counts per current human workflow status (open / verified / rejected), from persisted audit rows."""
    return CaseSummaryResponse(data=case_workflow.case_summary(db))


@router.get("/{incident_id}", response_model=IncidentResponse)
def get_incident(
    incident_id: int = Path(ge=1, le=SQLITE_MAX_INT),
    db: sqlite3.Connection = Depends(get_db),
):
    incident = repository.get_incident(db, incident_id)
    if incident is None:
        raise NotFoundError(f"Incident {incident_id} was not found.")
    return IncidentResponse(data=incident)


@router.get("/{incident_id}/assessments", response_model=AssessmentHistoryResponse)
def list_assessments(incident_id: int, db: sqlite3.Connection = Depends(get_db)):
    """The immutable assessment history, oldest first (v1, v2, ...). Summaries only."""
    if repository.get_incident(db, incident_id) is None:
        raise NotFoundError(f"Incident {incident_id} was not found.")
    return AssessmentHistoryResponse(data=risk_repository.list_assessment_history(db, incident_id))


@router.get("/{incident_id}/assessments/{version_number}", response_model=RiskCorrelationResponse)
def get_assessment(incident_id: int, version_number: int, db: sqlite3.Connection = Depends(get_db)):
    """One historical assessment with its full evidence, exactly as it was stored."""
    if repository.get_incident(db, incident_id) is None:
        raise NotFoundError(f"Incident {incident_id} was not found.")
    stored = risk_repository.get_assessment_version(db, incident_id, version_number)
    if stored is None:
        raise NotFoundError(f"Incident {incident_id} has no assessment v{version_number}.")
    return RiskCorrelationResponse(data=stored)


@router.get("/{incident_id}/counterfactuals", response_model=CounterfactualResponse)
def get_counterfactuals(incident_id: int = Path(ge=1, le=SQLITE_MAX_INT), db: sqlite3.Connection = Depends(get_db)):
    """"What would reduce the risk?" - read-only simulations through the SAME Risk Engine on the latest stored assessment.

    Nothing is persisted, no assessment is appended and the incident is not modified.
    """
    if repository.get_incident(db, incident_id) is None:
        raise NotFoundError(f"Incident {incident_id} was not found.")
    latest = risk_repository.get_latest_risk_assessment(db, incident_id)
    return CounterfactualResponse(data=CounterfactualOut(**counterfactual.analyze(latest.model_dump() if latest else None)))


@router.get("/{incident_id}/verification", response_model=VerificationResponse)
def get_verification(incident_id: int = Path(ge=1, le=SQLITE_MAX_INT), db: sqlite3.Connection = Depends(get_db)):
    """Independent-verification state, recommended methods (never the suspicious channel) and its audit events."""
    return VerificationResponse(data=VerificationOut(**verification.verification_state(db, incident_id)))


@router.post("/{incident_id}/verification", response_model=VerificationResponse)
def record_verification(
    payload: VerificationRequest,
    incident_id: int = Path(ge=1, le=SQLITE_MAX_INT),
    db: sqlite3.Connection = Depends(get_db),
):
    """Append one verification event (START / CONFIRM / FAIL). Never changes the risk assessment or the case decision."""
    state = verification.record(db, incident_id, payload.action, payload.method, payload.reason, payload.analyst_name)
    return VerificationResponse(data=VerificationOut(**state))


@router.get("/{incident_id}/timeline", response_model=TimelineResponse)
def get_timeline(incident_id: int = Path(ge=1, le=SQLITE_MAX_INT), db: sqlite3.Connection = Depends(get_db)):
    """Forensic timeline built only from persisted events (incident, assessment history, verification and case audit rows)."""
    incident = repository.get_incident(db, incident_id)
    if incident is None:
        raise NotFoundError(f"Incident {incident_id} was not found.")
    assessments = [
        risk_repository.get_assessment_version(db, incident_id, h.version_number).model_dump() for h in incident.assessment_history
    ]
    events = timeline.build_timeline(incident, assessments, verification.verification_state(db, incident_id, incident)["events"])
    return TimelineResponse(data=TimelineOut(
        incident_id=incident_id, reference=incident.reference, events=events,
        note="Built only from persisted records. Analyzer events carry the timestamp of the assessment run that recorded them; no time is invented.",
    ))


@router.get("/{incident_id}/report", response_class=HTMLResponse)
def get_report(incident_id: int = Path(ge=1, le=SQLITE_MAX_INT), db: sqlite3.Connection = Depends(get_db)):
    """Printable incident report (self-contained HTML; print or 'Save as PDF' from the browser). Read-only."""
    incident = repository.get_incident(db, incident_id)
    if incident is None:
        raise NotFoundError(f"Incident {incident_id} was not found.")
    latest = incident.risk_assessment
    identity, source = resolve_identity(incident.sender.identity_id, incident.sender.name)
    behaviour = _behaviour_for(db, incident, identity.identity_id if identity else None)
    graph = build_trust_graph(
        incident_id=incident_id, identity=identity, identity_source=source, behaviour=behaviour,
        assessment=latest.model_dump() if latest else None, channel=incident.channel, amount=incident.payment.amount,
        beneficiary=incident.payment.beneficiary_name, attachment_name=incident.attachment.name if incident.attachment else None,
    )
    graph["identity"] = identity.to_dict() if identity else None
    versions = [risk_repository.get_assessment_version(db, incident_id, h.version_number).model_dump() for h in incident.assessment_history]
    ver = verification.verification_state(db, incident_id, incident)
    scenario = scenario_service.get_scenario(incident.scenario_id) if incident.scenario_id else None
    html = report.render_report({
        "incident": incident.model_dump(), "assessment": latest.model_dump() if latest else None, "trust_graph": graph,
        "counterfactuals": counterfactual.analyze(latest.model_dump() if latest else None), "verification": ver,
        "timeline": timeline.build_timeline(incident, versions, ver["events"]),
        "history": [h.model_dump() for h in incident.assessment_history],
        "scenario_archive": list(scenario.attachment_entries) if scenario else [],
        "generated_at": report.now_utc(), "version": __version__,
    })
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})


@router.get("/{incident_id}/trust-graph", response_model=TrustGraphResponse)
def get_trust_graph(incident_id: int = Path(ge=1, le=SQLITE_MAX_INT), db: sqlite3.Connection = Depends(get_db)):
    """Evidence / trust graph and EXPECTED-vs-OBSERVED comparison for one incident.

    Read-only and deterministic: identity baseline + behaviour checks + the latest STORED assessment's signals.
    It runs no AI, scores nothing and writes nothing; the verdict node repeats the stored assessment.
    """
    incident = repository.get_incident(db, incident_id)
    if incident is None:
        raise NotFoundError(f"Incident {incident_id} was not found.")
    identity, source = resolve_identity(incident.sender.identity_id, incident.sender.name)
    behaviour = _behaviour_for(db, incident, identity.identity_id if identity else None)
    assessment = incident.risk_assessment.model_dump() if incident.risk_assessment else None
    graph = build_trust_graph(
        incident_id=incident_id, identity=identity, identity_source=source, behaviour=behaviour, assessment=assessment,
        channel=incident.channel, amount=incident.payment.amount, beneficiary=incident.payment.beneficiary_name,
        attachment_name=incident.attachment.name if incident.attachment else None,
    )
    graph["identity"] = identity.to_dict() if identity else None
    return TrustGraphResponse(data=TrustGraphOut(**graph))


@router.post("/{incident_id}/decision", response_model=CaseDecisionResponse)
def record_case_decision(
    payload: CaseDecisionRequest,
    incident_id: int = Path(ge=1, le=SQLITE_MAX_INT),
    db: sqlite3.Connection = Depends(get_db),
):
    """Record an analyst's VERIFIED / REJECTED decision for the case (workflow + audit record only).

    Appends one immutable audit row and moves the case OPEN -> VERIFIED|REJECTED. It never reads or changes the
    risk assessment, and it never approves, blocks, cancels or executes any payment. A closed case answers
    409 case_already_closed.
    """
    case_workflow.record_decision(db, incident_id, payload.decision, payload.reason, payload.analyst_name, payload.assessment_id)
    return CaseDecisionResponse(data=case_workflow.case_state(db, incident_id, repository.reference_for(incident_id)))


_EXTRACTION_STATUS = {"ai_not_configured": 503, "ai_unavailable": 502, "ai_invalid_response": 502}


@router.post("/{incident_id}/analyze-message", response_model=MessageAnalysisResponse)
def analyze_incident_message(
    incident_id: int = Path(ge=1, le=SQLITE_MAX_INT),
    db: sqlite3.Connection = Depends(get_db),
):
    """Extract entities and financial intent from the incident's message.

    Extraction only - no risk scoring. The result is computed on demand and
    not stored (no schema change).
    """
    incident = repository.get_incident(db, incident_id)
    if incident is None:
        raise NotFoundError(f"Incident {incident_id} was not found.")
    try:
        result = analyze_message(incident.message)
    except ExtractionError as exc:
        raise AppError(
            exc.code,
            exc.message,
            status_code=_EXTRACTION_STATUS.get(exc.code, 502),
            details=[{"failure_kind": exc.failure_kind}] if exc.failure_kind else None,
        )
    return MessageAnalysisResponse(data=MessageAnalysisOut(**result.to_dict()))


def _behaviour_for(db: sqlite3.Connection, incident, identity_id: Optional[str]) -> dict:
    """Behaviour analysis with the incident's recorded time and the identity's earlier incidents (real rows only)."""
    return analyze_incident_behaviour(
        sender_name=incident.sender.name,
        channel=incident.channel,
        amount=incident.payment.amount,
        beneficiary=incident.payment.beneficiary_name,
        sender_identity_id=identity_id,
        timestamp=incident.received_at,
        recent_request_times=repository.list_prior_request_times(db, identity_id, incident.id),
    )


@router.post("/{incident_id}/analyze-behaviour", response_model=BehaviourAnalysisResponse)
def analyze_incident_behaviour_endpoint(
    incident_id: int = Path(ge=1, le=SQLITE_MAX_INT),
    db: sqlite3.Connection = Depends(get_db),
):
    """Compare the request with the sender's synthetic behaviour profile.

    Deterministic anomaly signals only - no risk score or fraud verdict.
    Computed on demand and not stored (no schema change).
    """
    incident = repository.get_incident(db, incident_id)
    if incident is None:
        raise NotFoundError(f"Incident {incident_id} was not found.")
    result = _behaviour_for(db, incident, incident.sender.identity_id)
    return BehaviourAnalysisResponse(data=BehaviourAnalysisOut(**result))


@router.post("/{incident_id}/analyze-attachment", response_model=AttachmentAnalysisResponse)
async def analyze_incident_attachment(
    incident_id: int = Path(ge=1, le=SQLITE_MAX_INT),
    file: UploadFile | None = File(default=None),
    db: sqlite3.Connection = Depends(get_db),
):
    """Statically inspect the uploaded copy of the incident's attachment.

    The incident stores attachment metadata only, so the file is sent with this
    request as multipart field `file`. It is analyzed in memory and discarded:
    never executed, extracted or stored. Structural evidence only - no risk score.
    """
    incident = repository.get_incident(db, incident_id)
    if incident is None:
        raise NotFoundError(f"Incident {incident_id} was not found.")
    if incident.attachment is None:
        raise AppError("attachment_missing", "This incident has no attachment to analyze.", status_code=400)
    if file is None:
        raise AppError("attachment_missing", "No file was uploaded. Send the attachment as multipart field 'file'.",
                       status_code=400)

    limit = attachment_config.max_upload_bytes()
    data = await file.read(limit + 1)  # bounded read: never buffers more than limit + 1 bytes
    try:
        result = analyze_attachment(file.filename or "", data, file.content_type)
    except AttachmentError as exc:
        raise AppError(exc.code, exc.message, status_code=exc.status_code)

    if file.filename and incident.attachment.name and _clean_name(file.filename) != incident.attachment.name:
        result["notes"].insert(0, "The uploaded file name differs from the attachment name recorded on the incident.")
    return AttachmentAnalysisResponse(data=AttachmentAnalysisOut(**result))


@router.post("/{incident_id}/analyze-risk", response_model=RiskCorrelationResponse)
async def analyze_incident_risk(
    incident_id: int = Path(ge=1, le=SQLITE_MAX_INT),
    file: UploadFile | None = File(default=None),
    db: sqlite3.Connection = Depends(get_db),
):
    """Correlate message, behaviour and (optionally) attachment evidence, then persist the result.

    Deterministic heuristic risk points - not a probability and not proof of
    fraud. The incident stores attachment metadata only, so attachment evidence
    is included only when the file is sent as optional multipart field `file`
    (analyzed in memory, never executed, extracted or stored). The structured
    result replaces the incident's latest stored assessment and is returned as
    persisted. If message analysis was unavailable the evidence is incomplete:
    the computed result is returned (`persisted: false`) but NOT saved, and any
    earlier stored assessment is left unchanged. Nothing is blocked or
    executed: the response only recommends an action.
    """
    incident = repository.get_incident(db, incident_id)
    if incident is None:
        raise NotFoundError(f"Incident {incident_id} was not found.")

    attachment_file = None
    if file is not None:
        data = await file.read(attachment_config.max_upload_bytes() + 1)  # bounded read
        attachment_file = (file.filename or "", data, file.content_type)
    try:
        result = assess_incident_risk(incident, attachment_file)
    except AttachmentError as exc:
        raise AppError(exc.code, exc.message, status_code=exc.status_code)
    payload = result.to_dict()  # structured output only; the uploaded bytes are not part of it

    if payload["inputs"].get("message", {}).get("status") == "unavailable":
        payload["notes"] = list(payload["notes"]) + [
            "This assessment was not saved because message analysis was unavailable (incomplete evidence). "
            "Any earlier stored assessment is unchanged."
        ]
        return RiskCorrelationResponse(
            data=StoredRiskAssessmentOut(
                **payload,
                incident_id=incident_id,
                incident_status=status_for_level(payload["risk_level"]),
                incident_status_label=label_for_status(status_for_level(payload["risk_level"])),
                assessment_version=risk_repository.ASSESSMENT_VERSION,
                assessed_at=None,
                persisted=False,
            )
        )
    try:
        risk_repository.check_result_consistent(payload)  # defence in depth: never persist a self-contradicting result
        stored = risk_repository.save_risk_assessment(db, incident_id, payload)
    except risk_repository.IncidentNotFound:
        raise NotFoundError(f"Incident {incident_id} was not found.")
    return RiskCorrelationResponse(data=stored)


def _clean_name(name: str) -> str:
    return name.replace("\\", "/").rsplit("/", 1)[-1]
