"""反思/critic 回路（H4.3，docs/16）：给关键产出加一轮 AI 自查再呈现。

评审判定:决策辅助场景质量比速度重要，但 run_agent 是单趟 LLM 无自查。本模块对
**关键产出**（提案预研/会议纪要/运营日报等）加一轮:
1. critic 按 rubric 给产出打 1~5 分 + 列出具体问题（复用 LLM-as-Judge 模式）。
2. 低于阈值 → 带着问题让原 AI 重写一版，取重写版作为最终产出。
做成独立可选函数（不塞 run_agent 主链），故普通对话零影响、零延迟。
红线:反思只是"AI 先自查再呈现"，真人确认/编辑/驳回权不变。
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass

from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm import get_llm_for_role
from app.llm.usage import extract_usage, record_usage
from app.models.agent import AgentRole

logger = logging.getLogger(__name__)

_PASS_THRESHOLD = 4  # critic 分 ≥ 此值视为合格，不重写（1~5）

_CRITIC_SYSTEM = (
    "你是严格的产出审校员。依据【审校标准】审查【AI产出】，找出其中的问题"
    "（事实错误、遗漏、逻辑漏洞、不切题、表述不清、可能的编造）。"
    "第一行只输出一个 1~5 的整数总分（1=问题严重，3=基本可用，5=优秀无明显问题）。"
    "之后逐条列出发现的具体问题（每行一条，无问题写「无」）。不要重写产出本身。"
)


@dataclass
class ReflectionResult:
    """反思结果:最终产出 + critic 分 + 问题清单 + 是否发生了重写。"""

    final_output: str
    critic_score: int
    issues: str
    revised: bool
    original_output: str = ""

    def as_metadata(self) -> dict[str, object]:
        """结构化元数据（供落库/展示，不含最终正文本身）。"""
        return {
            "critic_score": self.critic_score,
            "issues": self.issues,
            "revised": self.revised,
        }


def parse_critic(critic_output: str) -> tuple[int, str]:
    """从 critic 产出解析 (总分 1~5, 问题清单)（纯函数）。

    首行取分（复用 eval 的解析约定，兜底 3）；其余行为问题清单。
    """
    from app.services.eval_service import judge_score

    text = (critic_output or "").strip()
    score = judge_score(text)
    lines = text.splitlines()
    issues = "\n".join(lines[1:]).strip() if len(lines) > 1 else ""
    return score, issues or "无"


async def reflect(
    db: AsyncSession,
    role: AgentRole,
    *,
    output: str,
    task_context: str,
    rubric: str,
    user_id: uuid.UUID | None = None,
    threshold: int = _PASS_THRESHOLD,
) -> ReflectionResult:
    """对一个关键产出做反思:critic 打分+列问题 → 低分则带问题重写。永不 raise。

    Args:
        output: 待审校的初稿产出。
        task_context: 原任务/输入的简述（供 critic 与重写理解上下文）。
        rubric: 审校标准（这类产出应满足什么）。
        threshold: critic 分 ≥ 此值不重写（默认 4）。
    失败降级:任何异常 → 返回初稿原样（critic_score=0, revised=False），不阻断业务。
    """
    if not (output or "").strip():
        return ReflectionResult(final_output=output, critic_score=0, issues="无", revised=False)
    try:
        score, issues = await _critique(db, rubric, task_context, output, user_id)
        if score >= threshold or issues.strip() in ("", "无"):
            return ReflectionResult(
                final_output=output, critic_score=score, issues=issues, revised=False
            )
        revised = await _revise(db, role, task_context, output, issues, user_id)
        if not revised.strip():
            return ReflectionResult(
                final_output=output, critic_score=score, issues=issues, revised=False
            )
        return ReflectionResult(
            final_output=revised, critic_score=score, issues=issues,
            revised=True, original_output=output,
        )
    except Exception:  # noqa: BLE001 - 反思故障不阻断产出，退回初稿
        logger.warning("反思回路失败，退回初稿 role=%s", role.name, exc_info=True)
        return ReflectionResult(final_output=output, critic_score=0, issues="无", revised=False)


async def _critique(
    db: AsyncSession, rubric: str, task_context: str, output: str, user_id: uuid.UUID | None
) -> tuple[int, str]:
    """critic 打分 + 列问题（reasoning 档 + 温度0求稳定）。"""
    llm = get_llm_for_role("meeting_expert", temperature=0.0)
    t0 = time.monotonic()
    reply = await llm.ainvoke([
        SystemMessage(content=_CRITIC_SYSTEM),
        HumanMessage(
            content=f"【审校标准】\n{rubric}\n\n【任务背景】\n{task_context[:800]}\n\n"
            f"【AI产出】\n{output[:3000]}"
        ),
    ])
    p, c, t = extract_usage(reply)
    await record_usage(
        db, role="reflection_critic",
        model=str(reply.response_metadata.get("model_name") or "meeting_expert"),
        prompt_tokens=p, completion_tokens=c, total_tokens=t,
        duration_ms=int((time.monotonic() - t0) * 1000), user_id=user_id,
    )
    text = reply.content if isinstance(reply.content, str) else str(reply.content)
    return parse_critic(text)


async def _revise(
    db: AsyncSession, role: AgentRole, task_context: str, output: str,
    issues: str, user_id: uuid.UUID | None,
) -> str:
    """让原 AI 带着 critic 指出的问题重写一版（用角色自身档位）。"""
    from app.agents.base import run_agent

    msg = (
        f"你之前对以下任务给出了一版产出，审校员指出了一些问题。"
        f"请针对这些问题修订，给出改进后的完整产出（只输出修订后的产出正文）。\n\n"
        f"【任务】\n{task_context}\n\n【你的初稿】\n{output}\n\n"
        f"【审校员指出的问题】\n{issues}"
    )
    rec = await run_agent(
        db, role, task_type="reflection_revise",
        input_summary=f"反思重写:{task_context[:40]}",
        user_message=msg, user_id=user_id,
    )
    return rec.output_content or ""
