"""Pydantic models: request validation and response shapes."""

from typing import Annotated, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

from .services.identity import registry as identity_registry

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
    # v0.9.0: stable id of a trusted identity (e.g. "CEO-001"). Optional; when absent the display name is used
    # as a backwards-compatible fallback. An unknown id is rejected, never guessed.
    sender_identity_id: Optional[str] = Field(default=None, max_length=40)

    channel: Channel

    amount: int = Field(gt=0, le=MAX_AMOUNT, description="Whole rupees (INR)")
    beneficiary_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=160)]
    beneficiary_is_new: bool

    message: Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=5000)]

    attachment_name: Optional[str] = Field(default=None, max_length=255)
    attachment_size_bytes: Optional[int] = Field(default=None, ge=0, le=MAX_ATTACHMENT_BYTES)
    attachment_content_type: Optional[str] = Field(default=None, max_length=120)

    # 0.10.0: when the request was received (ISO-8601). Optional: unknown time means NO time/day/velocity checks.
    received_at: Optional[str] = Field(default=None, max_length=40)

    @field_validator("received_at", mode="before")
    @classmethod
    def valid_received_at(cls, value):
        if value is None or (isinstance(value, str) and not value.strip()):
            return None
        from datetime import datetime

        try:
            parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
        except ValueError:
            raise ValueError("received_at must be an ISO-8601 timestamp, e.g. 2026-10-07T12:00:00+05:30")
        return parsed.isoformat() if parsed.tzinfo else parsed.isoformat() + "+00:00"

    @field_validator("sender_contact", "attachment_name", "attachment_content_type", mode="before")
    @classmethod
    def blank_to_none(cls, value):
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value

    @field_validator("sender_identity_id", mode="before")
    @classmethod
    def identity_must_exist(cls, value):
        if isinstance(value, str):
            value = value.strip() or None
        if value is not None and identity_registry.get_identity(value) is None:
            raise ValueError(f"Unknown trusted identity '{value}'.")
        return value.strip().upper() if isinstance(value, str) else value

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
    # v0.8.0: the assessment the analyst was looking at. Optional; when sent it must still be the latest one,
    # otherwise 409 assessment_superseded (a newer assessment exists and has not been reviewed).
    assessment_id: Optional[Annotated[int, Field(ge=1)]] = None
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
    # v0.8.0: the exact assessment a decision was based on (null for CASE_OPENED and for decisions recorded
    # before an assessment existed). Values come from the immutable history row, never from the request.
    assessment_id: Optional[int] = None
    assessment_number: Optional[int] = None
    assessment_risk_score: Optional[int] = None
    assessment_risk_level: Optional[str] = None


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
    # v0.9.0: link to the trusted identity. source: explicit | name_match | none (null id = no identity linked)
    identity_id: Optional[str] = None
    identity_source: str = "none"


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
    received_at: Optional[str] = None  # 0.10.0: when the request was received, if supplied
    title: str
    sender: Sender
    channel: str
    payment: Payment
    message: str
    attachment: Optional[Attachment] = None
    analysis: Analysis  # the stored 0.1.0 intake placeholder; NOT the security status once risk_assessment exists
    # v0.6.0: latest persisted TrustBreak risk assessment (null until one has been run).
    risk_assessment: Optional["StoredRiskAssessmentOut"] = None
    assessment_history: list["AssessmentSummaryOut"] = []  # v0.8.0: v1..vN timeline, oldest first
    incident_status: str = "not_assessed"  # not_assessed | proceed | verify | hold_payment
    incident_status_label: str = "Not assessed"
    # v0.7.0: human case workflow, separate from (and never derived from) the risk assessment above.
    workflow_status: Literal["OPEN", "VERIFIED", "REJECTED"] = "OPEN"
    workflow_status_label: str = "Open"
    case_history: list["CaseActionOut"] = []
    # P2: set for incidents created from a synthetic demo scenario (never a real incident).
    scenario_id: Optional[str] = None
    is_synthetic: bool = False


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
    scenario_id: Optional[str] = None
    is_synthetic: bool = False


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


class SocialSignalOut(BaseModel):
    signal: str
    detected: bool
    evidence: Optional[str] = None
    matched_phrase: Optional[str] = None
    source: Optional[Literal["AI", "rule", "fallback"]] = None  # primary origin
    sources: list[str] = []  # every origin that detected it
    confidence: Optional[Literal["low", "medium", "high"]] = None


class SocialEngineeringOut(BaseModel):
    signals: list[SocialSignalOut]
    detected_count: int
    ai_requested: bool = False
    ai_contributed: bool = False
    rule_source_label: str = "rule"
    notes: list[str] = []
    is_final_decision: bool = False  # always False: evidence only, no score


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
    analysis_state: Literal["ai", "fallback", "mock", "skipped"] = "mock"
    failure_kind: Optional[str] = None  # why the AI path failed, when it did
    social_engineering: Optional[SocialEngineeringOut] = None  # 0.11.0; None when the message was empty


class MessageAnalysisResponse(BaseModel):
    success: bool = True
    data: MessageAnalysisOut


# --------------------------------------------------------------------------- #
# Behaviour baseline & anomaly detection (signals only - not a risk score)
# --------------------------------------------------------------------------- #
class BehaviourAnomalyOut(BaseModel):
    type: Literal["amount", "beneficiary", "channel", "frequency", "velocity", "time", "day", "channel_distribution"]
    code: str
    severity: Literal["medium", "high"]
    message: str
    source: Optional[str] = None  # "synthetic_baseline" for every behaviour signal
    evidence: Optional[dict] = None  # structured numbers behind the message (additive in Baseline 2.0)


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
    historical_activity_count: int = 0
    working_hours: Optional[str] = None


class BehaviourAnalysisOut(BaseModel):
    employee_id: Optional[str] = None
    profile_found: bool
    amount_anomaly: bool
    amount_deviation: Optional[float] = None
    new_beneficiary: bool
    channel_anomaly: bool
    frequency_anomaly: bool  # True only when a synthetic baseline AND prior incidents show an elevated weekly count
    checks: dict[str, dict]
    anomalies: list[BehaviourAnomalyOut]
    profile_summary: Optional[BehaviourProfileOut] = None
    baseline: Optional[dict] = None  # descriptive metrics of the SYNTHETIC history (None = no history)
    baseline_status: str = "NOT_ENOUGH_BASELINE_DATA"
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
    category: str  # Risk Engine 2.0: IDENTITY | COMMUNICATION | FINANCIAL | BENEFICIARY | BEHAVIOUR | SOCIAL_ENGINEERING | ATTACHMENT (pre-2.0 rows: fine-grained names)
    # Where the evidence came from. Pre-2.0 rows used message | behaviour | attachment.
    source: Literal["rule", "synthetic_baseline", "AI", "fallback", "attachment_static", "system", "message", "behaviour", "attachment"]
    severity: Literal["high", "medium", "low"]
    points: int
    title: str
    message: str
    details: list[str] = []
    # Risk Engine 2.0 provenance (all optional so older stored assessments stay readable)
    why: Optional[str] = None
    evidence: Optional[str] = None
    confidence: Optional[Literal["low", "medium", "high"]] = None
    group: Optional[str] = None
    analyzer: Optional[Literal["message", "behaviour", "attachment"]] = None
    base_points: Optional[int] = None
    capped: bool = False
    related_signal_codes: list[str] = []
    corroborating_sources: list[str] = []


class RiskInputStatusOut(BaseModel):
    status: Literal["used", "not_provided", "not_evaluated", "unavailable"]
    mode: Optional[str] = None
    detail: str
    # Message input only: how the extraction was produced (ai | fallback | mock | skipped).
    analysis_state: Optional[str] = None
    provider: Optional[str] = None
    failure_kind: Optional[str] = None


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
    assessment_version: str  # legacy name, equals engine_version
    # v0.8.0 history identity (None when persisted is False)
    assessment_id: Optional[int] = None
    version_number: Optional[int] = None  # 1, 2, 3 ... per incident ("Assessment v3")
    engine_version: Optional[str] = None
    is_latest: Optional[bool] = None
    assessed_at: Optional[str] = None  # None only when persisted is False
    persisted: bool = True  # False: computed but deliberately NOT saved (incomplete evidence)


class AssessmentSummaryOut(BaseModel):
    """One row of the assessment history timeline (no evidence; fetch a version for that)."""

    assessment_id: int
    version_number: int
    engine_version: str
    assessed_at: str
    risk_score: int
    risk_level: str
    recommended_action: str
    recommended_action_label: str
    trust_break_detected: bool
    signal_count: int
    is_latest: bool


class AssessmentHistoryResponse(BaseModel):
    success: bool = True
    data: list[AssessmentSummaryOut]


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


# --------------------------------------------------------------------------- #
# v0.9.0: trusted identities and the evidence / trust graph
# --------------------------------------------------------------------------- #
class TrustedIdentityOut(BaseModel):
    identity_id: str
    employee_id: str
    display_name: str
    role: str
    department: str
    organization: str
    corporate_email: str
    phone_reference: str
    aliases: list[str]
    normal_channels: list[str]
    trusted_channels: list[str]
    restricted_channels: list[str]
    known_beneficiaries: list[str]
    typical_amount_min: int
    typical_amount_max: int
    typical_working_hours: str
    profile_version: int
    created_at: str
    updated_at: str
    active: bool
    profile_status: str


class IdentityListResponse(BaseModel):
    success: Literal[True] = True
    data: list[TrustedIdentityOut]


class IdentityActivityOut(BaseModel):
    incident_count: int
    last_incident_at: Optional[str] = None
    channels_seen: list[str]
    beneficiaries_seen: list[str]
    max_amount_seen: Optional[int] = None


class IdentityDetailOut(BaseModel):
    identity: TrustedIdentityOut
    baseline: dict
    activity: IdentityActivityOut


class IdentityDetailResponse(BaseModel):
    success: Literal[True] = True
    data: IdentityDetailOut


class ComparisonRowOut(BaseModel):
    aspect: str  # channel | beneficiary | amount
    expected: str
    observed: str
    status: Literal["normal", "anomalous", "not_evaluated"]
    detail: Optional[str] = None


class GraphNodeOut(BaseModel):
    id: str
    kind: str
    rank: int
    label: str
    sublabel: Optional[str] = None
    status: Literal["normal", "anomalous", "info", "unknown", "verdict"]
    source: str  # identity_registry | incident | behaviour | risk_assessment
    detail: Optional[str] = None


class GraphEdgeOut(BaseModel):
    source: str
    target: str
    label: Optional[str] = None
    kind: Literal["baseline", "observed", "deviation", "evidence", "verdict"]


class TrustGraphOut(BaseModel):
    incident_id: int
    identity: Optional[TrustedIdentityOut] = None
    identity_source: str
    comparison: list[ComparisonRowOut]
    nodes: list[GraphNodeOut]
    edges: list[GraphEdgeOut]
    assessment_id: Optional[int] = None
    version_number: Optional[int] = None
    risk_level: Optional[str] = None
    trust_break_detected: Optional[bool] = None
    notes: list[str]
    is_final_decision: bool = False


class TrustGraphResponse(BaseModel):
    success: Literal[True] = True
    data: TrustGraphOut


# --------------------------------------------------------------------------- #
# Counterfactual risk analysis (read-only simulations through the same Risk Engine)
# --------------------------------------------------------------------------- #
class CounterfactualAffectedOut(BaseModel):
    code: str
    title: str
    category: str
    points: int


class CounterfactualItemOut(BaseModel):
    id: str
    label: str
    description: str
    affected_signals: list[CounterfactualAffectedOut]
    original_score: int
    new_score: int
    score_delta: int
    original_raw_points: int
    new_raw_points: int
    raw_delta: int
    original_level: str
    new_level: str
    original_action: str
    new_action: str
    level_changed: bool
    trust_break_after: bool
    explanation: str


class CounterfactualCurrentOut(BaseModel):
    risk_score: int
    raw_points: int
    risk_level: str
    recommended_action: str
    trust_break_detected: bool
    assessment_version: Optional[int] = None


class CounterfactualLargestOut(BaseModel):
    id: str
    label: str
    score_delta: int
    raw_delta: int


class CounterfactualDowngradeOut(BaseModel):
    ids: list[str]
    labels: list[str]
    new_score: int
    new_level: str
    new_action: str


class CounterfactualOut(BaseModel):
    available: bool
    reason: Optional[str] = None
    is_simulation: bool = True
    disclaimer: str
    current: Optional[CounterfactualCurrentOut] = None
    counterfactuals: list[CounterfactualItemOut] = []
    largest_reduction: Optional[CounterfactualLargestOut] = None
    smallest_downgrade: Optional[CounterfactualDowngradeOut] = None
    notes: list[str] = []


class CounterfactualResponse(BaseModel):
    success: bool = True
    data: CounterfactualOut


# --------------------------------------------------------------------------- #
# Synthetic demo scenarios (P2)
# --------------------------------------------------------------------------- #
class ScenarioOut(BaseModel):
    id: str
    title: str
    illustrates: str
    synthetic: bool = True
    synthetic_label: str
    sender_name: str
    sender_role: str
    organization: str
    channel: str
    amount: int
    currency: str
    beneficiary_name: str
    beneficiary_is_new: bool
    message: str
    received_at: Optional[str] = None
    attachment_name: Optional[str] = None
    attachment_entries: list[str] = []


class ScenarioListResponse(BaseModel):
    success: bool = True
    data: list[ScenarioOut]


class ScenarioLoadOut(BaseModel):
    scenario_id: str
    incident_id: int
    reference: str
    synthetic: bool = True
    assessment_persisted: bool
    risk_score: Optional[int] = None
    risk_level: Optional[str] = None
    recommended_action: Optional[str] = None


class ScenarioLoadResponse(BaseModel):
    success: bool = True
    data: ScenarioLoadOut


# --------------------------------------------------------------------------- #
# Independent verification workflow (0.13.0) - separate from risk assessment and the final case decision
# --------------------------------------------------------------------------- #
VerificationMethod = Literal["known_corporate_phone", "finance_erp_confirmation", "approved_vendor_directory", "previously_trusted_channel"]


class VerificationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["START", "CONFIRM", "FAIL"]
    method: Optional[VerificationMethod] = None  # required for START; CONFIRM / FAIL use the started method
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=500)]
    analyst_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=80)]


class VerificationMethodOut(BaseModel):
    method: str
    label: str
    description: str
    channels: list[str] = []


class VerificationEventOut(BaseModel):
    event_type: str
    event_label: str
    state_after: str
    state_label: str
    method: Optional[str] = None
    method_label: Optional[str] = None
    reason: str
    analyst_name: str
    created_at: str
    assessment_id: Optional[int] = None
    assessment_number: Optional[int] = None


class VerificationOut(BaseModel):
    incident_id: int
    applicable: bool
    not_applicable_reason: Optional[str] = None
    state: Literal["NOT_STARTED", "IN_PROGRESS", "CONFIRMED", "FAILED"]
    state_label: str
    allowed_actions: list[str]
    recommended_methods: list[VerificationMethodOut]
    warning: str
    events: list[VerificationEventOut]
    note: str


class VerificationResponse(BaseModel):
    success: bool = True
    data: VerificationOut


# --------------------------------------------------------------------------- #
# Forensic timeline (0.13.0): derived only from persisted records
# --------------------------------------------------------------------------- #
class TimelineEventOut(BaseModel):
    seq: int
    timestamp: Optional[str] = None  # None = the source record carries no timestamp (never fabricated)
    event_code: str
    event: str
    source: str
    explanation: str


class TimelineOut(BaseModel):
    incident_id: int
    reference: str
    events: list[TimelineEventOut]
    note: str


class TimelineResponse(BaseModel):
    success: bool = True
    data: TimelineOut


# --------------------------------------------------------------------------- #
# Analyst command-centre dashboard (0.13.0)
# --------------------------------------------------------------------------- #
class DashboardResponse(BaseModel):
    success: bool = True
    data: dict
