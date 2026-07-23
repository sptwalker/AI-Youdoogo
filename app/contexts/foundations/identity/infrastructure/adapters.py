"""Identity adapters for existing platform services."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

import app.platform.outbox.source_change as source_change_events
from app.contexts.foundations.identity.application.errors import (
    FeishuExchangeFailed,
    FeishuIdentityMissing,
)
from app.contexts.foundations.identity.application.ports import ExternalIdentity
from app.core.security import DUMMY_HASH, hash_password, verify_password
from app.integrations.feishu.client import FeishuAPIError, feishu_client


class BcryptPasswordAdapter:
    """Keep password policy and timing equalization in the security adapter."""

    def hash(self, password: str) -> str:
        return hash_password(password)

    def verify(self, password: str, password_hash: str | None) -> bool:
        return verify_password(password, password_hash or DUMMY_HASH)


class FeishuOAuthAdapter:
    """Translate the legacy Feishu client into the Identity port."""

    async def exchange(self, code: str) -> ExternalIdentity:
        try:
            info = await feishu_client.oauth_user_info(code)
        except FeishuAPIError as exc:
            raise FeishuExchangeFailed(str(exc)) from exc
        open_id = info.get("open_id")
        if not isinstance(open_id, str):
            raise FeishuIdentityMissing()
        return ExternalIdentity(open_id=open_id)


class SQLAlchemySourceChangeAdapter:
    """Publish Identity changes into the caller's current DB transaction."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def publish_identity_changed(self, identity_id: uuid.UUID) -> None:
        await source_change_events.publish_source_change(
            self._session,
            source_type="identity",
            source_id=identity_id,
            affected_scopes=("identity",),
        )


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class UUIDIdentifier:
    def new_id(self) -> uuid.UUID:
        return uuid.uuid4()
