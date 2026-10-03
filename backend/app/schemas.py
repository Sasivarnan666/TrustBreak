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


# --------------------------------------------------------------------------- #
# Responses
# --------------------------------------------------------------------------- #
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
    analysis: Analysis


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
    risk_status: str


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


class MessageAnalysisResponse(BaseModel):
    success: bool = True
    data: MessageAnalysisOut
