"""Secret redaction policy for immutable audit evidence."""

from __future__ import annotations

from collections.abc import Mapping

_SECRET_HINTS = ("secret", "password", "token", "api_key", "apikey", "access_key")


def mask_secrets(detail: Mapping[str, object] | None) -> dict[str, object] | None:
    if not detail:
        return dict(detail) if detail is not None else None
    masked: dict[str, object] = {}
    for key, value in detail.items():
        if any(hint in key.lower() for hint in _SECRET_HINTS):
            masked[key] = "***"
        elif isinstance(value, Mapping):
            masked[key] = mask_secrets(value)
        else:
            masked[key] = value
    return masked
