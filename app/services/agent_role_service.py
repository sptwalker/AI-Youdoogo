"""智能体角色配置管理：新增部门智能体 = 建一行 agent_role（零新代码）。

验证 docs/06 阶段3「第二部门 Agent 以显著低于首个的工作量上线」：
新角色配好 prompt_template + model_role 即可被 scheduler/run_agent 通用驱动。
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.models.agent import TIER_DIRECTOR, TIER_EXEC, TIER_MEMBER, AgentRole

VALID_MODEL_ROLES = ("daily", "reasoning")
VALID_TIERS = (TIER_EXEC, TIER_DIRECTOR, TIER_MEMBER)


def _check_model_role(model_role: str) -> None:
    if model_role not in VALID_MODEL_ROLES:
        raise AppError(f"model_role 仅支持 {'/'.join(VALID_MODEL_ROLES)}")


def _check_tier(tier: str) -> None:
    if tier not in VALID_TIERS:
        raise AppError(f"tier 仅支持 {'/'.join(VALID_TIERS)}")


async def create_agent_role(
    db: AsyncSession,
    *,
    name: str,
    prompt_template: str,
    duty: str | None = None,
    model_role: str = "daily",
    department_id: uuid.UUID | None = None,
    permission_scope: dict[str, Any] | None = None,
    tools: list[Any] | None = None,
    tier: str = TIER_MEMBER,
    title: str = "",
    report_to_id: uuid.UUID | None = None,
) -> AgentRole:
    """新增一个智能体员工（name 唯一）。"""
    _check_model_role(model_role)
    _check_tier(tier)
    role = AgentRole(
        name=name, prompt_template=prompt_template, duty=duty, model_role=model_role,
        department_id=department_id, permission_scope=permission_scope or {}, tools=tools or [],
        tier=tier, title=title, report_to_id=report_to_id,
    )
    db.add(role)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise AppError("角色名或编码已存在", code=409, status_code=409) from exc
    await db.refresh(role)
    return role


async def update_agent_role(
    db: AsyncSession,
    role_id: uuid.UUID,
    *,
    prompt_template: str | None = None,
    duty: str | None = None,
    model_role: str | None = None,
    is_active: bool | None = None,
    permission_scope: dict[str, Any] | None = None,
    tools: list[Any] | None = None,
    title: str | None = None,
    tier: str | None = None,
    report_to_id: uuid.UUID | None = None,
    department_id: uuid.UUID | None = None,
) -> AgentRole:
    """更新智能体员工：仅更新提供的字段。"""
    role = await db.get(AgentRole, role_id)
    if role is None or role.is_delete:
        raise AppError("智能体员工不存在", code=404, status_code=404)
    if model_role is not None:
        _check_model_role(model_role)
        role.model_role = model_role
    if tier is not None:
        _check_tier(tier)
        role.tier = tier
    if prompt_template is not None:
        role.prompt_template = prompt_template
    if duty is not None:
        role.duty = duty
    if is_active is not None:
        role.is_active = is_active
    if permission_scope is not None:
        role.permission_scope = permission_scope
    if tools is not None:
        role.tools = tools
    if title is not None:
        role.title = title
    if report_to_id is not None:
        role.report_to_id = report_to_id
    if department_id is not None:
        role.department_id = department_id
    await db.commit()
    await db.refresh(role)
    return role


async def delete_agent_role(db: AsyncSession, role_id: uuid.UUID) -> None:
    """软删智能体员工。种子骨架（is_seed）不可删（保护 7 高管 + 8 总监）。"""
    role = await db.get(AgentRole, role_id)
    if role is None or role.is_delete:
        raise AppError("智能体员工不存在", code=404, status_code=404)
    if role.is_seed:
        raise AppError("骨架种子智能体（高管/总监）不可删除，如需停用请置为停用")
    role.is_delete = True
    await db.commit()


async def list_agent_roles(db: AsyncSession) -> list[AgentRole]:
    """列出全部未删除的智能体角色。"""
    stmt = (
        select(AgentRole)
        .where(AgentRole.is_delete.is_(False))
        .order_by(AgentRole.create_time)
    )
    return list((await db.execute(stmt)).scalars())
