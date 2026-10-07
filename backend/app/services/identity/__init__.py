"""Synthetic trusted-identity model (stdlib only). Public: TrustedIdentity, list_identities, get_identity, resolve_identity."""

from .model import TrustedIdentity, normalize
from .registry import get_identity, list_identities, resolve_identity, resolve_by_name

__all__ = ["TrustedIdentity", "normalize", "get_identity", "list_identities", "resolve_identity", "resolve_by_name"]
