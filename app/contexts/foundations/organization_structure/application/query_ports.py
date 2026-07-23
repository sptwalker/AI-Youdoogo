"""Published Organization Structure query port."""

from typing import Protocol

from app.contexts.foundations.organization_structure.contracts import OrganizationSnapshot


class OrganizationSnapshotQueryPort(Protocol):
    async def get_snapshot(self) -> OrganizationSnapshot: ...
