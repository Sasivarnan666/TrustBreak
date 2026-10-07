"""Behaviour baseline & anomaly detection (signals only, no risk score).

Public interface: `analyze_incident_behaviour(...)`, `analyze_behaviour(...)`.
"""

from typing import Optional

from .analyzer import BehaviourInput, analyze_behaviour
from .profile import BehaviourProfile, get_profile_for_identity, get_profile_for_sender


def analyze_incident_behaviour(
    sender_name: Optional[str],
    channel: Optional[str],
    amount: Optional[int],
    beneficiary: Optional[str],
    sender_identity_id: Optional[str] = None,
    timestamp: Optional[str] = None,
    recent_request_times: Optional[tuple] = None,
) -> dict:
    """Analyze the request against the sender's synthetic profile.

    The stable `sender_identity_id` is preferred. The display name is only a backwards-compatible fallback when
    no id is given; an id that does not exist never falls back to the name (no silent mis-identification).
    """
    if sender_identity_id:
        profile = get_profile_for_identity(sender_identity_id)
    else:
        profile = get_profile_for_sender(sender_name)
    return analyze_behaviour(
        BehaviourInput(
            channel=channel, amount=amount, beneficiary=beneficiary, timestamp=timestamp,
            recent_request_times=tuple(recent_request_times) if recent_request_times is not None else None,
        ),
        profile,
    )


__all__ = [
    "BehaviourInput",
    "BehaviourProfile",
    "analyze_behaviour",
    "analyze_incident_behaviour",
    "get_profile_for_identity",
    "get_profile_for_sender",
]
