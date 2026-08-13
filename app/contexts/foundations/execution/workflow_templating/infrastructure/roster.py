"""部门承接人名录：agent_role.code → id 批量解析（模板 expert_code 落到具体 Agent）。

一次查询取回所有 code→id 映射（避免逐 code N 查）；只认 is_active 且未删的角色。
foundations 读 agent_role 模型合规（多 Context 已在读，非反向依赖 business）。
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import AgentRole


async def load_agent_ids(
    session: AsyncSession, codes: Iterable[str]
) -> dict[str, uuid.UUID]:
    """把一组 agent_role.code 批量解析为 id；缺失/停用的 code 不入表（展开时回落 None）。"""
    wanted = {code for code in codes if code}
    if not wanted:
        return {}
    rows = (
        await session.execute(
            select(AgentRole.code, AgentRole.id).where(
                AgentRole.code.in_(wanted),
                AgentRole.is_active.is_(True),
                AgentRole.is_delete.is_(False),
            )
        )
    ).all()
    return {code: agent_id for code, agent_id in rows if code is not None}
