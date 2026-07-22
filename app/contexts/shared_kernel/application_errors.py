"""Transport-agnostic application failure categories shared across contexts.

The shared kernel intentionally contains only stable failure semantics. Domain-specific
errors should still live in their owning bounded context and may be mapped separately.
"""


class ApplicationError(Exception):
    """Base class for user-safe application failures without HTTP metadata."""


class RuleViolation(ApplicationError):
    """A business or use-case rule rejected the requested operation."""


class InvalidInput(ApplicationError):
    """The supplied input is invalid before a use case can proceed."""


class AuthenticationFailed(ApplicationError):
    """The caller could not be authenticated."""


class PermissionDenied(ApplicationError):
    """The authenticated caller is not allowed to perform the operation."""


class ResourceNotFound(ApplicationError):
    """A required application resource does not exist."""


class ConflictDetected(ApplicationError):
    """The operation conflicts with current state or an existing resource."""


class DependencyUnavailable(ApplicationError):
    """A required external dependency is temporarily unavailable."""
