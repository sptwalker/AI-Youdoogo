"""提案卡业务逻辑：创建 → AI会前预研 → 真人评审 → (通过后)转任务卡。

红线（docs/04）：提案 approved 只能由真人评审置位；只有 approved 提案能转任务卡。
AI 预研仅产出参考结论（reasoning 档位 = deepseek-reasoner），不改变 approved 状态。
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    from app.models.system import SysUser

from app.agents.base import get_agent_role, run_agent
from app.core.exceptions import AppError
from app.models.proposal import (
    APPROVED,
    DRAFT,
    REJECTED,
    RESEARCHING,
    REVIEWED,
    ProposalCard,
    ProposalReview,
)
from app.models.task import TaskCard
from app.services import task_service

EXPERT_NAME = "会商AI专家"  # 与 alembic 007 种子行一致


def _gen_code() -> str:
    """生成提案编号（PROP- + 8位十六进制）。"""
    return f"PROP-{uuid.uuid4().hex[:8].upper()}"


async def create_proposal(
    db: AsyncSession,
    *,
    title: str,
    background: str,
    plan: str,
    creator_id: uuid.UUID,
    benefit_risk: str | None = None,
    priority: str = "normal",
    department_id: uuid.UUID | None = None,
) -> ProposalCard:
    """创建提案（初始 draft）。"""
    proposal = ProposalCard(
        code=_gen_code(), title=title, background=background, plan=plan,
        benefit_risk=benefit_risk, priority=priority, creator_id=creator_id,
        department_id=department_id, status=DRAFT,
    )
    db.add(proposal)
    await db.commit()
    await db.refresh(proposal)
    return proposal


async def get_proposal(db: AsyncSession, proposal_id: uuid.UUID) -> ProposalCard:
    proposal = await db.get(ProposalCard, proposal_id)
    if proposal is None or proposal.is_delete:
        raise AppError("提案不存在", code=404, status_code=404)
    return proposal


async def run_ai_research(
    db: AsyncSession, proposal_id: uuid.UUID, *, operator_id: uuid.UUID | None = None
) -> ProposalReview:
    """会商AI专家对提案做会前预研，产出评审记录并置状态为 reviewed。

    Raises:
        AppError: 提案不存在 / 已进入终态 / 未配置会商专家角色。
    """
    proposal = await get_proposal(db, proposal_id)
    if proposal.status in (APPROVED, REJECTED):
        raise AppError("提案已完成评审，不可再预研")
    role = await get_agent_role(db, EXPERT_NAME)
    if role is None:
        raise AppError("未配置会商AI专家角色，请先执行数据库迁移（alembic upgrade head）")

    # 置「预研中」并提交，使长耗时 reasoner 调用期间该状态对前端可见
    proposal.status = RESEARCHING
    await db.commit()

    user_message = (
        f"请对以下提案做会前预研：\n\n提案标题：{proposal.title}\n"
        f"背景：{proposal.background}\n方案：{proposal.plan}\n"
        f"收益与风险：{proposal.benefit_risk or '（未填写）'}"
    )
    record = await run_agent(
        db, role,
        task_type="proposal_research",
        input_summary=f"提案预研：{proposal.code}",
        user_message=user_message,
        user_id=operator_id,
    )
    draft = record.output_content or record.error_msg or "（无产出）"
    # 反思回路（H4.3）：提案预研是关键产出，加一轮 critic 自查+低分重写再落库。
    from app.services import reflection_service

    refl = await reflection_service.reflect(
        db, role, output=draft, task_context=user_message,
        rubric="预研应准确评估提案的可行性、收益与风险，逻辑严谨、不遗漏关键点、不编造。",
        user_id=operator_id,
    )
    conclusion = refl.final_output
    if refl.revised:
        conclusion += f"\n\n> 系统：本预研经 AI 自查修订（初评 {refl.critic_score}/5）。"
    review = ProposalReview(
        proposal_id=proposal.id,
        review_type="ai_research",
        conclusion=conclusion,
    )
    db.add(review)
    proposal.status = REVIEWED
    await db.commit()
    await db.refresh(review)
    return review


async def human_review(
    db: AsyncSession,
    proposal_id: uuid.UUID,
    *,
    reviewer_id: uuid.UUID,
    conclusion: str,
    decision: str,
) -> ProposalCard:
    """真人评审：approve/reject 决定提案是否通过（红线：仅此处能置 approved）。

    Raises:
        AppError: decision 非法 / 提案未到可评审状态。
    """
    if decision not in ("approve", "reject"):
        raise AppError("decision 仅支持 approve / reject")
    proposal = await get_proposal(db, proposal_id)
    if proposal.status != REVIEWED:
        raise AppError(f"提案当前状态 {proposal.status} 不可评审（需先完成 AI 预研至 reviewed）")

    db.add(
        ProposalReview(
            proposal_id=proposal.id, review_type="human", conclusion=conclusion,
            reviewer_id=reviewer_id, decision=decision,
        )
    )
    proposal.status = APPROVED if decision == "approve" else REJECTED
    await db.commit()
    await db.refresh(proposal)
    return proposal


async def convert_to_task(
    db: AsyncSession,
    proposal_id: uuid.UUID,
    *,
    creator_id: uuid.UUID,
    assignee_agent_id: uuid.UUID | None = None,
) -> TaskCard:
    """把已通过的提案转为任务卡（红线：仅 approved 提案可转，避免未确认决议落地）。

    Raises:
        AppError: 提案未通过 / 已转过。
    """
    proposal = await get_proposal(db, proposal_id)
    if proposal.status != APPROVED:
        raise AppError("仅『已通过』的提案可转任务卡（决议须真人确认）")
    if proposal.converted_task_id is not None:
        raise AppError("该提案已转过任务卡")

    task = await task_service.create_task(
        db,
        title=f"[提案落地] {proposal.title}",
        task_type="proposal_execution",
        creator_id=creator_id,
        priority=proposal.priority,
        assignee_agent_id=assignee_agent_id,
        payload={"proposal_code": proposal.code, "plan": proposal.plan},
    )
    proposal.converted_task_id = task.id
    await db.commit()
    return task


async def list_proposals(
    db: AsyncSession, *, status: str | None = None, limit: int = 100,
    viewer: SysUser | None = None,
) -> list[ProposalCard]:
    stmt = select(ProposalCard).where(ProposalCard.is_delete.is_(False))
    if status:
        stmt = stmt.where(ProposalCard.status == status)
    if viewer is not None:  # 行级可见性（H1.2）：普通员工只见本人/本部门
        from app.services import permission_service

        cond = permission_service.row_filter(ProposalCard, viewer)
        if cond is not None:
            stmt = stmt.where(cond)
    stmt = stmt.order_by(ProposalCard.create_time.desc()).limit(limit)
    return list((await db.execute(stmt)).scalars())


async def list_reviews(db: AsyncSession, proposal_id: uuid.UUID) -> list[ProposalReview]:
    stmt = (
        select(ProposalReview)
        .where(ProposalReview.proposal_id == proposal_id)
        .order_by(ProposalReview.create_time)
    )
    return list((await db.execute(stmt)).scalars())
