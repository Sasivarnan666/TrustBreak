"""Risk level -> incident status mapping (pure, stdlib only).

The incident status is what the rest of the product shows once a risk
assessment exists. It is decision SUPPORT for a human: `hold_payment` means
"TrustBreak recommends that a person holds the transaction pending independent
verification". It never means a payment was blocked.
"""

NOT_ASSESSED = "not_assessed"
PROCEED = "proceed"
VERIFY = "verify"
HOLD_PAYMENT = "hold_payment"

STATUS_FOR_LEVEL = {
    "LOW": PROCEED,
    "MEDIUM": VERIFY,
    "HIGH": VERIFY,
    "CRITICAL": HOLD_PAYMENT,
}

STATUS_LABELS = {
    NOT_ASSESSED: "Not assessed",
    PROCEED: "Proceed",
    VERIFY: "Verify before paying",
    HOLD_PAYMENT: "Hold payment",
}

ALL_STATUSES = (NOT_ASSESSED, PROCEED, VERIFY, HOLD_PAYMENT)


def status_for_level(level) -> str:
    """Map a risk level to an incident status. Unknown level -> the cautious non-blocking `verify`."""
    return STATUS_FOR_LEVEL.get(level, VERIFY)


def label_for_status(status) -> str:
    return STATUS_LABELS.get(status, STATUS_LABELS[NOT_ASSESSED])
