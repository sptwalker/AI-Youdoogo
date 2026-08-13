"""飞书文档/多维表格输出的 Agent 能力（compose 半，红线·指令驱动）。

``compose_feishu``：把 Agent 文本里的 ``【整理飞书文档】`` / ``【整理多维表格】`` 指令解析成草稿
artifact，★零调飞书★，草稿呈现给真人验收。发布前必经真人确认。

# ponytail: 机械发布半（草稿→真人验收→机械 feishu_publish）依赖 workflow-runtime 的机械步编排
# （MECHANICAL_CAPABILITIES + 步配对 + publish_key 路由 + 跳过-agent 分支），远端 2-Port 重构已删。
# 该编排是 notify/email/convene/report/舆情所有 compose→发布模块的共享前置，留待跨模块专项统一重建；
# 届时消费 operations.run_publish / infrastructure.publisher（已就绪）。本模块仅落地 compose 半。
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.contracts import AgentSubject, ExecutionContext, SkillResult

logger = logging.getLogger(__name__)

_MAX_DRAFTS = 2
# 一行指令头 + 紧随的 ``` 代码块正文；DOTALL 让正文跨行。
_DOC_RE = re.compile(
    r"【整理飞书文档】\s*标题[：:]\s*([^\n]+?)\s*\n+```[^\n]*\n(.*?)\n?```",
    re.DOTALL,
)
_TABLE_RE = re.compile(
    r"【整理多维表格】\s*表格[：:]\s*([^\s/]+)/(\S+?)\s*\n+```[^\n]*\n(.*?)\n?```",
    re.DOTALL,
)


def parse(output: str) -> list[dict[str, Any]]:
    """从 Agent 文本解析飞书草稿（docx / bitable），至多 _MAX_DRAFTS 份；★不触任何外部调用★。"""
    drafts: list[dict[str, Any]] = []
    for title, body in _DOC_RE.findall(output or ""):
        if title.strip() and body.strip():
            drafts.append(
                {
                    "kind": "docx",
                    "publish_key": "feishu_publish",
                    "title": title.strip(),
                    "body": body.strip(),
                }
            )
    for app_token, table_id, body in _TABLE_RE.findall(output or ""):
        records = _parse_records(body)
        if app_token.strip() and table_id.strip() and records:
            drafts.append(
                {
                    "kind": "bitable",
                    "publish_key": "feishu_publish",
                    "app_token": app_token.strip(),
                    "table_id": table_id.strip(),
                    "records": records,
                }
            )
    return drafts[:_MAX_DRAFTS]


def _parse_records(body: str) -> list[dict[str, Any]]:
    try:
        data = json.loads(body)
    except (json.JSONDecodeError, TypeError):
        return []
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict)]


def _draft_label(draft: dict[str, Any]) -> str:
    if draft.get("kind") == "docx":
        return str(draft.get("title") or "未命名文档")
    return f"多维表格 {draft.get('table_id', '')}"


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
    """把 Agent 文本里的飞书整理指令解析成草稿 artifact；★零飞书调用★，不打断消息流。"""
    del db, initiator, user_id, user_intent, exclude, execution_context
    result = SkillResult()
    try:
        drafts = parse(output)
        if not drafts:
            return result
        result.artifacts.extend(drafts)
        names = "、".join(_draft_label(draft) for draft in drafts)
        result.notes.append(f"已生成飞书发布草稿（{names}），将在真人验收后自动发布")
    except Exception:  # noqa: BLE001 - 草稿解析失败不得打断消息流
        logger.warning("飞书草稿整理失败", exc_info=True)
    return result


async def prompt_section() -> str:
    """仅当飞书凭证已配时广告飞书整理指令（自门控）；未配返空 → 规划器/对话都不产飞书步。"""
    from app.contexts.foundations.integration.feishu_output.entrypoints import operations

    if not await operations.feishu_output_available():
        return ""
    return (
        "\n\n整理成飞书文档/多维表格：当用户要把内容发布成飞书云文档或写入多维表格时，单独写指令，"
        "系统会先生成草稿、经真人验收后才自动发布到飞书（发布前必经真人确认）。\n"
        "- 云文档：写一行 【整理飞书文档】标题：<标题>，紧接一个 ``` 代码块放正文"
        "（#/##/### 开头的行会成为标题）。\n"
        "- 多维表格：写一行 【整理多维表格】表格：<app_token>/<table_id>，紧接一个 ``` "
        '代码块放 JSON 记录数组（形如 [{"字段":"值"}]）。\n'
        "每次最多整理 2 份；这些内容先以草稿呈现、经真人确认后才真正发布。"
    )


__all__ = [
    "execute",
    "parse",
    "prompt_section",
]
