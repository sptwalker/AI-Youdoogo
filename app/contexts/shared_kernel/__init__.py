"""Minimal shared kernel for stable cross-context contracts."""

from app.contexts.shared_kernel.application_errors import (
    ApplicationError,
    AuthenticationFailed,
    ConflictDetected,
    DependencyUnavailable,
    InvalidInput,
    PermissionDenied,
    ResourceNotFound,
    RuleViolation,
)

__all__ = [
    "ApplicationError",
    "AuthenticationFailed",
    "ConflictDetected",
    "DependencyUnavailable",
    "InvalidInput",
    "PermissionDenied",
    "ResourceNotFound",
    "RuleViolation",
]
