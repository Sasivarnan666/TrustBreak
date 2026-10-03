"""/api/incidents endpoints. Thin: validation in schemas, SQL in repository."""

import sqlite3

from fastapi import APIRouter, Depends, File, Path, Query, UploadFile, status

from .. import repository, risk_repository
from ..database import get_db
from ..errors import AppError, NotFoundError
from ..schemas import (
    AttachmentAnalysisOut,
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
)
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


@router.get("/{incident_id}", response_model=IncidentResponse)
def get_incident(
    incident_id: int = Path(ge=1, le=SQLITE_MAX_INT),
    db: sqlite3.Connection = Depends(get_db),
):
    incident = repository.get_incident(db, incident_id)
    if incident is None:
        raise NotFoundError(f"Incident {incident_id} was not found.")
    return IncidentResponse(data=incident)


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
        raise AppError(exc.code, exc.message, status_code=_EXTRACTION_STATUS.get(exc.code, 502))
    return MessageAnalysisResponse(data=MessageAnalysisOut(**result.to_dict()))


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
    result = analyze_incident_behaviour(
        sender_name=incident.sender.name,
        channel=incident.channel,
        amount=incident.payment.amount,
        beneficiary=incident.payment.beneficiary_name,
    )
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
        stored = risk_repository.save_risk_assessment(db, incident_id, payload)
    except risk_repository.IncidentNotFound:
        raise NotFoundError(f"Incident {incident_id} was not found.")
    return RiskCorrelationResponse(data=stored)


def _clean_name(name: str) -> str:
    return name.replace("\\", "/").rsplit("/", 1)[-1]
