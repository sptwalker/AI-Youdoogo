"""Pure Environment Projection snapshot rendering."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Protocol

ENV_DOC_TITLE = "系统环境快照"

_TIER_LABEL = {"exec": "高管", "director": "总监", "member": "员工"}
_ROLE_LABEL = {"admin": "管理员", "executive": "高管", "member": "员工"}
_SECRET_LABEL = {
    "not_set": "未配置密钥",
    "configured": "密钥已配置",
    "missing": "密钥缺失",
}


@dataclass(frozen=True, slots=True)
class DepartmentSource:
    department_id: uuid.UUID
    name: str
    children: tuple[DepartmentSource, ...] = ()


@dataclass(frozen=True, slots=True)
class ExpertSource:
    expert_id: uuid.UUID
    name: str
    title: str
    tier: str
    department_id: uuid.UUID | None
    is_active: bool


@dataclass(frozen=True, slots=True)
class IdentitySource:
    username: str
    real_name: str
    role_code: str
    department_id: uuid.UUID | None
    is_active: bool


@dataclass(frozen=True, slots=True)
class ConnectorSource:
    name: str
    connector_type: str
    secret_status: str
    is_active: bool
    owner_expert_id: uuid.UUID | None


@dataclass(frozen=True, slots=True)
class EnvironmentSources:
    departments: tuple[DepartmentSource, ...]
    experts: tuple[ExpertSource, ...]
    identities: tuple[IdentitySource, ...]
    connectors: tuple[ConnectorSource, ...]


class EnvironmentSourceReader(Protocol):
    async def read(self) -> EnvironmentSources: ...


class BuildEnvironmentSnapshot:
    def __init__(self, sources: EnvironmentSourceReader) -> None:
        self._sources = sources

    async def execute(self) -> str:
        sources = await self._sources.read()
        return render_environment_snapshot(sources)


def render_environment_snapshot(sources: EnvironmentSources) -> str:
    department_names: dict[uuid.UUID, str] = {}

    def collect_departments(nodes: tuple[DepartmentSource, ...]) -> None:
        for node in nodes:
            department_names[node.department_id] = node.name
            collect_departments(node.children)

    collect_departments(sources.departments)

    def department_name(department_id: uuid.UUID | None) -> str:
        if department_id is None:
            return "未挂部门"
        return department_names.get(department_id, "未挂部门")

    department_counts: dict[uuid.UUID, int] = {}
    for expert in sources.experts:
        if expert.department_id is not None:
            department_counts[expert.department_id] = (
                department_counts.get(expert.department_id, 0) + 1
            )
    unassigned = sum(
        1 for expert in sources.experts if expert.department_id is None
    )

    expert_lines = [
        f"- {expert.name}（{_TIER_LABEL.get(expert.tier, expert.tier)}"
        + (
            f"，{expert.title}"
            if expert.title and expert.title != expert.name
            else ""
        )
        + f"，{department_name(expert.department_id)}"
        + ("" if expert.is_active else "，已停用")
        + "）"
        for expert in sources.experts
    ]
    identity_lines = [
        f"- {identity.real_name or identity.username}（账号 {identity.username}，"
        f"{_ROLE_LABEL.get(identity.role_code, identity.role_code)}，"
        f"{department_name(identity.department_id)}"
        + ("" if identity.is_active else "，已停用")
        + "）"
        for identity in sources.identities
    ]
    expert_names = {expert.expert_id: expert.name for expert in sources.experts}

    def owner_name(owner_expert_id: uuid.UUID | None) -> str:
        if owner_expert_id is None:
            return "未指派"
        return expert_names.get(owner_expert_id, "未指派")

    connector_lines = [
        f"- {connector.name}（类型 {connector.connector_type}，"
        f"{'启用' if connector.is_active else '停用'}，"
        f"{_SECRET_LABEL.get(connector.secret_status, connector.secret_status)}，"
        f"对接AI：{owner_name(connector.owner_expert_id)}）"
        for connector in sources.connectors
    ]

    roster_title = f"AI 员工花名册（共 {len(sources.experts)} 名"
    roster_title += f"，其中未挂部门 {unassigned} 名）" if unassigned else "）"
    return "\n\n".join(
        [
            f"# {ENV_DOC_TITLE}",
            "本文档由系统档案员自动维护，反映系统当前的组织架构、AI员工、真人用户与数据接口。"
            "（AI员工数不含真人的专属助理；组织树括号内为直挂该节点的AI数，非子树合计。）",
            _section(
                "组织架构",
                _render_tree(sources.departments, department_counts),
                "尚未初始化组织树",
            ),
            _section(roster_title, expert_lines, "暂无AI员工"),
            _section("真人用户", identity_lines, "暂无用户"),
            _section("数据接口", connector_lines, "暂无数据接口"),
        ]
    )


def _render_tree(
    nodes: tuple[DepartmentSource, ...],
    counts: dict[uuid.UUID, int],
    depth: int = 0,
) -> list[str]:
    lines: list[str] = []
    for node in nodes:
        lines.append(
            f"{'  ' * depth}- {node.name}"
            f"（直属AI员工 {counts.get(node.department_id, 0)} 名）"
        )
        lines.extend(_render_tree(node.children, counts, depth + 1))
    return lines


def _section(title: str, lines: list[str], empty: str) -> str:
    return f"## {title}\n" + ("\n".join(lines) if lines else f"（{empty}）")
