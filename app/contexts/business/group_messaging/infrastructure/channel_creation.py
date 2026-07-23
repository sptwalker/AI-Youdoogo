"""Minimal composition for the published department-channel operation."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.business.group_messaging.application.channel_creation import (
    CreateDepartmentChannel,
)
from app.contexts.business.group_messaging.infrastructure.sqlalchemy_uow import (
    SQLAlchemyGroupMessagingUnitOfWork,
)


class _SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class _UUIDIdentifier:
    def new_id(self) -> uuid.UUID:
        return uuid.uuid4()

    def new_object_token(self) -> str:
        return uuid.uuid4().hex


def build_department_channel_creator(session: AsyncSession) -> CreateDepartmentChannel:
    return CreateDepartmentChannel(
        uow_factory=lambda: SQLAlchemyGroupMessagingUnitOfWork(session),
        clock=_SystemClock(),
        identifiers=_UUIDIdentifier(),
    )
