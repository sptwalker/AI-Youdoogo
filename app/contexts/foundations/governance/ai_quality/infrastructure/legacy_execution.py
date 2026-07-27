"""Legacy Agent/LLM adapters behind AI Quality-owned ports."""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.governance.ai_quality.application.ports import (
    EvaluationJudgePort,
)
from app.contexts.foundations.governance.ai_quality.contracts.quality import (
    EvaluationCaseView,
    LowScoreSample,
)
from app.contexts.foundations.governance.ai_quality.domain.scoring import judge_score
from app.contexts.foundations.model_gateway.contracts.completion import (
    LlmCompletionPort,
    LlmCompletionRequest,
)
from app.contexts.foundations.workforce.expert_management.contracts.execution import (
    ExpertExecutionSnapshot,
)
from app.models.agent import AgentRole, AgentTaskRecord

_JUDGE_SYSTEM = (
    "你是严格的 AI 输出评审员。依据给定的【评分标准】，对【AI产出】打 1~5 分整数分"
    "（1=完全不满足，3=基本满足，5=优秀）。"
    "第一行只输出分数数字，第二行给一句简短理由。不要输出其它内容。"
)
_OPTIMIZER_SYSTEM = (
    "你是提示词优化专家。基于给定的『当前系统提示词』和若干『低分产出 + 人工评语』，"
    "诊断提示词的不足，产出一版改进后的完整系统提示词。"
    "只输出改进后的提示词正文，保持角色定位不变，针对评语反映的问题做增强。"
)


UsageRecorder = Callable[..., Awaitable[None]]
AgentRunner = Callable[..., Awaitable[AgentTaskRecord]]
JudgeCallable = Callable[[AsyncSession, str, str, uuid.UUID | None], Awaitable[int]]


def _permission_value(value: str) -> object:
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def role_from_snapshot(snapshot: ExpertExecutionSnapshot, prompt: str) -> AgentRole:
    return AgentRole(
        id=snapshot.expert_id,
        name=snapshot.name,
        title=snapshot.title,
        department_id=snapshot.department_id,
        prompt_template=prompt,
        model_role=snapshot.model_role,
        tools=list(snapshot.capability_keys),
        permission_scope={
            key: _permission_value(value) for key, value in snapshot.permission_entries
        },
        owner_user_id=snapshot.owner_user_id,
        is_active=True,
    )


class LegacyAgentEvaluationExecutor:
    def __init__(self, session: AsyncSession, runner: AgentRunner) -> None:
        self._session = session
        self._runner = runner

    async def execute(
        self,
        subject: ExpertExecutionSnapshot,
        prompt: str,
        case: EvaluationCaseView,
        user_id: uuid.UUID | None,
    ) -> str:
        record = await self._runner(
            self._session,
            role_from_snapshot(subject, prompt),
            task_type="eval_run",
            input_summary=f"评估:{case.name[:40]}",
            user_message=case.input_text,
            user_id=user_id,
        )
        return record.output_content or record.error_msg or ""


class CallbackEvaluationJudge:
    def __init__(self, session: AsyncSession, callback: JudgeCallable) -> None:
        self._session = session
        self._callback = callback

    async def score(
        self, rubric: str, output: str, user_id: uuid.UUID | None
    ) -> int:
        return await self._callback(self._session, rubric, output, user_id)


class CompletionEvaluationJudge:
    def __init__(
        self,
        session: AsyncSession,
        *,
        port: LlmCompletionPort,
        usage_recorder: UsageRecorder,
    ) -> None:
        self._session = session
        self._port = port
        self._usage_recorder = usage_recorder

    async def score(
        self, rubric: str, output: str, user_id: uuid.UUID | None
    ) -> int:
        started = time.monotonic()
        resp = await self._port.invoke(
            LlmCompletionRequest(
                model_role="meeting_expert",
                system_prompt=_JUDGE_SYSTEM,
                user_message=f"【评分标准】\n{rubric}\n\n【AI产出】\n{output[:2000]}",
                temperature=0.0,
            )
        )
        await self._usage_recorder(
            self._session,
            role="eval_judge",
            model=resp.model or "meeting_expert",
            prompt_tokens=resp.usage.prompt_tokens,
            completion_tokens=resp.usage.completion_tokens,
            total_tokens=resp.usage.total_tokens,
            duration_ms=int((time.monotonic() - started) * 1000),
            user_id=user_id,
        )
        return judge_score(resp.content)


class CompletionPromptSuggestion:
    def __init__(
        self,
        session: AsyncSession,
        *,
        port: LlmCompletionPort,
        usage_recorder: UsageRecorder,
    ) -> None:
        self._session = session
        self._port = port
        self._usage_recorder = usage_recorder

    async def suggest(
        self,
        current_prompt: str,
        samples: tuple[LowScoreSample, ...],
        user_id: uuid.UUID | None,
    ) -> str:
        sample_text = "\n\n".join(
            f"[{index + 1}] 评分 {sample.score}/5，评语：{sample.comment or '（无）'}"
            f"\n产出摘要：{sample.output[:300]}"
            for index, sample in enumerate(samples)
        )
        started = time.monotonic()
        resp = await self._port.invoke(
            LlmCompletionRequest(
                model_role="meeting_expert",
                system_prompt=_OPTIMIZER_SYSTEM,
                user_message=f"当前系统提示词：\n{current_prompt}\n\n低分样本：\n{sample_text}",
                temperature=0.4,
            )
        )
        await self._usage_recorder(
            self._session,
            role="prompt_optimizer",
            model=resp.model or "meeting_expert",
            prompt_tokens=resp.usage.prompt_tokens,
            completion_tokens=resp.usage.completion_tokens,
            total_tokens=resp.usage.total_tokens,
            duration_ms=int((time.monotonic() - started) * 1000),
            user_id=user_id,
        )
        return resp.content


def ensure_judge_port(value: EvaluationJudgePort) -> EvaluationJudgePort:
    return value
