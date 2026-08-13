"""Stable Identity contracts and request-scoped operations for external callers."""

from app.contexts.foundations.identity.application.contracts import (
    ExternalUserSyncResult,
    IdentityUserResult,
    SyncExternalUserCommand,
)
from app.contexts.foundations.identity.contracts import Principal, PrincipalType
from app.contexts.foundations.identity.entrypoints.operations import (
    authenticate_feishu,
    authenticate_password,
    create_user,
    get_user_by_id,
    get_user_by_username,
    list_users,
    login_by_feishu,
    sync_external_user,
    update_user,
)

__all__ = [
    "ExternalUserSyncResult",
    "IdentityUserResult",
    "Principal",
    "PrincipalType",
    "SyncExternalUserCommand",
    "authenticate_feishu",
    "authenticate_password",
    "create_user",
    "get_user_by_id",
    "get_user_by_username",
    "list_users",
    "login_by_feishu",
    "sync_external_user",
    "update_user",
]
