"""结构化分层记忆（H3.2，docs/16）：对话归档时提炼成结构化记忆，替代整段 transcript 硬存。

评审判定:原"长期记忆是弱RAG"——整段对话归档进 KB、无摘要/实体抽取，检索质量差。
本模块在归档前先 LLM 提炼:摘要 + 关键事实/决定 + 涉及实体 + 用户偏好，存提炼版(更易检索)。
提炼失败 → 兜底存原始 transcript（绝不丢数据）。红线:记忆只是资料，不触发任何决议。
"""

from __future__ import annotations

import logging
import time
import uuid

from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm import get_llm_for_role
from app.llm.usage import extract_usage, record_usage

logger = logging.getLogger(__name__)

_DISTILL_SYSTEM = (
    "你是记忆整理助手。把一段对话记录提炼成结构化的长期记忆，供日后检索。"
    "严格按以下结构输出（无对应内容的小节写「无」）：\n"
    "## 摘要\n（2~4 句话概括这段对话谈了什么）\n"
    "## 关键事实与决定\n（逐条列出确定的事实、结论、达成的决定；无则写「无」）\n"
    "## 涉及实体\n（人名/项目/产品/部门/指标等专有名词，逗号分隔）\n"
    "## 用户偏好与习惯\n（对方表达的偏好、要求、工作习惯；无则写「无」）\n"
    "只输出上述结构化内容，不要寒暄，不要编造未出现的信息。"
)


def build_distill_input(transcript: str) -> str:
    """构造提炼输入（纯函数，便于测试/复用）。"""
    return f"请提炼以下对话记录：\n\n{transcript[:8000]}"


async def distill_conversation(
    db: AsyncSession, transcript: str, *, user_id: uuid.UUID | None = None
) -> str | None:
    """把对话 transcript 提炼成结构化记忆。失败返回 None（调用方兜底存原文）。永不 raise。"""
    if not transcript.strip():
        return None
    try:
        llm = get_llm_for_role("default", temperature=0.2)
        t0 = time.monotonic()
        reply = await llm.ainvoke([
            SystemMessage(content=_DISTILL_SYSTEM),
            HumanMessage(content=build_distill_input(transcript)),
        ])
        p, c, t = extract_usage(reply)
        await record_usage(
            db, role="memory_distill",
            model=str(reply.response_metadata.get("model_name") or "default"),
            prompt_tokens=p, completion_tokens=c, total_tokens=t,
            duration_ms=int((time.monotonic() - t0) * 1000), user_id=user_id,
        )
        text = reply.content if isinstance(reply.content, str) else str(reply.content)
        return text.strip() or None
    except Exception:  # noqa: BLE001 - 提炼失败不阻断归档，调用方兜底存原文
        logger.warning("对话记忆提炼失败，将回退存原始存档", exc_info=True)
        return None
