"""Orchestration: run the three independent analyzers, then correlate.

This module sits ABOVE the analyzers (it is the only place that imports them);
the analyzers import nothing from each other or from here.
"""

from typing import Any, Optional

from ..attachment_analysis import analyze_attachment
from ..behaviour import analyze_incident_behaviour
from ..message_analysis import ExtractionError, analyze_message
from .engine import RiskCorrelationResult, correlate_risk


def assess_incident_risk(
    incident: Any,
    attachment_file: Optional[tuple] = None,
) -> RiskCorrelationResult:
    """Analyze an incident with all available analyzers and correlate the results.

    `incident` needs `.message`, `.channel`, `.sender.name/.role`,
    `.payment.amount/.beneficiary_name`. `attachment_file` is an optional
    (file_name, bytes, content_type) tuple: the incident stores attachment
    metadata only, so without the file there is no attachment evidence.
    An AttachmentError for a bad file propagates to the caller.
    A message-analysis failure degrades to "message evidence unavailable" and is
    reported in `inputs`, never silently.
    """
    unavailable: dict = {}
    try:
        message = analyze_message(incident.message)
    except ExtractionError as exc:
        message = None
        unavailable["message"] = f"Message analysis was unavailable ({exc.code})."

    behaviour = analyze_incident_behaviour(
        sender_name=incident.sender.name,
        channel=incident.channel,
        amount=incident.payment.amount,
        beneficiary=incident.payment.beneficiary_name,
    )

    attachment = None
    if attachment_file is not None:
        file_name, data, content_type = attachment_file
        attachment = analyze_attachment(file_name, data, content_type)

    return correlate_risk(message, behaviour, attachment, incident, unavailable=unavailable)
