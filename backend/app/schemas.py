"""Pydantic models: request validation and response shapes."""

from typing import Annotated, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

Channel = Literal["WhatsApp", "Email", "SMS", "Phone call", "Other"]

MAX_AMOUNT = 10_000_000_000  # INR 1,000 crore - sanity ceiling for the MVP
MAX_ATTACHMENT_BYTES = 10 * 1024**3  # 10 GiB - metadata only, nothing is uploaded


# --------------------------------------------------------------------------- #
# Requests
# --------------------------------------------------------------------------- #
class IncidentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sender_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=120)]
    sender_role: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=120)]
    sender_known: bool
    sender_contact: Optional[str] = Field(default=None, max_length=120)

    channel: Channel

    amount: int = Field(gt=0, le=MAX_AMOUNT, description="Whole rupees (INR)")
    beneficiary_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=160)]
    beneficiary_is_new: bool

    message: Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=5000)]

    attachment_name: Optional[str] = Field(default=None, max_length=255)
    attachment_size_bytes: Optional[int] = Field(default=None, ge=0, le=MAX_ATTACHMENT_BYTES)
    attachment_content_type: Optional[str] = Field(default=None, max_length=120)

    @field_validator("sender_contact", "attachment_name", "attachment_content_type", mode="before")
    @classmethod
    def blank_to_none(cls, value):
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value

    @model_validator(mode="after")
    def attachment_details_need_a_name(self):
        has_details = self.attachment_size_bytes is not None or self.attachment_content_type is not None
        if has_details and not self.attachment_name:
            raise ValueError("attachment_name is required when other attachment details are provided")
        return self


class CaseDecisionRequest(BaseModel):
    """An analyst's recorded decision (v0.7.0). A workflow/audit record only: no payment is ever acted on."""

    model_config = ConfigDict(extra="forbid")

    decision: Literal["VERIFIED", "REJECTED"]
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=10, max_length=1000)]
    analyst_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=80)]


# --------------------------------------------------------------------------- #
# Responses
# --------------------------------------------------------------------------- #
class CaseActionOut(BaseModel):
    previous_status: Optional[str] = None
    new_status: str
    new_status_label: str
    decision: str  # CASE_OPENED | VERIFIED | REJECTED
    decision_label: str
    reason: str
    analyst_name: Optional[str] = None
    created_at: str


class CaseStateOut(BaseModel):
    incident_id: int
    reference: str
    workflow_status: Literal["OPEN", "VERIFIED", "REJECTED"]
    workflow_status_label: str
    case_history: list[CaseActionOut]


class CaseDecisionResponse(BaseModel):
    success: bool = True
    data: CaseStateOut


class CaseSummaryOut(BaseModel):
    total: int
    open: int
    verified: int
    rejected: int


class CaseSummaryResponse(BaseModel):
    success: bool = True
    data: CaseSummaryOut


class Sender(BaseModel):
    name: str
    role: str
    known: bool
    contact: Optional[str] = None


class Payment(BaseModel):
    amount: int
    currency: str
    beneficiary_name: str
    beneficiary_is_new: bool


class Attachment(BaseModel):
    name: str
    size_bytes: Optional[int] = None
    content_type: Optional[str] = None


class EvidenceItem(BaseModel):
    label: str
    value: str
    source: str  # "submitted" = taken verbatim from the incident form


class Analysis(BaseModel):
    mode: str  # "placeholder" until real analysis exists
    risk_status: str  # "needs_review" for every incident in this build
    summary: str
    recommended_action: str
    evidence: list[EvidenceItem]


class Incident(BaseModel):
    id: int
    reference: str
    created_at: str
    title: str
    sender: Sender
    channel: str
    payment: Payment
    message: str
    attachment: Optional[Attachment] = None
    analysis: Analysis  # the stored 0.1.0 intake placeholder; NOT the security status once risk_assessment exists
    # v0.6.0: latest persisted TrustBreak risk assessment (null until one has been run).
    risk_assessment: Optional["StoredRiskAssessmentOut"] = None
    incident_status: str = "not_assessed"  # not_assessed | proceed | verify | hold_payment
    incident_status_label: str = "Not assessed"
    # v0.7.0: human case workflow, separate from (and never derived from) the risk assessment above.
    workflow_status: Literal["OPEN", "VERIFIED", "REJECTED"] = "OPEN"
    workflow_status_label: str = "Open"
    case_history: list["CaseActionOut"] = []


class IncidentSummary(BaseModel):
    id: int
    reference: str
    created_at: str
    title: str
    sender_name: str
    sender_role: str
    sender_known: bool
    channel: str
    amount: int
    currency: str
    beneficiary_name: str
    beneficiary_is_new: bool
    has_attachment: bool
    risk_status: str  # legacy placeholder value; use incident_status / risk_level for the real state
    # v0.6.0: latest persisted assessment (all null / "not_assessed" when none exists)
    incident_status: str = "not_assessed"
    incident_status_label: str = "Not assessed"
    risk_level: Optional[Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]] = None
    risk_score: Optional[int] = None
    recommended_action: Optional[Literal["PROCEED", "VERIFY", "HOLD_PAYMENT"]] = None
    recommended_action_label: Optional[str] = None
    trust_break_detected: bool = False
    assessed_at: Optional[str] = None
    # v0.7.0: current human case workflow status (separate concept from risk_level)
    workflow_status: Literal["OPEN", "VERIFIED", "REJECTED"] = "OPEN"
    workflow_status_label: str = "Open"


class IncidentResponse(BaseModel):
    success: bool = True
    data: Incident


class IncidentListMeta(BaseModel):
    total: int
    count: int
    limit: int
    offset: int


class IncidentListResponse(BaseModel):
    success: bool = True
    data: list[IncidentSummary]
    meta: IncidentListMeta


# --------------------------------------------------------------------------- #
# AI message analysis (extraction only - not a risk score or fraud decision)
# --------------------------------------------------------------------------- #
class ExtractedEntityOut(BaseModel):
    type: str
    value: str


class MessageExtractionOut(BaseModel):
    claimed_authority: Optional[str] = None
    requested_action: Optional[str] = None
    payment_amount: Optional[int] = None
    currency: Optional[str] = None
    beneficiary: Optional[str] = None
    urgency_level: str
    secrecy_indicator: bool
    organization: Optional[str] = None
    deadline: Optional[str] = None
    financial_intent: str
    extracted_entities: list[ExtractedEntityOut]
    confidence: float


class MessageAnalysisOut(BaseModel):
    mode: Literal["ai", "mock", "skipped"]  # "mock" = demo rules, NOT an AI model
    model: Optional[str] = None
    extraction: MessageExtractionOut
    notes: list[str]
    fallback_reason: Optional[str] = None
    is_final_decision: bool = False  # always False: extraction only
    provider: Optional[str] = None  # gemini | anthropic | mock - which backend produced the extraction
    requested_provider: Optional[str] = None
    is_fallback: bool = False  # True: an AI provider was wanted but the demo extractor ran


class MessageAnalysisResponse(BaseModel):
    success: bool = True
    data: MessageAnalysisOut


# --------------------------------------------------------------------------- #
# Behaviour baseline & anomaly detection (signals only - not a risk score)
# --------------------------------------------------------------------------- #
class BehaviourAnomalyOut(BaseModel):
    type: Literal["amount", "beneficiary", "channel"]
    code: str
    severity: Literal["medium", "high"]
    message: str


class BehaviourProfileOut(BaseModel):
    employee_id: str
    name: str
    role: str
    normal_channels: list[str]
    known_beneficiaries: list[str]
    typical_min_amount: Optional[int] = None
    typical_max_amount: Optional[int] = None
    historical_payment_count: int
    request_frequency: Optional[str] = None


class BehaviourAnalysisOut(BaseModel):
    employee_id: Optional[str] = None
    profile_found: bool
    amount_anomaly: bool
    amount_deviation: Optional[float] = None
    new_beneficiary: bool
    channel_anomaly: bool
    frequency_anomaly: bool  # always False today: frequency is not evaluated
    checks: dict[str, dict]
    anomalies: list[BehaviourAnomalyOut]
    profile_summary: Optional[BehaviourProfileOut] = None
    notes: list[str]
    is_final_decision: bool = False  # always False: signals only


class BehaviourAnalysisResponse(BaseModel):
    success: bool = True
    data: BehaviourAnalysisOut


# --------------------------------------------------------------------------- #
# Safe attachment analysis (structural evidence only - not a malware verdict)
# --------------------------------------------------------------------------- #
class AttachmentFindingOut(BaseModel):
    type: str
    severity: Literal["high", "medium", "low", "info"]
    message: str
    entry: Optional[str] = None


class AttachmentEntryOut(BaseModel):
    name: str
    extension: str
    category: Literal["executable", "script", "shortcut", "archive", "document", "other"]
    size_bytes: int
    compressed_bytes: int


class AttachmentAnalysisOut(BaseModel):
    file_name: str
    extension: str
    file_type: str  # detected from content, not from the name
    content_type: Optional[str] = None  # as declared by the uploader
    size_bytes: int
    archive: bool
    inspected: bool  # False when an archive could not be (or was not) opened
    file_count: Optional[int] = None
    total_uncompressed_bytes: Optional[int] = None  # declared by the archive, not verified
    entries: list[AttachmentEntryOut]
    extensions: list[str]
    executable_files: list[str]
    contains_executable: bool
    suspicious: bool
    findings: list[AttachmentFindingOut]
    notes: list[str]
    is_final_decision: bool = False  # always False: structural evidence only


class AttachmentAnalysisResponse(BaseModel):
    success: bool = True
    data: AttachmentAnalysisOut


# --------------------------------------------------------------------------- #
# Risk correlation (heuristic risk points from correlated indicators)
# NOT a probability and NOT proof of fraud. The engine only recommends.
# --------------------------------------------------------------------------- #
class RiskSignalOut(BaseModel):
    code: str
    category: str
    source: Literal["message", "behaviour", "attachment"]
    severity: Literal["high", "medium", "low"]
    points: int
    title: str
    message: str
    details: list[str] = []


class RiskInputStatusOut(BaseModel):
    status: Literal["used", "not_provided", "not_evaluated", "unavailable"]
    mode: Optional[str] = None
    detail: str


class RiskThresholdOut(BaseModel):
    min_score: int
    level: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]


class RiskCorrelationOut(BaseModel):
    risk_score: int  # heuristic risk points, capped at max_score
    raw_points: int  # uncapped sum of signal points
    max_score: int
    risk_level: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    recommended_action: Literal["PROCEED", "VERIFY", "HOLD_PAYMENT"]
    recommended_action_label: str
    recommended_action_guidance: str
    trust_break_detected: bool
    headline: str
    explanation: str
    signals: list[RiskSignalOut]
    category_points: dict[str, int]
    inputs: dict[str, RiskInputStatusOut]
    thresholds: list[RiskThresholdOut]
    notes: list[str]
    scoring_method: str
    disclaimer: str
    payment_blocked: bool = False  # always False: the engine never blocks or executes a payment
    is_final_decision: bool = True  # final pipeline output, not proof of fraud


class StoredRiskAssessmentOut(RiskCorrelationOut):
    """A risk assessment as persisted with its incident (v0.6.0)."""

    incident_id: int
    incident_status: Literal["proceed", "verify", "hold_payment"]
    incident_status_label: str
    assessment_version: str
    assessed_at: Optional[str] = None  # None only when persisted is False
    persisted: bool = True  # False: computed but deliberately NOT saved (incomplete evidence)


class RiskCorrelationResponse(BaseModel):
    success: bool = True
    data: StoredRiskAssessmentOut


class RiskSummaryOut(BaseModel):
    total: int
    critical: int
    high: int
    medium: int
    low: int
    assessed: int
    not_assessed: int


class RiskSummaryResponse(BaseModel):
    success: bool = True
    data: RiskSummaryOut


Incident.model_rebuild()
