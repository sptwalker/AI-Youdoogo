"""发送邮件编排文本协议——解析 Agent 输出中的 【发送邮件】<账号>|<主题>|<正文>（compose 半）。

红线两步拆分（镜像 convene_consultation compose→机械发布，docs/26 §8）：
- 本 compose（``send_email``，红线·外部写·指令驱动）：把邮件指令解析成**草稿 artifact**，
  ★零发送★，执行后编排步停 ``waiting_human`` 等真人验收。草稿带
  ``publish_key="send_email_publish"`` 供机械步统一路由。收件人按 ``username`` 在发布时解析邮箱，
  故无需像 convene 那样嵌 creator_id。
- 机械发送半（``send_email_publish``）由 workflow-runtime 机械步 + 组合根注入的
  MechanicalPublisher 按 publish_key 派发真发送（自开 session → operations.send_to_username），
  对规划器/对话不可见（无 prompt_section、无 legacy adapter、不入 REGISTRY）。
"""

from __future__ import annotations

import logging
import re
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.contracts import AgentSubject, ExecutionContext, SkillResult

logger = logging.getLogger(__name__)

_MAX_EMAILS = 3  # 一轮编排步至多解析 3 封邮件，避免单步意外群发
# 【发送邮件】<账号>|<主题>|<正文>，正文可跨行，读到下一条【或文末为止
_EMAIL_RE = re.compile(
    r"^【发送邮件】\s*(\S+?)\s*\|\s*([^\n|]+?)\s*\|\s*(.+?)(?=\n【|\Z)",
    re.DOTALL | re.MULTILINE,
)


def parse(output: str) -> list[dict[str, Any]]:
    """从 Agent 文本解析至多 _MAX_EMAILS 条邮件草稿；★不触任何外部调用★。"""
    drafts = [
        {
            "kind": "email",
            "publish_key": "send_email_publish",
            "username": username.strip(),
            "subject": subject.strip(),
            "body": body.strip(),
        }
        for username, subject, body in _EMAIL_RE.findall(output or "")
        if username.strip() and subject.strip() and body.strip()
    ]
    return drafts[:_MAX_EMAILS]


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
    """把 Agent 文本里的发信指令解析成草稿 artifact；★零发送★，不打断消息流。"""
    del db, initiator, user_id, user_intent, exclude, execution_context
    result = SkillResult()
    try:
        drafts = parse(output)
        if not drafts:
            return result
        result.artifacts.extend(drafts)
        result.notes.append("已生成邮件草稿，将在真人验收后自动发送")
    except Exception:  # noqa: BLE001 - 发信编排协议失败不得打断消息流
        logger.warning("发送邮件编排协议处理失败", exc_info=True)
    return result


async def prompt_section() -> str:
    # ponytail: 对话路径只产草稿；真发送只走编排验收→机械路径。对话侧一键批准 UI 显式推迟。
    return (
        "\n\n发送邮件:当需要给指定同事发一封工作邮件时，单独一行写 "
        "【发送邮件】<账号>|<主题>|<正文>；系统会先生成草稿、经真人验收后才真正发送"
        "（本步为红线外部写动作，需真人确认后才真正发出）。"
    )


__all__ = [
    "execute",
    "parse",
    "prompt_section",
]
