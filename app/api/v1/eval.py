"""评估驱动接口（H3.1，docs/16，仅 admin/executive）：评估集 CRUD + 跑评估 + 影子对比。

评估只产出分数与建议，提示词是否应用仍走真人确认（不自动落地，红线不变）。
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_roles
from app.contexts.foundations.governance.ai_quality.public import (
    CreateEvaluationCaseCommand,
    compare_candidate_prompt,
    create_evaluation_case,
    delete_evaluation_case,
    list_evaluation_cases,
    run_evaluation,
)
from app.contexts.foundations.identity.public import IdentityUserResult
from app.core.database import get_db
from app.platform.http_runtime import ok

router = APIRouter(prefix="/eval", tags=["eval"])

DB = Annotated[AsyncSession, Depends(get_db)]
Manager = Annotated[IdentityUserResult, Depends(require_roles("admin", "executive"))]


class CaseCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    role_id: uuid.UUID | None = None
    input_text: str = Field(min_length=1)
    rubric: str | None = None


class ShadowRequest(BaseModel):
    candidate_prompt: str = Field(min_length=1)


@router.get("/cases")
async def list_cases(
    db: DB, _: Manager, role_id: Annotated[uuid.UUID | None, Query()] = None
) -> dict:
    """评估用例列表（可按角色过滤，含通用用例）。"""
    cases = await list_evaluation_cases(db, role_id)
    return ok(
        [
            {
                "id": str(case.case_id),
                "name": case.name,
                "role_id": str(case.role_id) if case.role_id else None,
                "input_text": case.input_text,
                "rubric": case.rubric,
                "is_active": case.is_active,
            }
            for case in cases
        ]
    )


@router.post("/cases")
async def create_case(body: CaseCreate, db: DB, _: Manager) -> dict:
    """新建评估用例。"""
    case = await create_evaluation_case(
        db,
        CreateEvaluationCaseCommand(
            name=body.name,
            role_id=body.role_id,
            input_text=body.input_text,
            rubric=body.rubric,
        ),
    )
    return ok({"id": str(case.case_id), "name": case.name})


@router.delete("/cases/{case_id}")
async def delete_case(case_id: uuid.UUID, db: DB, _: Manager) -> dict:
    """删除评估用例（软删）。"""
    await delete_evaluation_case(db, case_id)
    return ok()


@router.post("/run/{role_id}")
async def run_eval(role_id: uuid.UUID, db: DB, manager: Manager) -> dict:
    """用角色当前提示词跑评估集，返回聚合分 + 明细。"""
    result = await run_evaluation(db, role_id, user_id=manager.id)
    return ok(
        {
            "role_id": str(result.role_id),
            "avg": result.average_score,
            "count": len(result.scores),
            "details": [
                {"case": score.case_name, "score": score.score}
                for score in result.scores
            ],
        }
    )


@router.post("/shadow/{role_id}")
async def shadow_compare(
    role_id: uuid.UUID, body: ShadowRequest, db: DB, manager: Manager
) -> dict:
    """影子评估：当前 vs 候选提示词对比得分（改提示词前先量化是否更好）。"""
    result = await compare_candidate_prompt(
        db,
        role_id,
        body.candidate_prompt,
        user_id=manager.id,
    )
    return ok(
        {
            "role_id": str(result.role_id),
            "baseline_avg": result.baseline_average,
            "candidate_avg": result.candidate_average,
            "delta": result.delta,
            "improved": result.improved,
            "count": result.case_count,
        }
    )
