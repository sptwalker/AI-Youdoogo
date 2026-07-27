"""提案卡接口：创建 / 列表 / 详情+评审 / AI预研 / 真人评审 / 转任务卡。

创建任意登录用户；预研/评审/转任务卡需 admin/executive。
红线（docs/04）：提案通过与转任务卡均由真人操作，AI 仅提供预研参考。
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, require_roles
from app.contexts.business.proposal_management.application.contracts import ProposalViewer
from app.contexts.business.proposal_management.entrypoints import operations
from app.contexts.foundations.identity.application.contracts import IdentityUserResult
from app.core.database import get_db
from app.platform.http_runtime import ok
from app.schemas.proposal import (
    ConvertRequest,
    HumanReviewRequest,
    ProposalCreate,
    ProposalEdit,
    ProposalOut,
    ReviewOut,
)
from app.schemas.task import TaskOut

router = APIRouter(prefix="/proposals", tags=["proposals"])

DB = Annotated[AsyncSession, Depends(get_db)]
Manager = Annotated[IdentityUserResult, Depends(require_roles("admin", "executive"))]


@router.post("")
async def create_proposal(body: ProposalCreate, db: DB, user: CurrentUser) -> dict:
    """创建提案。"""
    p = await operations.create_proposal(
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
    items = await operations.list_proposals(
        db,
        status=status,
        limit=limit,
        viewer=ProposalViewer(
            id=user.id,
            role_code=user.role_code,
            department_id=user.department_id,
        ),
    )
    return ok([ProposalOut.model_validate(p).model_dump(mode="json") for p in items])


@router.get("/{proposal_id}")
async def get_proposal(proposal_id: uuid.UUID, db: DB, user: CurrentUser) -> dict:
    """提案详情 + 评审记录（行级可见性守卫）。"""
    detail = await operations.get_proposal_detail(
        db,
        proposal_id,
        viewer=ProposalViewer(
            id=user.id,
            role_code=user.role_code,
            department_id=user.department_id,
        ),
    )
    return ok(
        {
            "proposal": ProposalOut.model_validate(detail.proposal).model_dump(mode="json"),
            "reviews": [
                ReviewOut.model_validate(review).model_dump(mode="json")
                for review in detail.reviews
            ],
        }
    )


@router.patch("/{proposal_id}")
async def edit_proposal(
    proposal_id: uuid.UUID, body: ProposalEdit, db: DB, user: CurrentUser
) -> dict:
    """编辑草稿提案（仅创建者本人、仅草稿状态可改，P3-7）。"""
    p = await operations.edit_proposal(
        db,
        proposal_id,
        actor_id=user.id,
        title=body.title,
        background=body.background,
        plan=body.plan,
        benefit_risk=body.benefit_risk,
        priority=body.priority,
    )
    return ok(ProposalOut.model_validate(p).model_dump(mode="json"))


@router.delete("/{proposal_id}")
async def delete_proposal(proposal_id: uuid.UUID, db: DB, user: CurrentUser) -> dict:
    """删除草稿提案（软删除，仅创建者本人、仅草稿状态可删，P3-7）。"""
    await operations.delete_proposal(db, proposal_id, actor_id=user.id)
    return ok({"id": str(proposal_id)})


@router.post("/{proposal_id}/ai-research")
async def ai_research(proposal_id: uuid.UUID, db: DB, manager: Manager) -> dict:
    """会商AI专家会前预研（deepseek-reasoner），产出评审记录。"""
    review = await operations.run_ai_research(db, proposal_id, operator_id=manager.id)
    return ok(ReviewOut.model_validate(review).model_dump(mode="json"))


@router.post("/{proposal_id}/review")
async def human_review(
    proposal_id: uuid.UUID, body: HumanReviewRequest, db: DB, manager: Manager
) -> dict:
    """真人评审：通过 / 驳回（红线：决议须真人确认生效）。"""
    p = await operations.human_review(
        db,
        proposal_id,
        reviewer_id=manager.id,
        conclusion=body.conclusion,
        decision=body.decision,
        actor_role=manager.role_code,
    )
    return ok(ProposalOut.model_validate(p).model_dump(mode="json"))


@router.post("/{proposal_id}/convert")
async def convert_to_task(
    proposal_id: uuid.UUID, body: ConvertRequest, db: DB, manager: Manager
) -> dict:
    """把已通过的提案转为任务卡。"""
    task = await operations.convert_to_task(
        db,
        proposal_id,
        creator_id=manager.id,
        assignee_agent_id=body.assignee_agent_id,
        actor_role=manager.role_code,
    )
    return ok(TaskOut.model_validate(task).model_dump(mode="json"))
