"""评估驱动服务（H3.1，docs/16）：LLM-as-Judge 打分 + 跑评估集 + 影子对比。

- judge_score:纯函数解析 judge 产出的分数（1~5，容错兜底 3）。
- run_eval:用某提示词跑全部适用用例，逐条 judge 打分，返回聚合分 + 明细。
- shadow_compare:当前 vs 候选提示词各跑一遍评估集，对比得分——量化"改提示词是否变好"。
红线:评估只出分数/建议，提示词是否应用仍真人确认（不自动落地）。
"""

from __future__ import annotations

import re
import time
import uuid
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.shared_kernel import ResourceNotFound, RuleViolation
from app.llm import get_llm_for_role
from app.llm.usage import extract_usage, record_usage
from app.models.agent import AgentRole
from app.models.eval_case import EvalCase

_JUDGE_SYSTEM = (
    "你是严格的 AI 输出评审员。依据给定的【评分标准】，对【AI产出】打 1~5 分整数分"
    "（1=完全不满足，3=基本满足，5=优秀）。"
    "第一行只输出分数数字，第二行给一句简短理由。不要输出其它内容。"
)
_SCORE_RE = re.compile(r"([1-5])")


def judge_score(judge_output: str) -> int:
    """从 judge 产出解析 1~5 分（纯函数）。取首个 1~5 数字;解析不出兜底 3（中性）。"""
    lines = (judge_output or "").strip().splitlines()
    first = lines[0] if lines else ""
    m = _SCORE_RE.search(first)
    if m:
        return int(m.group(1))
    m2 = _SCORE_RE.search(judge_output or "")  # 全文兜底找一个
    return int(m2.group(1)) if m2 else 3


async def _judge(db: AsyncSession, rubric: str, output: str, user_id: uuid.UUID | None) -> int:
    """LLM-as-Judge:按 rubric 给 output 打分。"""
    llm = get_llm_for_role("meeting_expert", temperature=0.0)  # reasoning 档 + 温度0求稳定
    t0 = time.monotonic()
    reply = await llm.ainvoke([
        SystemMessage(content=_JUDGE_SYSTEM),
        HumanMessage(content=f"【评分标准】\n{rubric}\n\n【AI产出】\n{output[:2000]}"),
    ])
    p, c, t = extract_usage(reply)
    await record_usage(
        db, role="eval_judge",
        model=str(reply.response_metadata.get("model_name") or "meeting_expert"),
        prompt_tokens=p, completion_tokens=c, total_tokens=t,
        duration_ms=int((time.monotonic() - t0) * 1000), user_id=user_id,
    )
    text = reply.content if isinstance(reply.content, str) else str(reply.content)
    return judge_score(text)


async def _applicable_cases(db: AsyncSession, role_id: uuid.UUID) -> list[EvalCase]:
    """某角色适用的 active 用例 = 绑定该角色的 ∪ 通用（role_id 为空）。"""
    stmt = select(EvalCase).where(
        EvalCase.is_active.is_(True), EvalCase.is_delete.is_(False),
        or_(EvalCase.role_id == role_id, EvalCase.role_id.is_(None)),
    )
    return list((await db.execute(stmt)).scalars())


async def _run_prompt_on_cases(
    db: AsyncSession, role: AgentRole, prompt: str, cases: list[EvalCase],
    user_id: uuid.UUID | None,
) -> dict[str, Any]:
    """用指定提示词跑一组用例，逐条 judge 打分，返回 {avg, count, details}。"""
    from app.agents.base import run_agent

    # 临时用候选提示词跑（不落库改角色）：run_agent 读 role.prompt_template，
    # 故在内存态临时替换、跑完还原，避免污染真实角色。
    original = role.prompt_template
    scores: list[int] = []
    details: list[dict[str, Any]] = []
    try:
        role.prompt_template = prompt
        for case in cases:
            rec = await run_agent(
                db, role, task_type="eval_run",
                input_summary=f"评估:{case.name[:40]}",
                user_message=case.input_text, user_id=user_id,
            )
            output = rec.output_content or rec.error_msg or ""
            s = await _judge(db, case.rubric, output, user_id)
            scores.append(s)
            details.append({"case": case.name, "score": s})
    finally:
        role.prompt_template = original  # 还原，绝不把候选提示词落到角色
    avg = round(sum(scores) / len(scores), 3) if scores else 0.0
    return {"avg": avg, "count": len(scores), "details": details}


async def run_eval(
    db: AsyncSession, role_id: uuid.UUID, *,
    prompt: str | None = None, user_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    """用当前（或指定）提示词跑该角色的评估集，返回聚合分 + 明细。"""
    role = await db.get(AgentRole, role_id)
    if role is None or role.is_delete:
        raise ResourceNotFound("智能体角色不存在")
    cases = await _applicable_cases(db, role_id)
    if not cases:
        raise RuleViolation("该角色暂无可用评估用例，请先在评估集中添加")
    result = await _run_prompt_on_cases(
        db, role, prompt or role.prompt_template, cases, user_id
    )
    return {"role_id": str(role_id), **result}


async def shadow_compare(
    db: AsyncSession, role_id: uuid.UUID, candidate_prompt: str, *,
    user_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    """影子评估:当前 vs 候选提示词各跑评估集，对比得分（改提示词前先量化是否更好）。

    返回 {baseline_avg, candidate_avg, delta, improved, count}。改不改仍真人拍板。
    """
    role = await db.get(AgentRole, role_id)
    if role is None or role.is_delete:
        raise ResourceNotFound("智能体角色不存在")
    cases = await _applicable_cases(db, role_id)
    if not cases:
        raise RuleViolation("该角色暂无可用评估用例，请先在评估集中添加")
    base = await _run_prompt_on_cases(db, role, role.prompt_template, cases, user_id)
    cand = await _run_prompt_on_cases(db, role, candidate_prompt, cases, user_id)
    delta = round(cand["avg"] - base["avg"], 3)
    return {
        "role_id": str(role_id),
        "baseline_avg": base["avg"],
        "candidate_avg": cand["avg"],
        "delta": delta,
        "improved": delta > 0,
        "count": base["count"],
    }


# ── CRUD（评估集维护）───────────────────────────────────
async def list_cases(db: AsyncSession, role_id: uuid.UUID | None = None) -> list[dict[str, Any]]:
    stmt = select(EvalCase).where(EvalCase.is_delete.is_(False))
    if role_id is not None:
        stmt = stmt.where(or_(EvalCase.role_id == role_id, EvalCase.role_id.is_(None)))
    stmt = stmt.order_by(EvalCase.create_time.desc())
    return [
        {
            "id": str(c.id), "name": c.name,
            "role_id": str(c.role_id) if c.role_id else None,
            "input_text": c.input_text, "rubric": c.rubric, "is_active": c.is_active,
        }
        for c in (await db.execute(stmt)).scalars()
    ]


async def create_case(db: AsyncSession, data: dict[str, Any]) -> dict[str, Any]:
    name = (data.get("name") or "").strip()
    if not name or not (data.get("input_text") or "").strip():
        raise RuleViolation("用例名称和输入必填")
    rubric = (data.get("rubric") or "").strip() or "产出是否准确、切题、可用。"
    case = EvalCase(
        name=name, role_id=data.get("role_id"),
        input_text=data["input_text"], rubric=rubric,
    )
    db.add(case)
    await db.commit()
    await db.refresh(case)
    return {"id": str(case.id), "name": case.name}


async def delete_case(db: AsyncSession, case_id: uuid.UUID) -> None:
    case = await db.get(EvalCase, case_id)
    if case is None or case.is_delete:
        raise ResourceNotFound("用例不存在")
    case.is_delete = True
    await db.commit()
