"""反馈评分 + 提示词优化链（docs/06 阶段5 自进化主链）。

评分（1~5）累积到某角色的低分样本后，可让模型基于「当前提示词 + 低分产出 + 评语」
产出一版改进提示词——仅作建议返回，须真人确认后经 agent_role_service.update 落地
（红线：AI 仅建议权，提示词变更由真人生效）。
"""

from __future__ import annotations

import time
import uuid

from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.shared_kernel import ResourceNotFound, RuleViolation
from app.llm import get_llm_for_role
from app.llm.usage import extract_usage, record_usage
from app.models.agent import AgentRole, AgentTaskRecord
from app.models.feedback import AgentFeedback

_OPTIMIZER_SYSTEM = (
    "你是提示词优化专家。基于给定的『当前系统提示词』和若干『低分产出 + 人工评语』，"
    "诊断提示词的不足，产出一版改进后的完整系统提示词。"
    "只输出改进后的提示词正文，保持角色定位不变，针对评语反映的问题做增强。"
)


async def add_feedback(
    db: AsyncSession,
    *,
    task_record_id: uuid.UUID,
    rater_id: uuid.UUID,
    score: int,
    comment: str | None = None,
) -> AgentFeedback:
    """给一条智能体执行记录打分（1~5）。"""
    if not 1 <= score <= 5:
        raise RuleViolation("评分需为 1~5")
    record = await db.get(AgentTaskRecord, task_record_id)
    if record is None or record.is_delete:
        raise ResourceNotFound("执行记录不存在")
    fb = AgentFeedback(
        task_record_id=task_record_id, rater_id=rater_id, score=score, comment=comment
    )
    db.add(fb)
    await db.commit()
    await db.refresh(fb)
    return fb


async def _collect_low_scored(
    db: AsyncSession, role_id: uuid.UUID, threshold: int, limit: int
) -> list[tuple[str, int, str | None]]:
    """取某角色最近的低分样本 (产出, 分数, 评语)。"""
    stmt = (
        select(AgentTaskRecord.output_content, AgentFeedback.score, AgentFeedback.comment)
        .join(AgentFeedback, AgentFeedback.task_record_id == AgentTaskRecord.id)
        .where(AgentTaskRecord.agent_role_id == role_id, AgentFeedback.score <= threshold)
        .order_by(AgentFeedback.create_time.desc())
        .limit(limit)
    )
    return [(o or "", s, c) for o, s, c in (await db.execute(stmt)).all()]


async def optimize_prompt(
    db: AsyncSession,
    role_id: uuid.UUID,
    *,
    threshold: int = 3,
    limit: int = 20,
    user_id: uuid.UUID | None = None,
) -> dict[str, object]:
    """基于低分反馈产出改进版提示词（仅建议，不自动落地）。

    Raises:
        ApplicationError: 角色不存在 / 无低分样本可供优化。
    """
    role = await db.get(AgentRole, role_id)
    if role is None or role.is_delete:
        raise ResourceNotFound("智能体角色不存在")
    samples = await _collect_low_scored(db, role_id, threshold, limit)
    if not samples:
        raise RuleViolation(f"该角色暂无评分≤{threshold}的反馈，无需优化")

    sample_text = "\n\n".join(
        f"[{i + 1}] 评分 {s}/5，评语：{c or '（无）'}\n产出摘要：{o[:300]}"
        for i, (o, s, c) in enumerate(samples)
    )
    llm = get_llm_for_role("meeting_expert", temperature=0.4)  # reasoning 档位做优化
    t0 = time.monotonic()
    reply = await llm.ainvoke(
        [
            SystemMessage(content=_OPTIMIZER_SYSTEM),
            HumanMessage(
                content=f"当前系统提示词：\n{role.prompt_template}\n\n低分样本：\n{sample_text}"
            ),
        ]
    )
    p_tok, c_tok, t_tok = extract_usage(reply)
    await record_usage(
        db, role="prompt_optimizer",
        model=str(reply.response_metadata.get("model_name") or "meeting_expert"),
        prompt_tokens=p_tok, completion_tokens=c_tok, total_tokens=t_tok,
        duration_ms=int((time.monotonic() - t0) * 1000), user_id=user_id,
    )
    suggested = reply.content if isinstance(reply.content, str) else str(reply.content)
    return {
        "role_id": str(role_id),
        "current_prompt": role.prompt_template,
        "suggested_prompt": suggested,
        "based_on_samples": len(samples),
    }
