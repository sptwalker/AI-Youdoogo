"""Published Proposal Management operations."""

from app.contexts.business.proposal_management.application.contracts import ProposalResult
from app.contexts.business.proposal_management.entrypoints.operations import (
    create_proposal,
    list_proposals,
)

__all__ = ["ProposalResult", "create_proposal", "list_proposals"]
