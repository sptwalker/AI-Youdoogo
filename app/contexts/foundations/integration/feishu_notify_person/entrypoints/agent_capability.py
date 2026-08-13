"""Agent 文本协议 adapter：定向飞书通知 compose 半（红线·点对点对外触达·真人确认后才发）。

红线两步拆分（镜像 compose_feishu→feishu_publish，docs/26 §8）：
- 本 compose（``feishu_notify_person``，红线·指令驱动）：把转发意图解析成**草稿 artifact**，
  ★零飞书调用★，执行后编排步停 ``waiting_human`` 等真人验收。草稿带
  ``publish_key="feishu_notify_person_publish"`` 供机械步统一路由。
- 机械发布半（``feishu_notify_person_publish``）由 workflow-runtime 机械步 + 组合根注入的
  MechanicalPublisher 按 publish_key 派发真发（见 policies.MECHANICAL_CAPABILITIES /
  bootstrap.workflow_events._FeishuMechanicalPublisher），对规划器/对话不可见（无 prompt_section、
  无 legacy adapter、不入 REGISTRY）。

区别于 feishu_notify（固定运营群单向播报，无停点）：本能力发到「指定 open_id 个人 / 指定 chat_id
群」，属点对点对外触达 → 红线。default_enabled=False：默认不进启用集、不广告，需管理员显式授予。
"""

from __future__ import annotations

import logging
import re
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.contracts import AgentSubject, ExecutionContext, SkillResult
from app.contexts.foundations.integration.feishu_notify_person.entrypoints import (
    operations,
)

logger = logging.getLogger(__name__)

_MAX_NOTIFIES = 3
# 一行指令头 + 收件人标识 + `|` + 同行正文（一行一条；`.` 默认不跨行 → 不吞并后续正文）。
_NOTIFY_RE = re.compile(r"【定向飞书】\s*(\S+?)\s*\|\s*(.+)")


def _is_chat(recipient: str) -> bool:
    """飞书群 chat_id 以 oc_ 开头，个人 open_id 以 ou_ 开头；据前缀选发送通道。"""
    return recipient.startswith("oc_")


def parse(output: str) -> list[dict[str, Any]]:
    """从 Agent 文本解析至多 _MAX_NOTIFIES 条定向通知草稿；★不触任何外部调用★。"""
    drafts: list[dict[str, Any]] = []
    for recipient, body in _NOTIFY_RE.findall(output or ""):
        text = body.strip()
        if recipient and text:
            drafts.append(
                {
                    "kind": "feishu_notify_person",
                    "publish_key": "feishu_notify_person_publish",
                    "recipient": recipient,
                    "is_chat": _is_chat(recipient),
                    "text": text,
                }
            )
    return drafts[:_MAX_NOTIFIES]


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
    """把 Agent 文本里的定向通知指令解析成草稿 artifact；★零飞书调用★，不打断消息流。"""
    del db, initiator, user_id, user_intent, exclude, execution_context
    result = SkillResult()
    try:
        drafts = parse(output)
        if not drafts:
            return result
        result.artifacts.extend(drafts)
        result.notes.append(
            f"已生成 {len(drafts)} 条定向飞书通知草稿，将在真人验收后自动发出"
        )
    except Exception:  # noqa: BLE001 - 定向通知协议失败不得打断消息流
        logger.warning("定向飞书通知协议处理失败", exc_info=True)
    return result


async def prompt_section() -> str:
    """仅当通知开关开才广告定向指令（自门控）；否则返空 → 生产逐字不变。"""
    if not operations.feishu_notify_person_available():
        return ""
    # ponytail: 对话路径只产草稿；真发只走编排验收→机械路径。对话侧一键批准 UI 显式推迟。
    return (
        "\n\n定向飞书通知:当需要把一条已确认的简报/结论转发给指定的人或群时，单独一行写 "
        "【定向飞书】<收件人标识>|<正文>；收件人标识为对方的飞书 open_id（个人，ou_ 开头）或 "
        "chat_id（群，oc_ 开头）。仅发送已确认无误的内容，每次回复最多 3 条。这是点对点对外触达，"
        "系统会先生成草稿、经真人验收后才真正发出。"
    )


__all__ = [
    "execute",
    "parse",
    "prompt_section",
]
