"""Organization Structure use cases and snapshot assembly."""

from __future__ import annotations

import uuid

from app.contexts.foundations.organization_structure.application.contracts import (
    CreateDepartmentCommand,
    ExternalDepartmentRecord,
    OrganizationDirectorySyncResult,
    OrganizationTemplateResult,
    SeedOrganizationTemplateCommand,
    SetSupervisorCommand,
    TemplateExpertSpec,
    UpdateDepartmentCommand,
)
from app.contexts.foundations.organization_structure.application.errors import (
    ExternalDepartmentUnavailable,
    OrganizationWriteConflict,
)
from app.contexts.foundations.organization_structure.application.ports import (
    Clock,
    DepartmentDiscussionPort,
    DepartmentRepository,
    ExpertRosterPort,
    ExternalIdentitySyncPort,
    ExternalOrganizationDirectoryPort,
    IdentifierPort,
    IdentityDirectoryPort,
    OrganizationUnitOfWorkFactory,
)
from app.contexts.foundations.organization_structure.contracts import (
    DepartmentSnapshot,
    OrganizationSnapshot,
    OrganizationTreeNodeSnapshot,
)
from app.contexts.foundations.organization_structure.domain.models import DepartmentNode
from app.contexts.foundations.workforce.expert_management.contracts.roster import (
    ExpertRosterSnapshot,
)
from app.contexts.shared_kernel import (
    ConflictDetected,
    ResourceNotFound,
    RuleViolation,
)

_DEPARTMENTS: tuple[tuple[str, str, int], ...] = (
    ("dept_product_base", "基础产品部", 1),
    ("dept_game_rd", "游戏研发部", 2),
    ("dept_platform_ops", "平台运营部", 3),
    ("dept_business", "商务合作部", 4),
    ("dept_marketing", "营销销售部", 5),
    ("dept_brand", "品牌宣传部", 6),
    ("dept_hr", "人资行政部", 7),
    ("dept_finance", "财务部", 8),
    ("dept_public_design", "公共设计组", 9),
)
_EXECS: tuple[tuple[str, str, str], ...] = (
    ("exec_cpo", "CPO", "首席产品顾问"),
    ("exec_cco", "CCO", "首席创意顾问"),
    ("exec_coo", "COO", "首席运营顾问"),
    ("exec_cto", "CTO", "首席技术顾问"),
    ("exec_cmo", "CMO", "首席营销顾问"),
    ("exec_cbo", "CBO", "首席商务顾问"),
    ("exec_cho", "CHO", "首席人事顾问"),
    ("exec_cfo", "CFO", "首席财务顾问"),
)
_DIRECTORS: tuple[tuple[str, str, str, str], ...] = (
    ("dir_product_base", "基础产品部总监助理", "dept_product_base", "exec_cpo"),
    ("dir_public_design", "公共设计组总监助理", "dept_public_design", "exec_cco"),
    ("dir_platform_ops", "平台运营部总监助理", "dept_platform_ops", "exec_coo"),
    ("dir_game_rd", "游戏研发部总监助理", "dept_game_rd", "exec_cto"),
    ("dir_marketing", "营销销售部总监助理", "dept_marketing", "exec_cmo"),
    ("dir_brand", "品牌宣传部总监助理", "dept_brand", "exec_cmo"),
    ("dir_business", "商务合作部总监助理", "dept_business", "exec_cbo"),
    ("dir_hr", "人资行政部总监助理", "dept_hr", "exec_cho"),
    ("dir_finance", "财务部总监助理", "dept_finance", "exec_cfo"),
)
_EXEC_PROMPT = (
    "你是创想悦动的{title}（公司级 AI 顾问）。你协助并代理真人高管进行分管领域的战略分析、"
    "风险评估、方案利弊推演与部门管理支持。你直属真人 CEO（最高管理员）监督。"
    "红线：你仅有建议/分析/辅助执行权，涉及资金/人事/项目/业务调整的决议必须真人确认生效。"
)
_DIRECTOR_PROMPT = (
    "你是创想悦动{dept}的 AI 总监助理。你协助并代理真人部门主管统筹本部门的数据监控、报告生成、"
    "任务拆解与执行、优化建议。红线：你仅有建议/执行权，一切生效动作须真人确认，产出可溯源、全程留痕。"
)


def _snapshot(node: DepartmentNode) -> DepartmentSnapshot:
    return DepartmentSnapshot(
        department_id=node.id,
        version=node.version,
        name=node.name,
        code=node.code,
        node_type=node.node_type,
        level=node.level,
        path=node.path,
        parent_id=node.parent_id,
        supervisor_user_id=node.supervisor_user_id,
        sort_order=node.sort_order,
        create_time=node.create_time,
    )


class OrganizationStructureApplication:
    def __init__(
        self,
        *,
        uow_factory: OrganizationUnitOfWorkFactory,
        experts: ExpertRosterPort,
        identities: IdentityDirectoryPort,
        external_directory: ExternalOrganizationDirectoryPort,
        external_identities: ExternalIdentitySyncPort,
        discussions: DepartmentDiscussionPort,
        identifiers: IdentifierPort,
        clock: Clock,
    ) -> None:
        self._uow_factory = uow_factory
        self._experts = experts
        self._identities = identities
        self._external_directory = external_directory
        self._external_identities = external_identities
        self._discussions = discussions
        self._identifiers = identifiers
        self._clock = clock

    async def get_node(self, department_id: uuid.UUID) -> DepartmentSnapshot:
        async with self._uow_factory() as uow:
            node = await self._required(uow.departments, department_id)
        return _snapshot(node)

    async def get_snapshot(self) -> OrganizationSnapshot:
        async with self._uow_factory() as uow:
            nodes = await uow.departments.list_nodes()
        counts = {
            item.department_id: item.count
            for item in await self._experts.count_by_department(include_personal=True)
        }
        snapshots = {node.id: _snapshot(node) for node in nodes}
        children: dict[uuid.UUID, list[uuid.UUID]] = {node.id: [] for node in nodes}
        root_ids: list[uuid.UUID] = []
        for node in nodes:
            if node.parent_id is not None and node.parent_id in snapshots:
                children[node.parent_id].append(node.id)
            else:
                root_ids.append(node.id)

        def build(node_id: uuid.UUID) -> OrganizationTreeNodeSnapshot:
            return OrganizationTreeNodeSnapshot(
                department=snapshots[node_id],
                employee_count=counts.get(node_id, 0),
                children=tuple(build(child_id) for child_id in children[node_id]),
            )

        version = max((node.version for node in nodes), default="empty")
        return OrganizationSnapshot(
            version=version,
            roots=tuple(build(root_id) for root_id in root_ids),
        )

    async def create_department(self, command: CreateDepartmentCommand) -> DepartmentSnapshot:
        try:
            async with self._uow_factory() as uow:
                parent = await self._required(uow.departments, command.parent_id)
                department = parent.create_child(
                    child_id=self._identifiers.new_id(),
                    name=command.name,
                    code=command.code or f"dept_{uuid.uuid4().hex[:8]}",
                    create_time=self._clock.now(),
                )
                await uow.departments.add(department)
                await uow.flush()
                await self._discussions.create_department_channel(
                    department_id=department.id,
                    department_name=department.name,
                )
                await uow.source_changes.publish_organization_changed(department.id)
                await uow.commit()
        except OrganizationWriteConflict as exc:
            raise ConflictDetected("同级下已有同名部门") from exc
        return await self.get_node(department.id)

    async def update_department(self, command: UpdateDepartmentCommand) -> DepartmentSnapshot:
        async with self._uow_factory() as uow:
            node = await self._required(uow.departments, command.department_id)
            node.update(name=command.name, sort_order=command.sort_order)
            await uow.departments.save(node)
            await uow.source_changes.publish_organization_changed(node.id)
            await uow.commit()
        return await self.get_node(node.id)

    async def delete_department(self, department_id: uuid.UUID) -> None:
        async with self._uow_factory() as uow:
            node = await self._required(uow.departments, department_id)
            if node.node_type == "company":
                node.delete()
            if await uow.departments.has_active_child(department_id):
                raise RuleViolation("该部门下还有子部门，请先移除子部门")
            if await self._experts.has_department_assignment(department_id):
                raise RuleViolation("该部门下还有智能体员工，请先移除或转移")
            node.delete()
            await uow.departments.save(node)
            await uow.source_changes.publish_organization_changed(node.id)
            await uow.commit()

    async def set_supervisor(self, command: SetSupervisorCommand) -> DepartmentSnapshot:
        async with self._uow_factory() as uow:
            node = await self._required(uow.departments, command.department_id)
            if command.supervisor_user_id is not None and not await self._identities.user_exists(
                command.supervisor_user_id
            ):
                raise RuleViolation("指定的主管用户不存在")
            node.supervisor_user_id = command.supervisor_user_id
            await uow.departments.save(node)
            await uow.source_changes.publish_organization_changed(node.id)
            await uow.commit()
        return await self.get_node(node.id)

    async def list_department_employees(
        self, department_id: uuid.UUID
    ) -> tuple[ExpertRosterSnapshot, ...]:
        return await self._experts.list_department_roster(department_id)

    async def ancestor_ids(
        self, department_id: uuid.UUID | None
    ) -> tuple[uuid.UUID, ...]:
        if department_id is None:
            return ()
        async with self._uow_factory() as uow:
            node = await self._required(uow.departments, department_id)
        return node.ancestor_ids()

    async def seed_template(
        self, command: SeedOrganizationTemplateCommand
    ) -> OrganizationTemplateResult:
        """Seed Organization-owned nodes, then delegate Expert-owned profiles."""
        async with self._uow_factory() as uow:
            root = await uow.departments.get_by_code("company")
            if root is None:
                root = DepartmentNode.create_company(
                    company_id=self._identifiers.new_id(),
                    name="创想悦动",
                    code="company",
                    supervisor_user_id=command.ceo_user_id,
                    create_time=self._clock.now(),
                )
                await uow.departments.add(root)
                await uow.flush()
            elif command.ceo_user_id is not None:
                root.set_supervisor(command.ceo_user_id)
                await uow.departments.save(root)

            departments: dict[str, DepartmentNode] = {}
            for code, name, sort_order in _DEPARTMENTS:
                department = await uow.departments.get_by_code(code)
                if department is None:
                    department = await uow.departments.get_by_parent_name(root.id, name)
                if department is None:
                    department = root.create_child(
                        child_id=self._identifiers.new_id(),
                        name=name,
                        code=code,
                        create_time=self._clock.now(),
                    )
                    department.sort_order = sort_order
                    await uow.departments.add(department)
                    await uow.flush()
                    await self._discussions.create_department_channel(
                        department_id=department.id,
                        department_name=department.name,
                    )
                else:
                    department.normalize_template_child(
                        root=root,
                        code=code,
                        name=name,
                        sort_order=sort_order,
                    )
                    await uow.departments.save(department)
                departments[code] = department
            await uow.source_changes.publish_organization_changed(root.id)
            await uow.commit()

        executives: dict[str, ExpertRosterSnapshot] = {}
        for code, abbreviation, full_name in _EXECS:
            name = f"{full_name}（{abbreviation}）"
            executives[code] = await self._experts.seed_expert(
                TemplateExpertSpec(
                    code=code,
                    name=name,
                    title=abbreviation,
                    tier="exec",
                    model_role="reasoning",
                    department_id=root.id,
                    prompt_template=_EXEC_PROMPT.format(title=name),
                    duty=abbreviation,
                )
            )
        for code, name, department_code, executive_code in _DIRECTORS:
            department = departments[department_code]
            await self._experts.seed_expert(
                TemplateExpertSpec(
                    code=code,
                    name=name,
                    title=name,
                    tier="director",
                    model_role="daily",
                    department_id=department.id,
                    prompt_template=_DIRECTOR_PROMPT.format(dept=department.name),
                    duty=name,
                    report_to_id=executives[executive_code].expert_id,
                )
            )
        return OrganizationTemplateResult(
            root=root.name,
            departments=len(_DEPARTMENTS),
            execs=len(_EXECS),
            directors=len(_DIRECTORS),
        )

    async def sync_external_directory(self) -> OrganizationDirectorySyncResult:
        records = sort_external_departments(await self._external_directory.list_departments())
        async with self._uow_factory() as uow:
            root = await uow.departments.get_company_root()
            if root is None:
                raise RuleViolation("未初始化公司根节点，无法同步组织")
            departments: dict[str, DepartmentNode] = {}
            for record in records:
                parent = departments.get(record.parent_external_id or "", root)
                department = await uow.departments.get_by_external_id(record.external_id)
                if department is None:
                    department = parent.create_external_child(
                        child_id=self._identifiers.new_id(),
                        external_id=record.external_id,
                        name=record.name,
                        create_time=self._clock.now(),
                    )
                    await uow.departments.add(department)
                    await uow.flush()
                else:
                    department.move_external_child(parent=parent, name=record.name)
                    await uow.departments.save(department)
                departments[record.external_id] = department
            await uow.source_changes.publish_organization_changed(root.id)
            await uow.commit()

        users_created = users_updated = 0
        for record in records:
            try:
                users = await self._external_directory.list_users(record.external_id)
            except ExternalDepartmentUnavailable:
                continue
            for user in users:
                department = next(
                    (
                        departments[external_id]
                        for external_id in user.department_external_ids
                        if external_id in departments
                    ),
                    root,
                )
                if await self._external_identities.sync_user(
                    user,
                    department_id=department.id,
                ):
                    users_created += 1
                else:
                    users_updated += 1
        return OrganizationDirectorySyncResult(
            departments=len(departments),
            users_created=users_created,
            users_updated=users_updated,
        )

    @staticmethod
    async def _required(
        repository: DepartmentRepository, department_id: uuid.UUID
    ) -> DepartmentNode:
        node = await repository.get(department_id)
        if node is None or node.is_deleted:
            raise ResourceNotFound("部门不存在")
        return node


def sort_external_departments(
    departments: tuple[ExternalDepartmentRecord, ...],
) -> tuple[ExternalDepartmentRecord, ...]:
    """Topologically order external departments so parents are materialized first."""
    by_id = {department.external_id: department for department in departments}
    ordered: list[ExternalDepartmentRecord] = []
    seen: set[str] = set()

    def visit(department: ExternalDepartmentRecord) -> None:
        if department.external_id in seen:
            return
        parent = by_id.get(department.parent_external_id or "")
        if parent is not None:
            visit(parent)
        seen.add(department.external_id)
        ordered.append(department)

    for department in departments:
        visit(department)
    return tuple(ordered)
