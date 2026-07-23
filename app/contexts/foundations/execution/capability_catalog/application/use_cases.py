"""Read-only Capability Catalog use cases."""

from app.contexts.foundations.execution.capability_catalog.application.ports import (
    CapabilityDefinitionQueryPort,
)
from app.contexts.foundations.execution.capability_catalog.contracts.definition import (
    CapabilityDefinition,
)


class ListCapabilityDefinitions:
    def __init__(self, catalog: CapabilityDefinitionQueryPort) -> None:
        self._catalog = catalog

    async def execute(self) -> tuple[CapabilityDefinition, ...]:
        return await self._catalog.list_definitions()
