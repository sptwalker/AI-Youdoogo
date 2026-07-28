"""Connector collaboration adapters at the infrastructure edge."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

import app.platform.outbox.source_change as source_change_events
from app.contexts.foundations.integration.connector_management.domain.models import Connector
from app.contexts.foundations.workforce.expert_management.public import (
    build_local_expert_directory_port,
)
from app.core.config import get_settings


class ExpertRosterAdapter:
    def __init__(self, session: AsyncSession) -> None:
        self._directory = build_local_expert_directory_port(session)

    async def exists(self, expert_id: uuid.UUID) -> bool:
        return await self._directory.get_roster(expert_id) is not None

    async def names(self, expert_ids: tuple[uuid.UUID, ...]) -> dict[uuid.UUID, str]:
        if not expert_ids:
            return {}
        wanted = set(expert_ids)
        roster = await self._directory.list_roster(include_personal=True)
        return {
            snapshot.expert_id: snapshot.name
            for snapshot in roster
            if snapshot.expert_id in wanted
        }


class EnvironmentSecretStatusAdapter:
    def status(self, secret_ref: str | None) -> str:
        if not secret_ref:
            return "not_set"
        return (
            "configured"
            if getattr(get_settings(), secret_ref.lower(), "")
            else "missing"
        )


class SourceChangePublisher:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def publish(self, connector: Connector) -> None:
        await source_change_events.publish_source_change(
            self._session,
            source_type="connector",
            source_id=connector.id,
            affected_scopes=("connector",),
        )
