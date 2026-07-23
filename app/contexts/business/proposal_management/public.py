"""Published Proposal Management read operations."""

from app.contexts.business.proposal_management.application.contracts import ProposalResult
from app.contexts.business.proposal_management.entrypoints.operations import list_proposals

__all__ = ["ProposalResult", "list_proposals"]
