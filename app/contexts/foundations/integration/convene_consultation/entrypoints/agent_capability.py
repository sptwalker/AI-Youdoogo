"""紧急会商编排文本协议——解析 Agent 输出中的 【紧急会商】<议题> 指令（compose 半）。

红线两步拆分（镜像 feishu_notify_person compose→机械发布，docs/26 §8）：
- 本 compose（``convene_consultation``，红线·指令驱动）：把会商议题解析成**草稿 artifact**，
  ★零建会、零通知★，执行后编排步停 ``waiting_human`` 等真人验收。草稿带
  ``publish_key="convene_consultation_publish"`` 供机械步统一路由，并把发起人 ``creator_id``
  嵌进草稿（机械发布器只拿到 draft、无 session/user_id）。
- 机械会商半（``convene_consultation_publish``）由 workflow-runtime 机械步 + 组合根注入的
  MechanicalPublisher 按 publish_key 派发真建会 + 定向通知（见 policies.MECHANICAL_CAPABILITIES /
  bootstrap.workflow_events._FeishuMechanicalPublisher），对规划器/对话不可见（无 prompt_section、
  无 legacy adapter、不入 REGISTRY）。
"""

from __future__ import annotations

import logging
import re
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.contracts import AgentSubject, ExecutionContext, SkillResult

logger = logging.getLogger(__name__)

_MAX_CONVENE = 1  # 一轮编排步只处理一次紧急会商拉起，避免单步意外建多场会
_CONVENE_RE = re.compile(r"【紧急会商】\s*(.+)")


def parse(output: str) -> list[dict[str, Any]]:
    """从 Agent 文本解析至多 _MAX_CONVENE 条会商草稿；★不触任何外部调用★。"""
    drafts = [
        {
            "kind": "convene_consultation",
            "publish_key": "convene_consultation_publish",
            "topic": topic.strip(),
        }
        for topic in _CONVENE_RE.findall(output or "")
        if topic.strip()
    ]
    return drafts[:_MAX_CONVENE]


async def execute(
    db: AsyncSession,
    initiator: AgentSubject | object,
    output: str,
    *,
    user_id: uuid.UUID | None = None,
    user_intent: str | None = None,
    exclude: set[str] | None = None,
    execution_context: ExecutionContext | None = None,
) -> SkillResult:
    """把 Agent 文本里的会商指令解析成草稿 artifact；★零建会、零通知★，不打断消息流。"""
    del db, initiator, user_intent, exclude, execution_context
    result = SkillResult()
    try:
        drafts = parse(output)
        if not drafts:
            return result
        # 机械会商步只拿到 draft（无 session/user_id）→ 在此把发起人嵌进草稿，供 publish 建会。
        # 缺 user_id（无发起人）时草稿不带 creator_id，机械步据此如实跳过、不臆造发起人。
        for draft in drafts:
            if user_id is not None:
                draft["creator_id"] = str(user_id)
        result.artifacts.extend(drafts)
        result.notes.append(
            "已生成紧急会商草稿，将在真人验收后自动建会并定向通知"
        )
    except Exception:  # noqa: BLE001 - 会商编排协议失败不得打断消息流
        logger.warning("紧急会商编排协议处理失败", exc_info=True)
    return result


async def prompt_section() -> str:
    # ponytail: 对话路径只产草稿；真建会/通知只走编排验收→机械路径。对话侧一键批准 UI 显式推迟
    # （docs/26 §8）。
    return (
        "\n\n紧急会商:当研判需要立刻拉起跨部门紧急会商时，单独一行写 【紧急会商】<议题>；"
        "系统会先生成草稿、经真人验收后才真正建会并定向通知品牌/销售/产品/法务负责人"
        "（本步为红线动作，需真人确认后才真正发起）。"
    )


__all__ = [
    "execute",
    "parse",
    "prompt_section",
]
