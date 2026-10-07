"""Strict schema for the structured result of message analysis.

Standard library only, so the core service can be tested without any web
dependency. Anything coming from an AI model (untrusted) must pass through
`validate_extraction` before the rest of the application sees it.

This result is *extracted information*. It is not a risk score and not a
fraud decision - `MessageAnalysis.is_final_decision` is always False.
"""

import math
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

URGENCY_LEVELS = ("none", "low", "medium", "high")
FINANCIAL_INTENTS = (
    "payment_transfer",
    "invoice_payment",
    "gift_card_purchase",
    "credential_or_otp_request",
    "bank_detail_change",
    "other_financial",
    "none",
)
ENTITY_TYPES = ("person", "role", "organization", "money", "beneficiary", "deadline", "url", "email")

EXTRACTION_KEYS = (
    "claimed_authority",
    "requested_action",
    "payment_amount",
    "currency",
    "beneficiary",
    "urgency_level",
    "secrecy_indicator",
    "organization",
    "deadline",
    "financial_intent",
    "extracted_entities",
    "confidence",
)

MAX_TEXT_LEN = 200
MAX_ENTITIES = 25
MAX_AMOUNT = 10_000_000_000  # same sanity ceiling as the incident form

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_CURRENCY = re.compile(r"^[A-Z]{3}$")


class ExtractionValidationError(ValueError):
    """The extraction does not match the schema."""


@dataclass(frozen=True)
class ExtractedEntity:
    type: str
    value: str


@dataclass(frozen=True)
class MessageExtraction:
    claimed_authority: Optional[str]
    requested_action: Optional[str]
    payment_amount: Optional[int]
    currency: Optional[str]
    beneficiary: Optional[str]
    urgency_level: str
    secrecy_indicator: bool
    organization: Optional[str]
    deadline: Optional[str]
    financial_intent: str
    extracted_entities: tuple = ()
    confidence: float = 0.0


@dataclass(frozen=True)
class MessageAnalysis:
    """Extraction plus honest provenance."""

    mode: str  # "ai" | "mock" | "skipped"
    model: Optional[str]  # AI model name; None unless mode == "ai"
    extraction: MessageExtraction
    notes: list = field(default_factory=list)
    fallback_reason: Optional[str] = None  # why mock was used instead of AI
    is_final_decision: bool = False  # extraction only - never a fraud verdict
    # Provenance (added with the provider adapter; the extraction schema is unchanged):
    provider: Optional[str] = None  # provider that produced `extraction`: gemini | anthropic | mock | None
    requested_provider: Optional[str] = None  # provider the configuration asked for
    is_fallback: bool = False  # True when an AI provider was wanted but the demo extractor was used
    # Four user-visible states (additive): ai | fallback | mock | skipped. ("unavailable" is an
    # error response in `ai` mode or a risk-input status, never a successful extraction.)
    analysis_state: Optional[str] = None  # derived from mode/is_fallback when not given
    failure_kind: Optional[str] = None  # why the AI path failed (FAILURE_KINDS); None when it did not
    # 0.11.0: structured social-engineering evidence (see social_engineering.py); None when nothing was analyzed.
    social_engineering: Optional[dict] = None

    def __post_init__(self) -> None:
        if self.analysis_state is None:  # frozen dataclass: derive once via object.__setattr__
            if self.mode == "ai":
                state = "ai"
            elif self.mode == "skipped":
                state = "skipped"
            else:
                state = "fallback" if self.is_fallback else "mock"
            object.__setattr__(self, "analysis_state", state)

    def to_dict(self) -> dict:
        return asdict(self)


def empty_extraction() -> MessageExtraction:
    return MessageExtraction(
        claimed_authority=None,
        requested_action=None,
        payment_amount=None,
        currency=None,
        beneficiary=None,
        urgency_level="none",
        secrecy_indicator=False,
        organization=None,
        deadline=None,
        financial_intent="none",
        extracted_entities=(),
        confidence=0.0,
    )


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #
def _text(value: Any, name: str) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ExtractionValidationError(f"{name} must be a string or null")
    cleaned = value.strip()
    if not cleaned:
        return None
    if len(cleaned) > MAX_TEXT_LEN:
        raise ExtractionValidationError(f"{name} is longer than {MAX_TEXT_LEN} characters")
    if _CONTROL_CHARS.search(cleaned):
        raise ExtractionValidationError(f"{name} contains control characters")
    return cleaned


def _number(value: Any, name: str) -> float:
    # bool is a subclass of int in Python - never accept it as a number.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ExtractionValidationError(f"{name} must be a number")
    if isinstance(value, float) and not math.isfinite(value):
        raise ExtractionValidationError(f"{name} must be finite")
    return value


def _amount(value: Any) -> Optional[int]:
    if value is None:
        return None
    number = _number(value, "payment_amount")
    if number != int(number):
        raise ExtractionValidationError("payment_amount must be a whole number")
    number = int(number)
    if not 0 < number <= MAX_AMOUNT:
        raise ExtractionValidationError("payment_amount is out of range")
    return number


def _entities(value: Any) -> tuple:
    if not isinstance(value, list):
        raise ExtractionValidationError("extracted_entities must be a list")
    if len(value) > MAX_ENTITIES:
        raise ExtractionValidationError(f"extracted_entities has more than {MAX_ENTITIES} items")
    entities = []
    for item in value:
        if not isinstance(item, dict) or set(item) != {"type", "value"}:
            raise ExtractionValidationError("each entity must have exactly 'type' and 'value'")
        if item["type"] not in ENTITY_TYPES:
            raise ExtractionValidationError("unknown entity type")
        entity_value = _text(item["value"], "entity value")
        if entity_value is None:
            raise ExtractionValidationError("entity value must not be empty")
        entities.append(ExtractedEntity(type=item["type"], value=entity_value))
    return tuple(entities)


def validate_extraction(raw: Any) -> MessageExtraction:
    """Validate an untrusted mapping against the strict schema.

    Unknown keys, missing keys, wrong types and out-of-range values are all
    rejected with `ExtractionValidationError`.
    """
    if not isinstance(raw, dict):
        raise ExtractionValidationError("extraction must be a JSON object")
    keys = set(raw)
    missing = [k for k in EXTRACTION_KEYS if k not in keys]
    unknown = sorted(str(k) for k in keys - set(EXTRACTION_KEYS))
    if missing:
        raise ExtractionValidationError(f"missing fields: {', '.join(missing)}")
    if unknown:
        raise ExtractionValidationError(f"unknown fields: {', '.join(unknown)}")

    currency = _text(raw["currency"], "currency")
    if currency is not None and not _CURRENCY.match(currency):
        raise ExtractionValidationError("currency must be a 3-letter uppercase code")

    if raw["urgency_level"] not in URGENCY_LEVELS:
        raise ExtractionValidationError("urgency_level is not an allowed value")
    if raw["financial_intent"] not in FINANCIAL_INTENTS:
        raise ExtractionValidationError("financial_intent is not an allowed value")
    if not isinstance(raw["secrecy_indicator"], bool):
        raise ExtractionValidationError("secrecy_indicator must be true or false")

    confidence = _number(raw["confidence"], "confidence")
    if not 0 <= confidence <= 1:
        raise ExtractionValidationError("confidence must be between 0 and 1")

    return MessageExtraction(
        claimed_authority=_text(raw["claimed_authority"], "claimed_authority"),
        requested_action=_text(raw["requested_action"], "requested_action"),
        payment_amount=_amount(raw["payment_amount"]),
        currency=currency,
        beneficiary=_text(raw["beneficiary"], "beneficiary"),
        urgency_level=raw["urgency_level"],
        secrecy_indicator=raw["secrecy_indicator"],
        organization=_text(raw["organization"], "organization"),
        deadline=_text(raw["deadline"], "deadline"),
        financial_intent=raw["financial_intent"],
        extracted_entities=_entities(raw["extracted_entities"]),
        confidence=round(float(confidence), 4),
    )


# --------------------------------------------------------------------------- #
# JSON Schema for provider-side structured output (derived from the constants
# above so it cannot drift from `validate_extraction`, which stays authoritative)
# --------------------------------------------------------------------------- #
SOCIAL_SIGNALS_KEY = "social_engineering_signals"  # optional model-reply key, validated separately (see social_engineering.py)


def response_json_schema() -> dict:
    """Provider-side schema = the 12-field extraction schema plus the OPTIONAL social-engineering indicator list.

    `extraction_json_schema()` is unchanged and `validate_extraction` still rejects unknown keys; the optional key is
    removed from the reply before extraction validation and validated on its own.
    """
    from .social_engineering import CONFIDENCE_LEVELS, MAX_AI_SIGNALS, SIGNALS

    schema = extraction_json_schema()
    schema["properties"][SOCIAL_SIGNALS_KEY] = {
        "type": "array",
        "maxItems": MAX_AI_SIGNALS,
        "items": {
            "type": "object",
            "properties": {
                "signal": {"type": "string", "enum": list(SIGNALS)},
                "evidence": {"type": "string", "maxLength": MAX_TEXT_LEN},
                "confidence": {"type": "string", "enum": list(CONFIDENCE_LEVELS)},
            },
            "required": ["signal", "evidence", "confidence"],
            "additionalProperties": False,
        },
    }
    return schema


def extraction_json_schema() -> dict:
    nullable_text = {"type": ["string", "null"], "maxLength": MAX_TEXT_LEN}
    return {
        "type": "object",
        "properties": {
            "claimed_authority": nullable_text,
            "requested_action": nullable_text,
            "payment_amount": {"type": ["integer", "null"], "minimum": 1, "maximum": MAX_AMOUNT},
            "currency": {"type": ["string", "null"], "pattern": "^[A-Z]{3}$"},
            "beneficiary": nullable_text,
            "urgency_level": {"type": "string", "enum": list(URGENCY_LEVELS)},
            "secrecy_indicator": {"type": "boolean"},
            "organization": nullable_text,
            "deadline": nullable_text,
            "financial_intent": {"type": "string", "enum": list(FINANCIAL_INTENTS)},
            "extracted_entities": {
                "type": "array",
                "maxItems": MAX_ENTITIES,
                "items": {
                    "type": "object",
                    "properties": {
                        "type": {"type": "string", "enum": list(ENTITY_TYPES)},
                        "value": {"type": "string", "maxLength": MAX_TEXT_LEN},
                    },
                    "required": ["type", "value"],
                    "additionalProperties": False,
                },
            },
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        },
        "required": list(EXTRACTION_KEYS),
        "additionalProperties": False,
    }
