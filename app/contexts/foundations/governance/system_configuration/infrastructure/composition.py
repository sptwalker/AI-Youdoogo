"""Request-scoped composition for System Configuration."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.governance.audit_trail.public import (
    AppendAuditRecordCommand,
    append_audit_record,
)
from app.contexts.foundations.governance.system_configuration.application.use_cases import (
    ListConfigurations,
    ResolveConfiguration,
    UpdateConfiguration,
)

from .sqlalchemy_adapter import (
    RuntimeConfigurationAdapter,
    SQLAlchemyConfigurationUnitOfWork,
)


class AuditTrailConfigurationAdapter:
    """Publish configuration changes through Audit Trail's public operation."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record_update(
        self,
        *,
        config_id: uuid.UUID,
        key: str,
        actor_id: uuid.UUID | None,
        actor_role: str | None,
    ) -> None:
        await append_audit_record(
            self._session,
            AppendAuditRecordCommand(
                actor_id=actor_id,
                actor_role=actor_role,
                action="config.update",
                summary=f"修改配置 {key}",
                target_type="sys_config",
                target_id=config_id,
                detail={"key": key},
            ),
        )


class SystemConfigurationOperations:
    """Application use cases composed for one request session."""

    def __init__(self, session: AsyncSession) -> None:
        unit = SQLAlchemyConfigurationUnitOfWork(session)
        self.resolve = ResolveConfiguration(unit)
        self.list = ListConfigurations(unit)
        self.update = UpdateConfiguration(
            unit,
            RuntimeConfigurationAdapter(),
            AuditTrailConfigurationAdapter(session),
        )


def build_system_configuration(
    session: AsyncSession,
) -> SystemConfigurationOperations:
    return SystemConfigurationOperations(session)
