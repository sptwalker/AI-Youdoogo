"""Agent 文本协议 adapter：飞书运营群播报（运维旁路·无真人停点·仅播报已确认内容）。

用户已定为运维旁路播报：复用 ``notify.push_ops_message`` 推固定运营群，受 feishu_notify_enabled
控制、默认关 → prompt_section 返空不广告、run_broadcast no-op。播报到固定内部运营群、非点对点
对外发布，故无红线停点（用户决策）；note 提示「仅播报已确认内容」。终止型副作用：不做知识库
综合、不链式派发（区别于 read_url / web_search 的 interpret 回喂环）。
"""

from __future__ import annotations

import logging
import re
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.contracts import AgentSubject, ExecutionContext, SkillResult
from app.contexts.foundations.integration.feishu_notify.entrypoints import operations

logger = logging.getLogger(__name__)

_MAX_BROADCASTS = 2
# 一行指令头 + 同行内容（播报内容一行一条；`.` 默认不跨行 → 不吞并后续正文）。
_BROADCAST_RE = re.compile(r"【飞书播报】\s*(.+)")


def parse(output: str) -> list[str]:
    """从 Agent 文本解析至多 _MAX_BROADCASTS 条播报内容；★不触任何外部调用★。"""
    messages: list[str] = []
    for line in _BROADCAST_RE.findall(output or ""):
        text = line.strip()
        if text:
            messages.append(text)
    return messages[:_MAX_BROADCASTS]


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
    """解析并向运营群播报；开关关/未配置 → no-op。任何协议失败都不打断消息流。"""
    del db, initiator, user_id, user_intent, exclude, execution_context
    result = SkillResult()
    try:
        messages = parse(output)
        if not messages:
            return result
        for text in messages:
            sent = await operations.run_broadcast(text)
            if sent:
                result.notes.append("已向运营群播报（仅播报已确认内容）")
            else:
                result.notes.append("运营群播报未生效（未开启通知或未配置运营群）")
    except Exception:  # noqa: BLE001 - 播报协议失败不得打断消息流
        logger.warning("飞书播报协议处理失败", exc_info=True)
    return result


async def prompt_section() -> str:
    """仅当播报开关开且运营群已配才广告播报指令（自门控）；否则返空 → 生产逐字不变。"""
    if not operations.feishu_notify_available():
        return ""
    return (
        "\n\n飞书运营群播报:当用户明确要把一条已确认的结论/通知播报到运营群时，单独一行写 "
        "【飞书播报】<要播报的内容>，系统会把该内容推送到固定运营群。仅播报已确认无误的内容，"
        "每次回复最多 2 条；这是发到固定内部运营群的单向通知，不要用于对外发布或点对点通知个人。"
    )


__all__ = ["execute", "parse", "prompt_section"]
