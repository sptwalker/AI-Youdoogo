"""Capability Catalog query port."""

from __future__ import annotations

from typing import Protocol

from app.contexts.foundations.execution.capability_catalog.contracts.definition import (
    CapabilityDefinition,
)


class CapabilityDefinitionQueryPort(Protocol):
    async def resolve(self, key: str, version: str | None) -> CapabilityDefinition | None: ...

    async def list_definitions(self) -> tuple[CapabilityDefinition, ...]: ...
