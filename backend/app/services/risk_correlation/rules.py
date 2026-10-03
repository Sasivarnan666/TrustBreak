"""Transparent, deterministic scoring rules for the risk correlation engine.

EVERYTHING HERE IS PROTOTYPE HEURISTIC SCORING.

* The weights are hand-chosen "risk points". They are NOT probabilities and are
  not calibrated against real fraud data. 85 points means "85 risk points from
  correlated indicators", never "85% chance of fraud".
* The thresholds are prototype values. They have not been scientifically
  validated.
* Each CATEGORY below contributes at most its weight, once, however many raw
  findings map to it (two executables in one archive are still one
  `executable_content` signal).

Stdlib only; no imports from the individual analysis modules.
"""

from dataclasses import dataclass

MAX_SCORE = 100  # displayed score is capped here; the uncapped sum is reported as `raw_points`

# --- sources ---------------------------------------------------------------- #
SOURCE_MESSAGE = "message"
SOURCE_BEHAVIOUR = "behaviour"
SOURCE_ATTACHMENT = "attachment"

# --- levels and actions ----------------------------------------------------- #
LOW, MEDIUM, HIGH, CRITICAL = "LOW", "MEDIUM", "HIGH", "CRITICAL"
PROCEED, VERIFY, HOLD_PAYMENT = "PROCEED", "VERIFY", "HOLD_PAYMENT"

# (lowest score of the band, level), highest band first. Prototype thresholds.
LEVEL_THRESHOLDS = ((70, CRITICAL), (40, HIGH), (20, MEDIUM), (0, LOW))

ACTION_FOR_LEVEL = {LOW: PROCEED, MEDIUM: VERIFY, HIGH: VERIFY, CRITICAL: HOLD_PAYMENT}

ACTION_LABELS = {PROCEED: "Proceed", VERIFY: "Verify before paying", HOLD_PAYMENT: "Hold payment"}
ACTION_GUIDANCE = {
    PROCEED: "No strong indicators were found in the available evidence. Follow your normal approval process.",
    VERIFY: "Verify the request using an independent trusted communication channel before any funds are released.",
    HOLD_PAYMENT: (
        "Do not release funds yet. Verify the request using an independent trusted communication channel "
        "(a phone number from your own records, not the one used in this request)."
    ),
}

# Severity is derived from the points so the two can never disagree.
HIGH_SEVERITY_MIN_POINTS = 20
MEDIUM_SEVERITY_MIN_POINTS = 10


def severity_for_points(points: int) -> str:
    if points >= HIGH_SEVERITY_MIN_POINTS:
        return "high"
    if points >= MEDIUM_SEVERITY_MIN_POINTS:
        return "medium"
    return "low"


@dataclass(frozen=True)
class SignalRule:
    code: str
    category: str
    source: str
    points: int
    title: str
    default_message: str


# One rule per category. The order is the display/tie-break order.
RULES = (
    # message
    SignalRule("HIGH_URGENCY", "urgency", SOURCE_MESSAGE, 10, "High urgency",
               "The message contains urgent payment language."),
    SignalRule("SECRECY_REQUESTED", "secrecy", SOURCE_MESSAGE, 10, "Secrecy requested",
               "The message asks for the request to be kept confidential."),
    SignalRule("FINANCIAL_TRANSFER_INTENT", "financial_intent", SOURCE_MESSAGE, 10, "Financial transfer request",
               "The message asks for a financial transfer or payment-detail change."),
    SignalRule("AUTHORITY_MISMATCH", "authority_mismatch", SOURCE_MESSAGE, 15, "Claimed authority mismatch",
               "The authority claimed in the message differs from the sender's recorded role."),
    # behaviour
    SignalRule("AMOUNT_ABOVE_BASELINE", "payment_anomaly", SOURCE_BEHAVIOUR, 20, "Amount above baseline",
               "Requested amount is above the sender's normal maximum."),
    SignalRule("NEW_BENEFICIARY", "beneficiary_anomaly", SOURCE_BEHAVIOUR, 20, "New beneficiary",
               "The beneficiary is not present in the sender's known beneficiary profile."),
    SignalRule("UNUSUAL_CHANNEL", "channel_anomaly", SOURCE_BEHAVIOUR, 15, "Unusual channel",
               "The communication channel differs from the sender's normal channels."),
    # attachment
    SignalRule("EXECUTABLE_ATTACHMENT", "executable_content", SOURCE_ATTACHMENT, 25, "Executable content",
               "The uploaded file contains executable content."),
    SignalRule("DOCUMENT_WITH_EXECUTABLE", "document_deception", SOURCE_ATTACHMENT, 20, "Document-looking file with executable",
               "The file looks like a document or statement but contains executable content."),
    SignalRule("DOUBLE_EXTENSION", "deceptive_filename", SOURCE_ATTACHMENT, 15, "Double extension",
               "A file name uses a document-looking extension followed by an executable extension."),
    SignalRule("PATH_TRAVERSAL", "path_traversal", SOURCE_ATTACHMENT, 15, "Path traversal indicator",
               "An archive entry path points outside the archive folder."),
    SignalRule("OTHER_HIGH_SEVERITY_ATTACHMENT_FINDING", "suspicious_attachment", SOURCE_ATTACHMENT, 10,
               "Other high-severity attachment finding",
               "Attachment analysis reported another high-severity structural finding."),
)
RULES_BY_CODE = {r.code: r for r in RULES}
RULES_BY_CATEGORY = {r.category: r for r in RULES}

# Categories that say "this request does not fit the trusted context".
CONTEXT_INCONSISTENCY_CATEGORIES = frozenset(
    {"payment_anomaly", "beneficiary_anomaly", "channel_anomaly", "authority_mismatch"}
)

# --- how upstream outputs map onto categories ------------------------------- #
# Message analysis `financial_intent` values that count as a funds-transfer request.
FINANCIAL_TRANSFER_INTENTS = frozenset(
    {"payment_transfer", "invoice_payment", "gift_card_purchase", "bank_detail_change", "other_financial"}
)
HIGH_URGENCY_LEVELS = frozenset({"high"})  # "medium" urgency earns no points (prototype choice)

# Attachment finding types with a dedicated category; any OTHER finding rated
# "high" falls into suspicious_attachment (once).
EXECUTABLE_FINDING_TYPES = frozenset({"executable_inside_archive", "executable_file"})
DOCUMENT_DECEPTION_FINDING_TYPES = frozenset({"document_with_executable_content"})
DOUBLE_EXTENSION_FINDING_TYPES = frozenset({"double_extension"})
PATH_TRAVERSAL_FINDING_TYPES = frozenset({"path_traversal"})
DEDICATED_FINDING_TYPES = (
    EXECUTABLE_FINDING_TYPES
    | DOCUMENT_DECEPTION_FINDING_TYPES
    | DOUBLE_EXTENSION_FINDING_TYPES
    | PATH_TRAVERSAL_FINDING_TYPES
)

# Titles used to compare a claimed authority with a recorded role. Only a clear
# match of BOTH sides to DIFFERENT canonical roles counts as a mismatch.
ROLE_ALIASES = {
    "ceo": ("chief executive officer", "chief executive", "ceo"),
    "cfo": ("chief financial officer", "finance head", "head of finance", "cfo"),
    "coo": ("chief operating officer", "coo"),
    "cto": ("chief technology officer", "cto"),
    "md": ("managing director", "md"),
    "chairperson": ("chairperson", "chairman", "chairwoman"),
}

DISCLAIMER = (
    "This is a prototype risk assessment based on correlated indicators. It is not proof of fraud. "
    "Scores are heuristic risk points, not probabilities."
)
