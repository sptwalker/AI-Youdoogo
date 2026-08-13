"""运营提案文本协议——解析 Agent 输出中的 【运营提案】<议题> 指令。

单步内部顾问输出（非红线）：把议题交给平台运营总监助理产出一份结构化运营提案（仅供管理层参考、
不构成决策，`notify=False` 无任何对外发送），把提案正文折回对话/编排。进 AUTOMATIC（编排步免红线）、
default_enabled=True。走文本指令路径（legacy_executor），无机械步、无结构化 executor。

★架构：本技能被 app.agents 装配，故绝不静态 import 触达 app.agents 的执行组合（agent_operations →
agent_execution.public → app.agents 会成环）。产提案改经编排注入的 execution_context.agent_runner
运行运营总监助理子 Agent（镜像嵌套会商），专家按 code 走 expert_management.public 目录端口取。
"""

from __future__ import annotations

import logging
import re
import uuid
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.contracts import (
    AgentSubject,
    ExecutionContext,
    SkillResult,
    agent_execution_result,
)
from app.contexts.foundations.execution.agent_execution.contracts.execution import (
    AgentExecutionStatus,
)
from app.contexts.foundations.workforce.expert_management.public import (
    build_local_expert_directory_port,
)

if TYPE_CHECKING:
    from app.contexts.foundations.workforce.expert_management.contracts.execution import (
        ExpertExecutionSnapshot,
    )

logger = logging.getLogger(__name__)

_MAX_PROPOSALS = 1  # 一轮至多产一份提案，避免单步刷屏
_PROPOSAL_RE = re.compile(r"【运营提案】\s*(.+)")
_OPS_DIRECTOR_CODE = "dir_platform_ops"  # 平台运营部总监助理（提案执行者）

PROMPT_SECTION = (
    "\n\n运营提案:当需要就某个运营议题产出一份可供管理层参考的优化提案时，单独一行写 "
    "【运营提案】<议题>；系统会请平台运营总监助理输出含背景/目标/方案/收益风险/优先级的提案"
    "（仅供参考、不构成最终决策，不对外发送）。"
)


def parse(output: str) -> list[str]:
    """从 Agent 文本解析至多 _MAX_PROPOSALS 个运营提案议题。"""
    topics = [topic.strip() for topic in _PROPOSAL_RE.findall(output or "") if topic.strip()]
    return topics[:_MAX_PROPOSALS]


async def _load_ops_director(db: AsyncSession) -> ExpertExecutionSnapshot | None:
    """按 code 取平台运营部总监助理执行快照（骨架未初始化 → None，如实缺席不臆造）。

    # ponytail: 复用 PublishedOperationalExpertAdapter.get_by_code 会连带 import
    # agent_execution.public → 触架构环；此处直接走 expert_management.public 目录端口（3 行），
    # 保持本技能对 app.agents 零静态依赖。骨架规模换更简查询时再抽公共 by_code helper。
    """
    directory = build_local_expert_directory_port(db)
    roster = await directory.list_roster(include_personal=True)
    match = next(
        (expert for expert in roster if expert.code == _OPS_DIRECTOR_CODE and expert.is_active),
        None,
    )
    return await directory.get_execution(match.expert_id) if match is not None else None


def _proposal_message(topic: str, context: str) -> str:
    """构造运营提案用户消息（与 agent_use_cases.proposal 口径一致，固定五段式）。"""
    reference = f"\n\n参考信息：\n{context}" if context.strip() else ""
    return (
        "请就以下运营议题输出一份运营优化提案，固定包含"
        "【背景与问题】【优化目标】【具体方案】【预期收益与风险】【优先级建议】五部分。"
        "提案仅供管理层参考，不构成最终决策。"
        f"\n\n议题：{topic}{reference}"
    )


async def execute(
    db: AsyncSession,
    initiator: AgentSubject | object,
    output: str,
    *,
    user_id: uuid.UUID | None = None,
    user_intent: str | None = None,
    execution_context: ExecutionContext | None = None,
) -> SkillResult:
    """把 Agent 文本里的运营提案指令交给运营总监助理产提案，正文折回对话/编排。"""
    del initiator
    result = SkillResult()
    try:
        topics = parse(output)
        if not topics:
            return result
        runner = getattr(execution_context, "agent_runner", None)
        if runner is None:
            # 无注入执行器（对话未接编排 runner）→ 如实声明、不臆造提案，不打断消息流
            result.notes.extend(f"运营提案「{topic}」未生成（无可用执行者）" for topic in topics)
            return result
        expert = await _load_ops_director(db)
        if expert is None:
            result.notes.extend(
                f"运营提案「{topic}」未生成（未配置平台运营部总监助理）" for topic in topics
            )
            return result
        context = user_intent or ""
        for topic in topics:
            outcome = agent_execution_result(
                await runner(
                    db,
                    expert,
                    task_type="proposal",
                    input_summary=f"运营提案：{topic[:40]}",
                    user_message=_proposal_message(topic, context),
                    user_id=user_id,
                    execution_context=execution_context,
                )
            )
            if outcome.status == AgentExecutionStatus.SUCCEEDED and outcome.content:
                result.artifacts.append(
                    {"kind": "operational_proposal", "topic": topic, "body": outcome.content}
                )
                result.notes.append(f"已生成运营提案：{topic}")
            else:
                result.notes.append(
                    f"运营提案「{topic}」未生成（{outcome.error_msg or '无产出'}）"
                )
    except Exception:  # noqa: BLE001 - 提案协议失败不得打断消息流
        logger.warning("运营提案协议处理失败", exc_info=True)
    return result


async def prompt_section() -> str:
    return PROMPT_SECTION


__all__ = ["PROMPT_SECTION", "execute", "parse", "prompt_section"]
