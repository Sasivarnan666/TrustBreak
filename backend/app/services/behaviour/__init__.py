"""Behaviour baseline & anomaly detection (signals only, no risk score).

Public interface: `analyze_incident_behaviour(...)`, `analyze_behaviour(...)`.
"""

from typing import Optional

from .analyzer import BehaviourInput, analyze_behaviour
from .profile import BehaviourProfile, get_profile_for_sender


def analyze_incident_behaviour(
    sender_name: Optional[str],
    channel: Optional[str],
    amount: Optional[int],
    beneficiary: Optional[str],
) -> dict:
    """Look up the sender's synthetic profile and analyze the request against it."""
    return analyze_behaviour(
        BehaviourInput(channel=channel, amount=amount, beneficiary=beneficiary),
        get_profile_for_sender(sender_name),
    )


__all__ = [
    "BehaviourInput",
    "BehaviourProfile",
    "analyze_behaviour",
    "analyze_incident_behaviour",
    "get_profile_for_sender",
]
