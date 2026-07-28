"""Adapters from source Context public contracts to Environment Projection inputs."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.environment_projection.application.snapshot import (
    ConnectorSource,
    DepartmentSource,
    EnvironmentSources,
    ExpertSource,
    IdentitySource,
)
from app.contexts.foundations.identity import public as identity
from app.contexts.foundations.integration.connector_management import (
    public as connector_management,
)
from app.contexts.foundations.organization_structure import (
    public as organization_structure,
)
from app.contexts.foundations.organization_structure.contracts import (
    OrganizationTreeNodeSnapshot,
)
from app.contexts.foundations.workforce.expert_management.public import (
    build_local_expert_directory_port,
)


class PublishedEnvironmentSourceReader:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._experts = build_local_expert_directory_port(session)

    async def read(self) -> EnvironmentSources:
        organization = await organization_structure.get_snapshot(self._session)
        experts = await self._experts.list_roster(include_personal=False)
        identities = await identity.list_users(self._session)
        connectors = await connector_management.connector_catalog(self._session)
        return EnvironmentSources(
            departments=tuple(_department(root) for root in organization.roots),
            experts=tuple(
                ExpertSource(
                    expert_id=expert.expert_id,
                    name=expert.name,
                    title=expert.title,
                    tier=expert.tier,
                    department_id=expert.department_id,
                    is_active=expert.is_active,
                )
                for expert in experts
            ),
            identities=tuple(
                IdentitySource(
                    username=user.username,
                    real_name=user.real_name,
                    role_code=user.role_code,
                    department_id=user.department_id,
                    is_active=user.is_active,
                )
                for user in identities
            ),
            connectors=tuple(
                ConnectorSource(
                    name=connector.name,
                    connector_type=connector.connector_type,
                    secret_status=connector.secret_status,
                    is_active=connector.is_active,
                    owner_expert_id=connector.owner_expert_id,
                )
                for connector in connectors
            ),
        )


def _department(node: OrganizationTreeNodeSnapshot) -> DepartmentSource:
    return DepartmentSource(
        department_id=node.department.department_id,
        name=node.department.name,
        children=tuple(_department(child) for child in node.children),
    )
