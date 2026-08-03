"""LLM and Agent adapters for best-effort output review."""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.execution.agent_execution.public import run_agent
from app.contexts.foundations.governance.ai_quality.domain.scoring import judge_score
from app.contexts.foundations.governance.usage_budget.public import (
    extract_usage,
    record_usage,
)
from app.llm import get_llm_for_role
from app.models.agent import AgentRole

logger = logging.getLogger(__name__)

_CRITIC_SYSTEM = (
    "你是严格的产出审校员。依据【审校标准】审查【AI产出】，找出其中的问题"
    "（事实错误、遗漏、逻辑漏洞、不切题、表述不清、可能的编造）。"
    "第一行只输出一个 1~5 的整数总分（1=问题严重，3=基本可用，5=优秀无明显问题）。"
    "之后逐条列出发现的具体问题（每行一条，无问题写「无」）。不要重写产出本身。"
)

LLMFactory = Callable[..., Any]
UsageRecorder = Callable[..., Awaitable[None]]
AgentRunner = Callable[..., Awaitable[Any]]


def parse_critic(critic_output: str) -> tuple[int, str]:
    text = (critic_output or "").strip()
    lines = text.splitlines()
    issues = "\n".join(lines[1:]).strip() if len(lines) > 1 else ""
    return judge_score(text), issues or "无"


class LangChainOutputCritic:
    def __init__(
        self,
        session: AsyncSession,
        *,
        llm_factory: LLMFactory = get_llm_for_role,
        usage_recorder: UsageRecorder = record_usage,
    ) -> None:
        self._session = session
        self._llm_factory = llm_factory
        self._usage_recorder = usage_recorder

    async def critique(
        self,
        *,
        rubric: str,
        task_context: str,
        output: str,
        user_id: uuid.UUID | None,
    ) -> tuple[int, str]:
        llm = self._llm_factory("meeting_expert", temperature=0.0)
        started = time.monotonic()
        reply = await llm.ainvoke(
            [
                SystemMessage(content=_CRITIC_SYSTEM),
                HumanMessage(
                    content=(
                        f"【审校标准】\n{rubric}\n\n【任务背景】\n{task_context[:800]}\n\n"
                        f"【AI产出】\n{output[:3000]}"
                    )
                ),
            ]
        )
        prompt_tokens, completion_tokens, total_tokens = extract_usage(reply)
        await self._usage_recorder(
            self._session,
            role="reflection_critic",
            model=str(reply.response_metadata.get("model_name") or "meeting_expert"),
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            duration_ms=int((time.monotonic() - started) * 1000),
            user_id=user_id,
        )
        content = reply.content if isinstance(reply.content, str) else str(reply.content)
        return parse_critic(content)


class AgentOutputRevision:
    def __init__(
        self,
        session: AsyncSession,
        *,
        runner: AgentRunner = run_agent,
    ) -> None:
        self._session = session
        self._runner = runner

    async def revise(
        self,
        *,
        expert_id: uuid.UUID,
        task_context: str,
        output: str,
        issues: str,
        user_id: uuid.UUID | None,
    ) -> str:
        role = await self._session.get(AgentRole, expert_id)
        if role is None or role.is_delete or not role.is_active:
            raise RuntimeError("output review expert is unavailable")
        record = await self._runner(
            self._session,
            role,
            task_type="reflection_revise",
            input_summary=f"反思重写:{task_context[:40]}",
            user_message=(
                "你之前对以下任务给出了一版产出，审校员指出了一些问题。"
                "请针对这些问题修订，给出改进后的完整产出（只输出修订后的产出正文）。\n\n"
                f"【任务】\n{task_context}\n\n【你的初稿】\n{output}\n\n"
                f"【审校员指出的问题】\n{issues}"
            ),
            user_id=user_id,
        )
        return record.output_content or ""


class LoggingOutputReviewFailureReporter:
    def record_failure(self, expert_id: uuid.UUID) -> None:
        logger.warning("反思回路失败，退回初稿 expert=%s", expert_id, exc_info=True)


__all__ = [
    "AgentOutputRevision",
    "LangChainOutputCritic",
    "LoggingOutputReviewFailureReporter",
    "parse_critic",
]
