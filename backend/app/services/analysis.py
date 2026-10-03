"""PLACEHOLDER incident analysis.

This is NOT fraud detection and NOT AI. It performs no scoring, no pattern
matching and no inference. It exists so the full flow
frontend -> backend -> database -> dashboard works end to end.

What it does:
  * marks every incident `needs_review`
  * records the submitted facts as "evidence" (source = "submitted")
  * returns one fixed, generic recommended action

The real analysis engine will replace `analyze_incident` behind the same
signature (see docs/ROADMAP.md).
"""

from ..schemas import Analysis, EvidenceItem, IncidentCreate

ANALYSIS_MODE = "placeholder"
RISK_NEEDS_REVIEW = "needs_review"

SUMMARY = (
    "Automated analysis is not enabled in this build. The evidence below is the "
    "information exactly as submitted; no fraud detection has been performed."
)
RECOMMENDED_ACTION = (
    "Hold the payment. Confirm the request with the sender through a phone number "
    "or channel from your own records - not the one used in this request - before "
    "any funds are released."
)


def format_inr(amount: int) -> str:
    """Indian digit grouping, e.g. 1850000 -> '₹18,50,000'."""
    digits = str(amount)
    if len(digits) <= 3:
        return f"₹{digits}"
    head, tail = digits[:-3], digits[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return "₹" + ",".join(groups + [tail])


def _format_bytes(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024**2:
        return f"{size / 1024:.1f} KB"
    return f"{size / 1024**2:.1f} MB"


def _attachment_value(payload: IncidentCreate) -> str:
    if not payload.attachment_name:
        return "No attachment"
    extras = []
    if payload.attachment_content_type:
        extras.append(payload.attachment_content_type)
    if payload.attachment_size_bytes is not None:
        extras.append(_format_bytes(payload.attachment_size_bytes))
    return payload.attachment_name + (f" ({', '.join(extras)})" if extras else "")


def analyze_incident(payload: IncidentCreate) -> Analysis:
    evidence = [
        EvidenceItem(label="Sender", value=f"{payload.sender_name}, {payload.sender_role}", source="submitted"),
        EvidenceItem(
            label="Sender status",
            value="Known contact" if payload.sender_known else "Not a known contact",
            source="submitted",
        ),
        EvidenceItem(label="Channel", value=payload.channel, source="submitted"),
        EvidenceItem(label="Amount requested", value=format_inr(payload.amount), source="submitted"),
        EvidenceItem(
            label="Beneficiary",
            value=f"{payload.beneficiary_name} ({'new' if payload.beneficiary_is_new else 'existing'})",
            source="submitted",
        ),
        EvidenceItem(label="Attachment", value=_attachment_value(payload), source="submitted"),
    ]
    return Analysis(
        mode=ANALYSIS_MODE,
        risk_status=RISK_NEEDS_REVIEW,
        summary=SUMMARY,
        recommended_action=RECOMMENDED_ACTION,
        evidence=evidence,
    )
