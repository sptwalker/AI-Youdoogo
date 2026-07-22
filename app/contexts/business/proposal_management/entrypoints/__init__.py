"""Proposal-management entrypoint exports."""

from app.contexts.business.proposal_management.entrypoints.http_errors import (
    proposal_error_response,
    register_proposal_error_handlers,
)

__all__ = ["proposal_error_response", "register_proposal_error_handlers"]
