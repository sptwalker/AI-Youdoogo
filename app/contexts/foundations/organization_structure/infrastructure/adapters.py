"""Organization Structure adapters for published provider contracts."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

import app.platform.outbox.source_change as source_change_events
from app.contexts.business.group_messaging import department_channels
from app.contexts.foundations.identity import public as identity_public
from app.contexts.foundations.organization_structure.application.contracts import (
    ExternalDepartmentRecord,
    ExternalUserRecord,
    TemplateExpertSpec,
)
from app.contexts.foundations.organization_structure.application.errors import (
    ExternalDepartmentUnavailable,
)
from app.contexts.foundations.workforce.expert_management.contracts.roster import (
    DepartmentExpertCount,
    ExpertRosterSnapshot,
)
from app.contexts.foundations.workforce.expert_management.public import (
    build_local_expert_directory_port,
    build_local_expert_provisioning_port,
)
from app.contexts.shared_kernel import DependencyUnavailable
from app.integrations.feishu.client import FeishuAPIError, feishu_client

logger = logging.getLogger(__name__)


class OrganizationSourceChangeAdapter:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def publish_organization_changed(self, department_id: uuid.UUID) -> None:
        await source_change_events.publish_source_change(
            self._session,
            source_type="organization",
            source_id=department_id,
            affected_scopes=("organization",),
        )


class PublishedGroupMessagingAdapter:
    """Organization-owned adapter over Group Messaging's published channel operation."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_department_channel(
        self, *, department_id: uuid.UUID, department_name: str
    ) -> None:
        await department_channels.create_department_channel(
            self._session,
            name=f"{department_name}讨论区",
            department_id=department_id,
        )


class PublishedExpertManagementAdapter:
    """Organization-owned adapter over Expert Management's published operations."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._directory = build_local_expert_directory_port(session)
        self._provisioning = build_local_expert_provisioning_port(session)

    async def list_department_roster(
        self, department_id: uuid.UUID
    ) -> tuple[ExpertRosterSnapshot, ...]:
        return await self._directory.list_department_roster(department_id)

    async def count_by_department(
        self, *, include_personal: bool
    ) -> tuple[DepartmentExpertCount, ...]:
        return await self._directory.count_by_department(
            include_personal=include_personal,
        )

    async def has_department_assignment(self, department_id: uuid.UUID) -> bool:
        return bool(await self.list_department_roster(department_id))

    async def seed_expert(self, spec: TemplateExpertSpec) -> ExpertRosterSnapshot:
        return await self._provisioning.seed(
            code=spec.code,
            name=spec.name,
            prompt_template=spec.prompt_template,
            title=spec.title,
            tier=spec.tier,
            model_role=spec.model_role,
            department_id=spec.department_id,
            duty=spec.duty,
            report_to_id=spec.report_to_id,
        )


class PublishedIdentityDirectoryAdapter:
    """Resolve supervisor existence through Identity's request-scoped operation."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def user_exists(self, user_id: uuid.UUID) -> bool:
        return (
            await identity_public.get_user_by_id(self._session, user_id=user_id)
            is not None
        )


class PublishedIdentitySyncAdapter:
    """Translate an external directory user into Identity's owned sync command."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def sync_user(
        self, user: ExternalUserRecord, *, department_id: uuid.UUID
    ) -> bool:
        result = await identity_public.sync_external_user(
            self._session,
            identity_public.SyncExternalUserCommand(
                feishu_open_id=user.external_id,
                real_name=user.name,
                en_name=user.en_name,
                title=user.title,
                mobile=user.mobile,
                avatar_url=user.avatar_url,
                department_id=department_id,
            ),
        )
        return result.created


class FeishuOrganizationDirectoryAdapter:
    """Read Feishu directory data without leaking vendor payloads to Application."""

    async def list_departments(self) -> tuple[ExternalDepartmentRecord, ...]:
        try:
            rows = await feishu_client.list_departments()
        except FeishuAPIError as exc:
            raise DependencyUnavailable(f"拉取飞书部门失败:{exc}") from exc
        return tuple(
            ExternalDepartmentRecord(
                external_id=str(row["open_department_id"]),
                parent_external_id=(
                    str(row["parent_department_id"])
                    if row.get("parent_department_id")
                    else None
                ),
                name=str(row.get("name") or "未命名部门"),
            )
            for row in rows
            if row.get("open_department_id")
        )

    async def list_users(
        self, department_external_id: str
    ) -> tuple[ExternalUserRecord, ...]:
        try:
            rows = await feishu_client.list_users_by_department(department_external_id)
        except FeishuAPIError as exc:
            logger.warning(
                "拉取部门 %s 员工失败，跳过",
                department_external_id,
                exc_info=True,
            )
            raise ExternalDepartmentUnavailable() from exc
        return tuple(self._user(row) for row in rows if row.get("open_id"))

    @staticmethod
    def _user(row: dict[str, Any]) -> ExternalUserRecord:
        avatar = row.get("avatar")
        avatar_url = avatar.get("avatar_240") if isinstance(avatar, dict) else ""
        department_ids = row.get("department_ids")
        return ExternalUserRecord(
            external_id=str(row["open_id"]),
            name=str(row.get("name") or "未命名"),
            en_name=str(row.get("en_name") or ""),
            title=str(row.get("job_title") or ""),
            mobile=str(row.get("mobile") or ""),
            avatar_url=str(avatar_url or ""),
            department_external_ids=tuple(
                str(item) for item in department_ids or () if item
            ),
        )


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class UUIDIdentifier:
    def new_id(self) -> uuid.UUID:
        return uuid.uuid4()
