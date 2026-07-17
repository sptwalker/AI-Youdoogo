"""技能注册表（docs/13 §11）：智能体能力的统一注册、按 AI 启停与统一执行入口。

- 加新能力 = REGISTRY 加一行（+如需执行器实现 execute 签名）——base.py 与调用点零改动。
- 按 AI 启用：agent_role.tools 存技能 key；空列表 = 默认技能全开；非空 = 仅列表内合法 key。
- 双层开关：该 AI 启用 且 该技能的 sys_config 全局急停开着，才生效。
- 代码内注册表而非数据库表：技能是代码行为，注册表随代码走版本才安全。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.services import collab_protocol, config_service
from app.services.collab_protocol import ProtocolResult, fold_notes

if TYPE_CHECKING:
    from app.models.agent import AgentRole

__all__ = ["REGISTRY", "Skill", "enabled_skills", "execute_all", "fold_notes", "prompt_sections"]

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Skill:
    """一项智能体能力：提示词注入段 +（可选）产出指令执行器。"""

    key: str
    label: str  # UI 展示名
    description: str  # UI 提示
    flag_key: str  # sys_config 全局急停 key
    default_on: bool = True


REGISTRY: dict[str, Skill] = {
    "env_context": Skill(
        "env_context", "环境快照", "感知组织架构/AI花名册/真人用户/数据接口", "agent_env_context"
    ),
    "collab": Skill(
        "collab", "协作原语", "咨询其他AI + 发起跨部门协作（真人复核生效）", "agent_collab_protocol"
    ),
    "deliver": Skill(
        "deliver", "文件交付", "把产出整理成CSV/XLSX/文档交付到工作桌面", "agent_deliver"
    ),
    "data_query": Skill(
        "data_query", "数据取数", "用只读SQL查运营数据（护栏校验+审计）", "agent_data_query"
    ),
}


def enabled_skills(role: AgentRole) -> list[Skill]:
    """该 AI 启用的技能。tools 空 → 默认全开；非空 → 仅列表内合法 key（未知/非 str 忽略）。"""
    tools = [t for t in (role.tools or []) if isinstance(t, str)]
    if not (role.tools or []):
        return [s for s in REGISTRY.values() if s.default_on]
    return [REGISTRY[k] for k in tools if k in REGISTRY]


async def _flag_on(db: AsyncSession, skill: Skill) -> bool:
    """技能的 sys_config 全局急停（默认开；兼容 JSONB bool/str 两种存法）。"""
    flag = await config_service.resolve(db, skill.flag_key, True)
    return str(flag).lower() not in ("false", "0")


async def _section(db: AsyncSession, skill: Skill) -> str:
    """单个技能的提示词注入段（不生效/无内容返回空串）。"""
    if skill.key == "env_context":
        from app.services.environment_service import get_env_context

        snapshot = await get_env_context(db)
        if not snapshot:
            return ""
        return f"\n\n【系统环境快照】（由系统档案员维护，实时数据，可直接引用）\n{snapshot}"
    if skill.key == "collab":
        return collab_protocol.PROMPT_SECTION
    if skill.key == "deliver":
        from app.services import deliver_service

        return deliver_service.PROMPT_SECTION
    if skill.key == "data_query":
        from app.services import query_skill

        return await query_skill.prompt_section(db)
    return ""


async def prompt_sections(db: AsyncSession, role: AgentRole) -> str:
    """该 AI 全部生效技能的提示词段拼接。单技能故障吞掉记 warning，不阻断 AI 执行。"""
    parts: list[str] = []
    for skill in enabled_skills(role):
        try:
            if not await _flag_on(db, skill):
                continue
            parts.append(await _section(db, skill))
        except Exception:  # noqa: BLE001 - 单技能注入故障不阻断
            logger.warning("技能提示词段注入失败 skill=%s", skill.key, exc_info=True)
    return "".join(parts)


async def execute_all(
    db: AsyncSession, role: AgentRole, output: str, *,
    user_id: UUID | None = None, user_intent: str | None = None,
    exclude: set[str] | None = None,
) -> ProtocolResult:
    """对 AI 产出执行其启用技能的指令（collab + deliver + data_query），合并结果。永不 raise。

    技能各自解析自己的指令、独立容错；notes/consult_replies/datasets/artifacts 汇总到一个
    ProtocolResult，由调用方（desktop/discussion/meeting）统一折进消息、渲染咨询答复。

    - user_intent:透传用户原始诉求给取数技能，让其解读轮知道是否还需交付（阶段A,docs/14）。
    - exclude:跳过的技能 key（取数解读轮回调本函数时排除 data_query 防递归）。
    """
    from app.services import deliver_service, query_skill

    executors = {
        "collab": collab_protocol.execute,
        "deliver": deliver_service.execute,
        "data_query": query_skill.execute,
    }
    exclude = exclude or set()
    merged = ProtocolResult()
    for skill in enabled_skills(role):
        run = executors.get(skill.key)
        if run is None or skill.key in exclude:
            continue
        try:
            if not await _flag_on(db, skill):
                continue
            # 仅取数技能吃 user_intent/exclude；其余执行器签名无这些参数
            kw: dict[str, Any] = (
                {"user_intent": user_intent, "exclude": exclude}
                if skill.key == "data_query"
                else {}
            )
            part = await run(db, role, output, user_id=user_id, **kw)
            merged.notes.extend(part.notes)
            merged.consult_replies.extend(part.consult_replies)
            merged.datasets.extend(part.datasets)
            merged.artifacts.extend(part.artifacts)
        except Exception:  # noqa: BLE001 - 技能执行故障不连累业务消息流
            logger.warning("技能执行失败 skill=%s", skill.key, exc_info=True)
    return merged
