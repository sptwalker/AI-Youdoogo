"""Expert lifecycle and roster use cases."""

from __future__ import annotations

import uuid

from app.contexts.foundations.workforce.expert_management.application.contracts import (
    CreateExpertCommand,
    SeedExpertCommand,
    UpdateExpertCommand,
)
from app.contexts.foundations.workforce.expert_management.application.errors import (
    ExpertWriteConflict,
)
from app.contexts.foundations.workforce.expert_management.application.management_ports import (
    Clock,
    ExpertUnitOfWorkFactory,
    IdentifierPort,
)
from app.contexts.foundations.workforce.expert_management.application.ports import (
    ExpertRosterQueryPort,
)
from app.contexts.foundations.workforce.expert_management.contracts.roster import (
    DepartmentExpertCount,
    ExpertRosterSnapshot,
)
from app.contexts.foundations.workforce.expert_management.domain.models import (
    ExpertProfile,
    validate_model_role,
    validate_tier,
)
from app.contexts.shared_kernel import ConflictDetected, ResourceNotFound


def _snapshot(expert: ExpertProfile) -> ExpertRosterSnapshot:
    return ExpertRosterSnapshot(
        expert_id=expert.id,
        version=expert.version,
        code=expert.code,
        name=expert.name,
        title=expert.title,
        tier=expert.tier,
        department_id=expert.department_id,
        report_to_id=expert.report_to_id,
        owner_user_id=expert.owner_user_id,
        duty=expert.duty,
        prompt_template=expert.prompt_template,
        model_role=expert.model_role,
        permission_scope_json=expert.permission_scope_json,
        tools_json=expert.tools_json,
        is_seed=expert.is_seed,
        is_active=expert.is_active,
        create_time=expert.create_time,
    )


class ExpertManagementApplication:
    def __init__(
        self,
        *,
        uow_factory: ExpertUnitOfWorkFactory,
        roster: ExpertRosterQueryPort,
        identifiers: IdentifierPort,
        clock: Clock,
    ) -> None:
        self._uow_factory = uow_factory
        self._roster = roster
        self._identifiers = identifiers
        self._clock = clock

    async def create(self, command: CreateExpertCommand) -> ExpertRosterSnapshot:
        validate_model_role(command.model_role)
        validate_tier(command.tier)
        expert = ExpertProfile(
            id=self._identifiers.new_id(),
            version="new",
            code=None,
            name=command.name,
            title=command.title,
            tier=command.tier,
            department_id=command.department_id,
            report_to_id=command.report_to_id,
            owner_user_id=command.owner_user_id,
            duty=command.duty,
            prompt_template=command.prompt_template,
            model_role=command.model_role,
            permission_scope_json=command.permission_scope_json,
            tools_json=command.tools_json,
            is_seed=False,
            is_active=True,
            create_time=self._clock.now(),
        )
        try:
            async with self._uow_factory() as uow:
                await uow.experts.add(expert)
                await uow.flush()
                await uow.source_changes.publish_expert_changed(expert.id)
                await uow.commit()
        except ExpertWriteConflict as exc:
            raise ConflictDetected("角色名或编码已存在") from exc
        return await self._reload(expert)

    async def update(self, command: UpdateExpertCommand) -> ExpertRosterSnapshot:
        try:
            async with self._uow_factory() as uow:
                expert = await uow.experts.get(command.expert_id)
                if expert is None or expert.is_deleted:
                    raise ResourceNotFound("智能体员工不存在")
                expert.update(
                    name=command.name,
                    prompt_template=command.prompt_template,
                    duty=command.duty,
                    model_role=command.model_role,
                    is_active=command.is_active,
                    permission_scope_json=command.permission_scope_json,
                    tools_json=command.tools_json,
                    title=command.title,
                    tier=command.tier,
                    report_to_id=command.report_to_id,
                    department_id=command.department_id,
                )
                await uow.experts.save(expert)
                await uow.flush()
                await uow.source_changes.publish_expert_changed(expert.id)
                await uow.commit()
        except ExpertWriteConflict as exc:
            raise ConflictDetected("角色名已被占用") from exc
        return await self._reload(expert)

    async def seed(self, command: SeedExpertCommand) -> ExpertRosterSnapshot:
        """Upsert one stable template profile while preserving operator-edited prompts."""
        validate_model_role(command.model_role)
        validate_tier(command.tier)
        try:
            async with self._uow_factory() as uow:
                expert = await uow.experts.get_by_code(command.code)
                if expert is None:
                    expert = await uow.experts.get_by_name(command.name)
                if expert is None:
                    changed = True
                    expert = ExpertProfile(
                        id=self._identifiers.new_id(),
                        version="new",
                        code=command.code,
                        name=command.name,
                        title=command.title,
                        tier=command.tier,
                        department_id=command.department_id,
                        report_to_id=command.report_to_id,
                        owner_user_id=None,
                        duty=command.duty,
                        prompt_template=command.prompt_template,
                        model_role=command.model_role,
                        permission_scope_json="{}",
                        tools_json="[]",
                        is_seed=True,
                        is_active=True,
                        create_time=self._clock.now(),
                    )
                    await uow.experts.add(expert)
                else:
                    before = (
                        expert.code,
                        expert.name,
                        expert.title,
                        expert.tier,
                        expert.model_role,
                        expert.department_id,
                        expert.is_seed,
                        expert.duty,
                        expert.report_to_id,
                    )
                    expert.apply_seed(
                        code=command.code,
                        name=command.name,
                        title=command.title,
                        tier=command.tier,
                        model_role=command.model_role,
                        department_id=command.department_id,
                        duty=command.duty,
                        report_to_id=command.report_to_id,
                    )
                    changed = before != (
                        expert.code,
                        expert.name,
                        expert.title,
                        expert.tier,
                        expert.model_role,
                        expert.department_id,
                        expert.is_seed,
                        expert.duty,
                        expert.report_to_id,
                    )
                    await uow.experts.save(expert)
                await uow.flush()
                if changed:
                    await uow.source_changes.publish_expert_changed(expert.id)
                await uow.commit()
        except ExpertWriteConflict as exc:
            raise ConflictDetected("角色名或编码已存在") from exc
        return await self._reload(expert)

    async def delete(self, expert_id: uuid.UUID) -> None:
        async with self._uow_factory() as uow:
            expert = await uow.experts.get(expert_id)
            if expert is None or expert.is_deleted:
                raise ResourceNotFound("智能体员工不存在")
            expert.delete()
            await uow.experts.save(expert)
            await uow.flush()
            await uow.source_changes.publish_expert_changed(expert.id)
            await uow.commit()

    async def list_roster(
        self, *, include_personal: bool = False
    ) -> tuple[ExpertRosterSnapshot, ...]:
        return await self._roster.list_roster(include_personal=include_personal)

    async def list_department_roster(
        self, department_id: uuid.UUID
    ) -> tuple[ExpertRosterSnapshot, ...]:
        return await self._roster.list_department_roster(department_id)

    async def count_by_department(
        self, *, include_personal: bool
    ) -> tuple[DepartmentExpertCount, ...]:
        return await self._roster.count_by_department(include_personal=include_personal)

    async def _reload(self, fallback: ExpertProfile) -> ExpertRosterSnapshot:
        persisted = await self._roster.get_roster_by_id(fallback.id)
        return persisted or _snapshot(fallback)
