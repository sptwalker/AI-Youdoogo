"""Opt-in Lodge resource-server foundation; legacy user login remains separate."""

from app.platform.lodge_identity.claims import LodgePrincipal
from app.platform.lodge_identity.service import LodgeIdentityService

__all__ = ["LodgeIdentityService", "LodgePrincipal"]
