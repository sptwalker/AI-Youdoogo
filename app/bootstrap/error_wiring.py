"""Map transport-agnostic application failures to the public HTTP contract."""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.contexts.shared_kernel import (
    ApplicationError,
    AuthenticationFailed,
    ConflictDetected,
    DependencyUnavailable,
    InvalidInput,
    PermissionDenied,
    ResourceNotFound,
    RuleViolation,
)
from app.platform.http_runtime import error_response

ErrorMapping = tuple[type[ApplicationError], int, int]

_ERROR_MAPPINGS: tuple[ErrorMapping, ...] = (
    (InvalidInput, 400, 400),
    (AuthenticationFailed, 401, 401),
    (PermissionDenied, 403, 403),
    (ResourceNotFound, 404, 404),
    (ConflictDetected, 409, 409),
    (DependencyUnavailable, 502, 502),
    (RuleViolation, 400, 1),
)


def application_error_response(error: ApplicationError) -> JSONResponse:
    """Translate an application failure without leaking HTTP into inner code."""
    for error_type, status_code, code in _ERROR_MAPPINGS:
        if isinstance(error, error_type):
            return error_response(status_code, code, str(error))
    return error_response(400, 1, str(error))


def register_application_error_handlers(app: FastAPI) -> None:
    """Register shared application failure translation in the composition root."""

    @app.exception_handler(ApplicationError)
    async def _application_error(_: Request, exc: ApplicationError) -> JSONResponse:
        return application_error_response(exc)
