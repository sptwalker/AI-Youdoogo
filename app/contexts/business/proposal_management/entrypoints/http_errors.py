"""Map proposal-management failures to the stable HTTP error envelope."""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.contexts.business.proposal_management.application.errors import ProposalNotFound
from app.contexts.business.proposal_management.domain.errors import ProposalError
from app.platform.http_runtime import error_response


def proposal_error_response(error: ProposalError) -> JSONResponse:
    """Translate a delivery-agnostic proposal error at the HTTP boundary."""
    if isinstance(error, ProposalNotFound):
        return error_response(404, 404, str(error))
    return error_response(400, 1, str(error))


def register_proposal_error_handlers(app: FastAPI) -> None:
    """Register proposal error translation in the composition root."""

    @app.exception_handler(ProposalError)
    async def _proposal_error(_: Request, exc: ProposalError) -> JSONResponse:
        return proposal_error_response(exc)
