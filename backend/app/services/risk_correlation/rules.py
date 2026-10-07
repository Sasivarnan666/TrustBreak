"""Transparent, deterministic scoring rules for Risk Engine 2.0.

EVERYTHING HERE IS PROTOTYPE HEURISTIC SCORING.

* The weights are hand-chosen "risk points". They are NOT probabilities and are NOT statistically
  calibrated against real fraud data. 85 points means "85 risk points from correlated indicators",
  never "85% chance of fraud".
* The thresholds are prototype values. They have not been scientifically validated.
* ALL weights, consolidation groups and category caps live in this one file. Analyzer and adapter code
  contains no scoring numbers.
* Correlation, not keyword counting: related indicators that describe the SAME underlying evidence are
  consolidated into ONE contribution (see CONSOLIDATION_GROUPS), and each category's total is capped
  (see CATEGORY_CAPS).

Stdlib only; no imports from the individual analysis modules.
"""

from dataclasses import dataclass

ENGINE_VERSION = "2.0.0"  # Risk Engine 2.0. Pre-2.0 stored assessments keep their own engine_version (e.g. "0.6.0").
SCORING_METHOD = "heuristic_points_v2"
SCORE_LABEL = "Prototype heuristic risk score"
MAX_SCORE = 100  # displayed score is capped here; the uncapped sum is reported as `raw_points`

# --- categories ------------------------------------------------------------- #
IDENTITY, COMMUNICATION, FINANCIAL, BENEFICIARY = "IDENTITY", "COMMUNICATION", "FINANCIAL", "BENEFICIARY"
BEHAVIOUR, SOCIAL_ENGINEERING, ATTACHMENT = "BEHAVIOUR", "SOCIAL_ENGINEERING", "ATTACHMENT"
CATEGORIES = (IDENTITY, COMMUNICATION, FINANCIAL, BENEFICIARY, BEHAVIOUR, SOCIAL_ENGINEERING, ATTACHMENT)
CATEGORY_LABELS = {
    IDENTITY: "Identity", COMMUNICATION: "Communication", FINANCIAL: "Financial", BENEFICIARY: "Beneficiary",
    BEHAVIOUR: "Behaviour", SOCIAL_ENGINEERING: "Social engineering", ATTACHMENT: "Attachment",
}

# --- signal sources: where the EVIDENCE came from (never overstated) ------------ #
SRC_RULE = "rule"                          # deterministic pattern / rule detection
SRC_BASELINE = "synthetic_baseline"        # comparison against the SYNTHETIC behavioural baseline
SRC_AI = "AI"                              # a language model reported it AND the evidence was grounded in the message
SRC_FALLBACK = "fallback"                  # deterministic rules used because the AI provider failed (not AI output)
SRC_ATTACHMENT = "attachment_static"       # static structural attachment inspection (nothing executed or extracted)
SRC_SYSTEM = "system"                      # produced by the engine itself
SOURCES = (SRC_RULE, SRC_BASELINE, SRC_AI, SRC_FALLBACK, SRC_ATTACHMENT, SRC_SYSTEM)
SOURCE_LABELS = {
    SRC_RULE: "Rule (deterministic pattern)", SRC_BASELINE: "Synthetic behavioural baseline",
    SRC_AI: "AI (grounded in the message)", SRC_FALLBACK: "Fallback (deterministic, not AI)",
    SRC_ATTACHMENT: "Static attachment analysis", SRC_SYSTEM: "System",
}
# Which analyzer output a signal was derived from (used for the trust-break "independent sources" test).
AN_MESSAGE, AN_BEHAVIOUR, AN_ATTACHMENT = "message", "behaviour", "attachment"

# Preference order when two corroborating signals tie on points (deterministic tie-break only).
SOURCE_PREFERENCE = (SRC_AI, SRC_RULE, SRC_FALLBACK, SRC_BASELINE, SRC_ATTACHMENT, SRC_SYSTEM)

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


# --- confidence --------------------------------------------------------------- #
# Social-engineering indicators carry a confidence (rule match strength, or the model's self-report for AI
# items). It scales the weight so that a weak match ("today") counts for less than a strong one ("urgent").
# Signals from deterministic comparisons (baseline, attachment structure, extraction flags) have no confidence
# and use their full weight.
CONFIDENCE_FACTOR = {"high": 1.0, "medium": 0.75, "low": 0.5}


def scaled_points(weight: int, confidence) -> int:
    """weight x confidence factor, rounded half up; unknown/absent confidence -> full weight."""
    return int(weight * CONFIDENCE_FACTOR.get(confidence, 1.0) + 0.5)


@dataclass(frozen=True)
class SignalRule:
    code: str
    category: str
    group: str       # consolidation group: signals in the same group share ONE contribution
    weight: int      # prototype heuristic points at full confidence
    title: str
    default_message: str
    rationale: str   # why this weight (documented for every weight)


# --------------------------------------------------------------------------- #
# THE SCORING TABLE (prototype heuristic weights). One rule per signal code.
# --------------------------------------------------------------------------- #
RULES = (
    # ---- IDENTITY -------------------------------------------------------- #
    SignalRule("AUTHORITY_MISMATCH", IDENTITY, "authority", 15, "Claimed authority mismatch",
               "The authority claimed in the message differs from the sender's recorded role.",
               "A claimed role that contradicts the recorded role is a direct identity inconsistency."),
    # ---- COMMUNICATION --------------------------------------------------- #
    SignalRule("UNUSUAL_CHANNEL", COMMUNICATION, "channel", 15, "Unusual channel",
               "The communication channel differs from the sender's normal channels.",
               "Payment requests moved to an informal channel are a classic impersonation pattern."),
    SignalRule("CHANNEL_DISTRIBUTION_ANOMALY", COMMUNICATION, "channel", 6, "Rarely used channel",
               "The channel is known but accounts for a very small share of the sender's synthetic history.",
               "A seldom-used channel is a weaker signal than a never-seen one. Scored once with UNUSUAL_CHANNEL (shared 'channel' group)."),
    # ---- FINANCIAL ------------------------------------------------------- #
    SignalRule("AMOUNT_ABOVE_BASELINE", FINANCIAL, "amount", 20, "Amount above baseline",
               "Requested amount is above the sender's normal maximum.",
               "Large deviations from normal amounts are the main financial-loss driver."),
    SignalRule("FINANCIAL_TRANSFER_INTENT", FINANCIAL, "payment_request", 8, "Financial transfer request",
               "The message asks for a financial transfer or payment-detail change.",
               "A request to move money is what a fraudster needs, but most payment messages are legitimate, so the weight is small. Scored once with PAYMENT_PRESSURE."),
    # ---- BENEFICIARY ----------------------------------------------------- #
    SignalRule("NEW_BENEFICIARY", BENEFICIARY, "beneficiary", 20, "New beneficiary",
               "The beneficiary is not present in the sender's known beneficiary profile.",
               "Paying a never-before-seen recipient is the most common payment-diversion indicator."),
    # ---- BEHAVIOUR (category cap applies) -------------------------------- #
    SignalRule("UNUSUAL_TIME", BEHAVIOUR, "time_of_day", 6, "Unusual time",
               "The request time is outside the sender's usual working hours.",
               "Out-of-hours requests are mildly unusual; legitimate urgent work also happens then."),
    SignalRule("UNUSUAL_DAY", BEHAVIOUR, "day_of_week", 4, "Unusual day",
               "The request day is outside the sender's usual working days.",
               "Weaker than time of day; often co-occurs with it, so it is deliberately small."),
    SignalRule("FREQUENCY_ANOMALY", BEHAVIOUR, "frequency", 8, "Request frequency above baseline",
               "More requests than the sender's historical weekly maximum.",
               "Repeated requests in a short period are a recognised escalation pattern."),
    SignalRule("VELOCITY_ANOMALY", BEHAVIOUR, "velocity", 12, "Request velocity burst",
               "Several requests in a very short window, above the historical burst size.",
               "A burst is stronger evidence than a weekly count."),
    # ---- SOCIAL ENGINEERING (category cap applies) ----------------------- #
    SignalRule("HIGH_URGENCY", SOCIAL_ENGINEERING, "time_pressure", 8, "High urgency",
               "The message contains urgent payment language.",
               "Urgency is a pressure tactic, but common in genuine business; kept small."),
    SignalRule("URGENCY_PRESSURE", SOCIAL_ENGINEERING, "time_pressure", 8, "Urgency pressure",
               "The message pressures the reader to act immediately.",
               "Pressure to act immediately leaves no time for checks. Scored once with HIGH_URGENCY and DEADLINE_PRESSURE."),
    SignalRule("DEADLINE_PRESSURE", SOCIAL_ENGINEERING, "time_pressure", 8, "Deadline pressure",
               "The message sets a short deadline.",
               "A tight deadline is the concrete form of urgency and leaves no time for checks. Scored once with the other time-pressure signals."),
    SignalRule("SECRECY_REQUESTED", SOCIAL_ENGINEERING, "concealment", 10, "Secrecy requested",
               "The message asks for the request to be kept confidential.",
               "Asking to hide a payment from colleagues defeats normal controls."),
    SignalRule("SECRECY_PRESSURE", SOCIAL_ENGINEERING, "concealment", 10, "Secrecy pressure",
               "The message asks the reader to keep the request secret.",
               "Asking the reader to keep a payment secret defeats normal controls. Scored once with SECRECY_REQUESTED and ISOLATION_REQUEST."),
    SignalRule("ISOLATION_REQUEST", SOCIAL_ENGINEERING, "concealment", 8, "Isolation request",
               "The message asks the reader not to involve other people.",
               "Keeping other people out of a payment removes the chance of a second opinion. Scored once with the other concealment signals."),
    SignalRule("VERIFICATION_SUPPRESSION", SOCIAL_ENGINEERING, "verification_suppression", 12,
               "Verification suppression", "The message discourages calls, checks or approvals.",
               "Actively preventing verification is a strong, distinct fraud tactic."),
    SignalRule("FEAR_OR_THREAT", SOCIAL_ENGINEERING, "coercion", 8, "Fear or threat",
               "The message threatens consequences if the reader does not comply.",
               "Coercion reduces careful judgement."),
    SignalRule("PAYMENT_PRESSURE", SOCIAL_ENGINEERING, "payment_request", 5, "Payment pressure",
               "The message instructs the reader to release or transfer funds.",
               "An explicit instruction to release funds is the action the fraud needs. Scored once with FINANCIAL_TRANSFER_INTENT."),
    SignalRule("CREDENTIAL_PRESSURE", SOCIAL_ENGINEERING, "credential", 12, "Credential pressure",
               "The message asks for a password, OTP or similar credential.",
               "Credential requests are rarely legitimate in a payment context."),
    SignalRule("IMPERSONATION_CUE", SOCIAL_ENGINEERING, "impersonation", 8, "Impersonation cue",
               "The message uses wording typical of impersonation (new number, lost phone...).",
               "Common impersonation pretexts, but each is also innocent in isolation."),
    SignalRule("UNUSUAL_INSTRUCTION", SOCIAL_ENGINEERING, "unusual_instruction", 10, "Unusual instruction",
               "The message gives an unusual payment instruction (gift cards, crypto, split payments...).",
               "Instructions outside normal procurement channels are strongly associated with fraud."),
    SignalRule("AUTHORITY_PRESSURE", SOCIAL_ENGINEERING, "authority", 5, "Authority pressure",
               "The message invokes a senior title to add pressure.",
               "Invoking a senior title adds pressure but is weak alone. Scored once with AUTHORITY_MISMATCH, which is stronger."),
    # ---- ATTACHMENT (category cap applies) -------------------------------- #
    SignalRule("EXECUTABLE_ATTACHMENT", ATTACHMENT, "attachment_executable", 25, "Executable content",
               "The uploaded file contains executable content.",
               "Executable content is the most direct attachment risk property (static inspection only: nothing is run)."),
    SignalRule("RISKY_EXTENSION", ATTACHMENT, "attachment_executable", 20, "Risky file extension",
               "The file uses an extension associated with executable or script content.",
               "Extensions such as .exe or .scr indicate runnable content. Scored once with EXECUTABLE_ATTACHMENT."),
    SignalRule("DOCUMENT_WITH_EXECUTABLE", ATTACHMENT, "attachment_masquerade", 12, "Document-looking file with executable",
               "The file looks like a document or statement but contains executable content.",
               "A statement-looking archive that hides runnable files is deliberate disguise. Scored once with the double-extension finding."),
    SignalRule("DOUBLE_EXTENSION", ATTACHMENT, "attachment_masquerade", 12, "Double extension",
               "A file name uses a document-looking extension followed by an executable extension.",
               "A name like Invoice.pdf.exe tries to look like a document. Scored once with DOCUMENT_WITH_EXECUTABLE."),
    SignalRule("PATH_TRAVERSAL", ATTACHMENT, "attachment_structure", 12, "Path traversal indicator",
               "An archive entry path points outside the archive folder.",
               "A distinct structural exploit pattern, independent of executables."),
    SignalRule("OTHER_HIGH_SEVERITY_ATTACHMENT_FINDING", ATTACHMENT, "attachment_structure", 8,
               "Other high-severity attachment finding",
               "Attachment analysis reported another high-severity structural finding.",
               "Catch-all for high-severity findings without a dedicated rule."),
    SignalRule("SUSPICIOUS_STRUCTURE", ATTACHMENT, "attachment_structure", 5, "Suspicious archive structure",
               "The archive has a structural property that limits inspection (encrypted, nested, very compressed).",
               "Reduced inspectability is a weak indicator on its own."),
)
RULES_BY_CODE = {r.code: r for r in RULES}
RISK_WEIGHTS = {r.code: r.weight for r in RULES}  # the single, central weight table
GROUP_FOR_CODE = {r.code: r.group for r in RULES}

# Why signals in a group are scored once. Within a group the strongest signal is scored and the others are
# recorded on it as `related_signal_codes` (nothing is hidden, nothing is double counted).
CONSOLIDATION_GROUPS = {
    "time_pressure": "Urgency, high urgency and deadline wording describe the same pressure to act quickly.",
    "concealment": "Secrecy and isolation requests describe the same attempt to keep the request hidden.",
    "payment_request": "A payment instruction and the extracted financial-transfer intent are the same request.",
    "authority": "An authority claim and a claimed-vs-recorded role mismatch describe the same authority evidence.",
    "channel": "A never-seen channel and a rarely used channel are the same channel observation.",
    "attachment_executable": "Executable content and a risky extension describe the same executable property.",
    "attachment_masquerade": "A document-looking archive and a double extension are two views of the same disguise.",
    "attachment_structure": "Structural attachment findings are scored once at the strongest finding.",
}

# Maximum points a category may contribute in total (prototype guard so many weak related indicators
# cannot, on their own, outweigh the strongest context-inconsistency evidence). Categories not listed are uncapped.
CATEGORY_CAPS = {
    BEHAVIOUR: 20,
    SOCIAL_ENGINEERING: 30,
    ATTACHMENT: 40,
}

# Signals that mean "this request does not fit the trusted context" (used for TRUST BREAK DETECTED).
CONTEXT_INCONSISTENCY_CODES = frozenset(
    {"AMOUNT_ABOVE_BASELINE", "NEW_BENEFICIARY", "UNUSUAL_CHANNEL", "AUTHORITY_MISMATCH"}
)

# --- how upstream outputs map onto signals ----------------------------------- #
# Message analysis `financial_intent` values that count as a funds-transfer request.
FINANCIAL_TRANSFER_INTENTS = frozenset(
    {"payment_transfer", "invoice_payment", "gift_card_purchase", "bank_detail_change", "other_financial"}
)
HIGH_URGENCY_LEVELS = frozenset({"high"})  # "medium" urgency earns no points (prototype choice)

# Behaviour anomaly codes that map 1:1 onto a rule.
BEHAVIOUR_ANOMALY_CODES = (
    "AMOUNT_ABOVE_BASELINE", "NEW_BENEFICIARY", "UNUSUAL_CHANNEL", "CHANNEL_DISTRIBUTION_ANOMALY",
    "UNUSUAL_TIME", "UNUSUAL_DAY", "FREQUENCY_ANOMALY", "VELOCITY_ANOMALY",
)
# Legacy boolean flags on the behaviour result (used when the anomalies list is absent).
BEHAVIOUR_FLAG_CODES = (
    ("amount_anomaly", "AMOUNT_ABOVE_BASELINE"), ("new_beneficiary", "NEW_BENEFICIARY"),
    ("channel_anomaly", "UNUSUAL_CHANNEL"),
)
# Social-engineering indicator name -> signal code (names come from the message analysis).
SOCIAL_SIGNAL_CODES = {
    "authority_pressure": "AUTHORITY_PRESSURE", "urgency_pressure": "URGENCY_PRESSURE",
    "secrecy_pressure": "SECRECY_PRESSURE", "verification_suppression": "VERIFICATION_SUPPRESSION",
    "isolation_request": "ISOLATION_REQUEST", "fear_or_threat": "FEAR_OR_THREAT",
    "deadline_pressure": "DEADLINE_PRESSURE", "payment_pressure": "PAYMENT_PRESSURE",
    "credential_pressure": "CREDENTIAL_PRESSURE", "impersonation_cue": "IMPERSONATION_CUE",
    "unusual_instruction": "UNUSUAL_INSTRUCTION",
}

# Attachment finding types -> rule (each finding type maps to exactly one rule).
EXECUTABLE_FINDING_TYPES = frozenset({"executable_inside_archive", "executable_file"})
RISKY_EXTENSION_FINDING_TYPES = frozenset({"risky_extension"})
DOCUMENT_DECEPTION_FINDING_TYPES = frozenset({"document_with_executable_content"})
DOUBLE_EXTENSION_FINDING_TYPES = frozenset({"double_extension"})
PATH_TRAVERSAL_FINDING_TYPES = frozenset({"path_traversal"})
STRUCTURAL_FINDING_TYPES = frozenset(
    {"encrypted_entries", "nested_archive", "high_compression_ratio", "large_uncompressed_size"}
)
DEDICATED_FINDING_TYPES = (
    EXECUTABLE_FINDING_TYPES | RISKY_EXTENSION_FINDING_TYPES | DOCUMENT_DECEPTION_FINDING_TYPES
    | DOUBLE_EXTENSION_FINDING_TYPES | PATH_TRAVERSAL_FINDING_TYPES | STRUCTURAL_FINDING_TYPES
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
    "Risk assessment is deterministic prototype decision support. It is not proof of fraud and the score is not a "
    "probability. Scores are uncalibrated heuristic risk points."
)
