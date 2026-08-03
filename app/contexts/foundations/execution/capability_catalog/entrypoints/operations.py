"""Published Capability Catalog operations."""

from app.contexts.foundations.execution.capability_catalog.contracts.definition import (
    CapabilityDefinition,
)
from app.contexts.foundations.execution.capability_catalog.infrastructure.registry import (
    InMemoryCapabilityCatalog,
)


async def list_capabilities() -> tuple[CapabilityDefinition, ...]:
    return await InMemoryCapabilityCatalog().list_definitions()
