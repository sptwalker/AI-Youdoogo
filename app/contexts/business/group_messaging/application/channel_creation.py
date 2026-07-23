"""Focused Group Messaging use case for Organization-owned channel requests."""

from __future__ import annotations

import uuid

from app.contexts.business.group_messaging.application.contracts import ChannelResult
from app.contexts.business.group_messaging.application.ports import (
    Clock,
    GroupMessagingUnitOfWorkFactory,
    IdentifierPort,
)
from app.contexts.business.group_messaging.domain.models import Channel


class CreateDepartmentChannel:
    def __init__(
        self,
        *,
        uow_factory: GroupMessagingUnitOfWorkFactory,
        clock: Clock,
        identifiers: IdentifierPort,
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock
        self._identifiers = identifiers

    async def execute(self, *, name: str, department_id: uuid.UUID) -> ChannelResult:
        channel = Channel(
            id=self._identifiers.new_id(),
            name=name,
            department_id=department_id,
            default_agent_id=None,
            creator_id=None,
            create_time=self._clock.now(),
        )
        async with self._uow_factory() as uow:
            await uow.messages.add_channel(channel)
            await uow.commit()
        return ChannelResult(
            id=channel.id,
            name=channel.name,
            department_id=channel.department_id,
            default_agent_id=channel.default_agent_id,
            creator_id=channel.creator_id,
            is_archived=channel.is_archived,
            create_time=channel.create_time,
        )
