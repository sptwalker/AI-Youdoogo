"""Skill descriptors, feature gates, and prompt metadata."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.contracts import SkillExecutor
from app.agents.legacy_skill_adapters import (
    LegacyExecutor,
    legacy_collab,
    legacy_deliver,
    legacy_query,
)
from app.models.agent import AgentRole
from app.services import config_service

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Skill:
    """One source of truth for skill prompt metadata and executor registration."""

    key: str
    label: str
    description: str
    flag_key: str
    default_on: bool = True
    executor_factory: Callable[[], SkillExecutor] | None = None
    legacy_executor: LegacyExecutor | None = None


def _collab_executor() -> SkillExecutor:
    from app.services.collab_protocol import CollabSkillExecutor

    return CollabSkillExecutor()


def _deliver_executor() -> SkillExecutor:
    from app.services.deliver_service import DeliverySkillExecutor

    return DeliverySkillExecutor()


def _query_executor() -> SkillExecutor:
    from app.services.query_skill import DataQuerySkillExecutor

    return DataQuerySkillExecutor()


REGISTRY: dict[str, Skill] = {
    "env_context": Skill(
        "env_context",
        "环境快照",
        "感知组织架构/AI花名册/真人用户/数据接口",
        "agent_env_context",
    ),
    "collab": Skill(
        "collab",
        "协作原语",
        "咨询其他AI + 发起跨部门协作（真人复核生效）",
        "agent_collab_protocol",
        executor_factory=_collab_executor,
        legacy_executor=legacy_collab,
    ),
    "deliver": Skill(
        "deliver",
        "文件交付",
        "把产出整理成CSV/XLSX/文档交付到工作桌面",
        "agent_deliver",
        executor_factory=_deliver_executor,
        legacy_executor=legacy_deliver,
    ),
    "data_query": Skill(
        "data_query",
        "数据取数",
        "用只读SQL查运营数据（护栏校验+审计）",
        "agent_data_query",
        executor_factory=_query_executor,
        legacy_executor=legacy_query,
    ),
}


def enabled_skills(role: AgentRole) -> list[Skill]:
    """Return enabled skills; an empty tools list means all defaults are enabled."""
    tools = [item for item in (role.tools or []) if isinstance(item, str)]
    if not (role.tools or []):
        return [skill for skill in REGISTRY.values() if skill.default_on]
    return [REGISTRY[key] for key in tools if key in REGISTRY]


async def flag_on(db: AsyncSession, skill: Skill) -> bool:
    flag = await config_service.resolve(db, skill.flag_key, True)
    return str(flag).lower() not in ("false", "0")


async def _section(db: AsyncSession, skill: Skill) -> str:
    if skill.key == "env_context":
        from app.services.environment_service import get_env_context

        snapshot = await get_env_context(db)
        if not snapshot:
            return ""
        return f"\n\n【系统环境快照】（由系统档案员维护，实时数据，可直接引用）\n{snapshot}"
    if skill.key == "collab":
        from app.services.collab_protocol import PROMPT_SECTION

        return PROMPT_SECTION
    if skill.key == "deliver":
        from app.services.deliver_service import PROMPT_SECTION

        return PROMPT_SECTION
    if skill.key == "data_query":
        from app.services.query_skill import prompt_section

        return await prompt_section(db)
    return ""


async def prompt_sections(db: AsyncSession, role: AgentRole) -> str:
    """Build enabled prompt sections while isolating individual skill failures."""
    parts: list[str] = []
    for skill in enabled_skills(role):
        try:
            if await flag_on(db, skill):
                parts.append(await _section(db, skill))
        except Exception:  # noqa: BLE001 - one prompt failure must not block the agent
            logger.warning("技能提示词段注入失败 skill=%s", skill.key, exc_info=True)
    return "".join(parts)
