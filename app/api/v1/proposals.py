"""提案卡接口：创建 / 列表 / 详情+评审 / AI预研 / 真人评审 / 转任务卡。

创建任意登录用户；预研/评审/转任务卡需 admin/executive。
红线（docs/04）：提案通过与转任务卡均由真人操作，AI 仅提供预研参考。
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, require_roles
from app.core.database import get_db
from app.core.exceptions import ok
from app.models.system import SysUser
from app.schemas.proposal import (
    ConvertRequest,
    HumanReviewRequest,
    ProposalCreate,
    ProposalOut,
    ReviewOut,
)
from app.schemas.task import TaskOut
from app.services import audit_service, permission_service, proposal_service

router = APIRouter(prefix="/proposals", tags=["proposals"])

DB = Annotated[AsyncSession, Depends(get_db)]
Manager = Annotated[SysUser, Depends(require_roles("admin", "executive"))]


@router.post("")
async def create_proposal(body: ProposalCreate, db: DB, user: CurrentUser) -> dict:
    """创建提案。"""
    p = await proposal_service.create_proposal(
        db,
        title=body.title,
        background=body.background,
        plan=body.plan,
        creator_id=user.id,
        benefit_risk=body.benefit_risk,
        priority=body.priority,
        department_id=body.department_id,
    )
    return ok(ProposalOut.model_validate(p).model_dump(mode="json"))


@router.get("")
async def list_proposals(
    db: DB,
    user: CurrentUser,
    status: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> dict:
    """提案列表（行级可见性：普通员工只见本人/本部门，管理层全见）。"""
    items = await proposal_service.list_proposals(db, status=status, limit=limit, viewer=user)
    return ok([ProposalOut.model_validate(p).model_dump(mode="json") for p in items])


@router.get("/{proposal_id}")
async def get_proposal(proposal_id: uuid.UUID, db: DB, user: CurrentUser) -> dict:
    """提案详情 + 评审记录（行级可见性守卫）。"""
    p = await proposal_service.get_proposal(db, proposal_id)
    permission_service.assert_can_see(user, creator_id=p.creator_id, department_id=p.department_id)
    reviews = await proposal_service.list_reviews(db, proposal_id)
    return ok(
        {
            "proposal": ProposalOut.model_validate(p).model_dump(mode="json"),
            "reviews": [ReviewOut.model_validate(r).model_dump(mode="json") for r in reviews],
        }
    )


@router.post("/{proposal_id}/ai-research")
async def ai_research(proposal_id: uuid.UUID, db: DB, manager: Manager) -> dict:
    """会商AI专家会前预研（deepseek-reasoner），产出评审记录。"""
    review = await proposal_service.run_ai_research(db, proposal_id, operator_id=manager.id)
    return ok(ReviewOut.model_validate(review).model_dump(mode="json"))


@router.post("/{proposal_id}/review")
async def human_review(
    proposal_id: uuid.UUID, body: HumanReviewRequest, db: DB, manager: Manager
) -> dict:
    """真人评审：通过 / 驳回（红线：决议须真人确认生效）。"""
    p = await proposal_service.human_review(
        db, proposal_id, reviewer_id=manager.id, conclusion=body.conclusion, decision=body.decision
    )
    await audit_service.audit(
        db, actor_id=manager.id, actor_role=manager.role_code,
        action=f"proposal.{body.decision}", summary=f"提案评审 {p.code} → {body.decision}",
        target_type="proposal_card", target_id=p.id,
    )
    return ok(ProposalOut.model_validate(p).model_dump(mode="json"))


@router.post("/{proposal_id}/convert")
async def convert_to_task(
    proposal_id: uuid.UUID, body: ConvertRequest, db: DB, manager: Manager
) -> dict:
    """把已通过的提案转为任务卡。"""
    task = await proposal_service.convert_to_task(
        db, proposal_id, creator_id=manager.id, assignee_agent_id=body.assignee_agent_id
    )
    await audit_service.audit(
        db, actor_id=manager.id, actor_role=manager.role_code,
        action="proposal.convert", summary=f"提案转任务卡 {task.title[:40]}",
        target_type="task_card", target_id=task.id,
    )
    return ok(TaskOut.model_validate(task).model_dump(mode="json"))
