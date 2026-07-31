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
from app.contexts.foundations.workforce.expert_management.contracts.execution import (
    ExpertReleaseView,
)
from app.contexts.foundations.workforce.expert_management.contracts.roster import (
    DepartmentExpertCount,
    ExpertRosterSnapshot,
)
from app.contexts.foundations.workforce.expert_management.domain.models import (
    ExpertExecutionDefinition,
    ExpertProfile,
    ExpertRelease,
    OrgExpertMember,
    validate_model_role,
    validate_tier,
)
from app.contexts.shared_kernel import ConflictDetected, ResourceNotFound


def _snapshot(expert: ExpertProfile) -> ExpertRosterSnapshot:
    member, execution = expert.member, expert.execution
    return ExpertRosterSnapshot(
        expert_id=expert.id,
        version=expert.version,
        code=member.code,
        name=member.name,
        title=member.title,
        tier=member.tier,
        department_id=member.department_id,
        report_to_id=member.report_to_id,
        owner_user_id=member.owner_user_id,
        duty=execution.duty,
        prompt_template=execution.prompt_template,
        model_role=execution.model_role,
        permission_scope_json=execution.permission_scope_json,
        tools_json=execution.tools_json,
        is_seed=member.is_seed,
        is_active=member.is_active,
        create_time=expert.create_time,
    )


def _seed_fingerprint(expert: ExpertProfile) -> tuple[object, ...]:
    """Seed 幂等比对键——旧 update 前后对照的 9 字段，跨两子聚合读取。"""
    member, execution = expert.member, expert.execution
    return (
        member.code,
        member.name,
        member.title,
        member.tier,
        execution.model_role,
        member.department_id,
        member.is_seed,
        execution.duty,
        member.report_to_id,
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
            create_time=self._clock.now(),
            member=OrgExpertMember(
                code=None,
                name=command.name,
                title=command.title,
                tier=command.tier,
                department_id=command.department_id,
                report_to_id=command.report_to_id,
                owner_user_id=command.owner_user_id,
                is_seed=False,
                is_active=True,
            ),
            execution=ExpertExecutionDefinition(
                prompt_template=command.prompt_template,
                model_role=command.model_role,
                permission_scope_json=command.permission_scope_json,
                tools_json=command.tools_json,
                duty=command.duty,
            ),
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
                expert.member.revise(
                    name=command.name,
                    title=command.title,
                    tier=command.tier,
                    report_to_id=command.report_to_id,
                    department_id=command.department_id,
                    is_active=command.is_active,
                )
                expert.execution.revise(
                    prompt_template=command.prompt_template,
                    model_role=command.model_role,
                    permission_scope_json=command.permission_scope_json,
                    tools_json=command.tools_json,
                    duty=command.duty,
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
                        create_time=self._clock.now(),
                        member=OrgExpertMember(
                            code=command.code,
                            name=command.name,
                            title=command.title,
                            tier=command.tier,
                            department_id=command.department_id,
                            report_to_id=command.report_to_id,
                            owner_user_id=None,
                            is_seed=True,
                            is_active=True,
                        ),
                        execution=ExpertExecutionDefinition(
                            prompt_template=command.prompt_template,
                            model_role=command.model_role,
                            permission_scope_json="{}",
                            tools_json="[]",
                            duty=command.duty,
                        ),
                    )
                    await uow.experts.add(expert)
                else:
                    before = _seed_fingerprint(expert)
                    expert.member.apply_seed(
                        code=command.code,
                        name=command.name,
                        title=command.title,
                        tier=command.tier,
                        department_id=command.department_id,
                        report_to_id=command.report_to_id,
                    )
                    expert.execution.apply_seed(
                        model_role=command.model_role,
                        duty=command.duty,
                    )
                    changed = before != _seed_fingerprint(expert)
                    await uow.experts.save(expert)
                await uow.flush()
                if changed:
                    await uow.source_changes.publish_expert_changed(expert.id)
                await uow.commit()
        except ExpertWriteConflict as exc:
            raise ConflictDetected("角色名或编码已存在") from exc
        return await self._reload(expert)

    async def publish_release(
        self, expert_id: uuid.UUID, *, released_by: uuid.UUID | None = None
    ) -> ExpertReleaseView:
        """把某专家当前执行定义冻结成新一版不可变发布（Module 2 / docs/23 §4.2）。

        触发时机（自动切版 vs 显式发布）由 Module 3 生命周期决定，本方法只提供操作。
        """
        async with self._uow_factory() as uow:
            expert = await uow.experts.get(expert_id)
            if expert is None or expert.is_deleted:
                raise ResourceNotFound("智能体员工不存在")
            release = ExpertRelease.cut(
                release_id=self._identifiers.new_id(),
                expert=expert,
                version_no=await uow.releases.next_version_no(expert_id),
                released_by=released_by,
                released_at=self._clock.now(),
            )
            await uow.releases.add(release)
            await uow.flush()
            await uow.releases.set_current(expert_id, release.id)
            await uow.commit()
        return ExpertReleaseView(
            release_id=release.id,
            expert_id=release.expert_id,
            version_no=release.version_no,
            model_role=release.model_role,
            released_by=release.released_by,
            released_at=release.released_at,
        )

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
