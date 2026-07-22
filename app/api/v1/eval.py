"""评估驱动接口（H3.1，docs/16，仅 admin/executive）：评估集 CRUD + 跑评估 + 影子对比。

评估只产出分数与建议，提示词是否应用仍走真人确认（不自动落地，红线不变）。
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_roles
from app.core.database import get_db
from app.models.system import SysUser
from app.platform.http_runtime import ok
from app.services import eval_service

router = APIRouter(prefix="/eval", tags=["eval"])

DB = Annotated[AsyncSession, Depends(get_db)]
Manager = Annotated[SysUser, Depends(require_roles("admin", "executive"))]


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
    return ok(await eval_service.list_cases(db, role_id))


@router.post("/cases")
async def create_case(body: CaseCreate, db: DB, _: Manager) -> dict:
    """新建评估用例。"""
    return ok(await eval_service.create_case(db, body.model_dump()))


@router.delete("/cases/{case_id}")
async def delete_case(case_id: uuid.UUID, db: DB, _: Manager) -> dict:
    """删除评估用例（软删）。"""
    await eval_service.delete_case(db, case_id)
    return ok()


@router.post("/run/{role_id}")
async def run_eval(role_id: uuid.UUID, db: DB, manager: Manager) -> dict:
    """用角色当前提示词跑评估集，返回聚合分 + 明细。"""
    return ok(await eval_service.run_eval(db, role_id, user_id=manager.id))


@router.post("/shadow/{role_id}")
async def shadow_compare(
    role_id: uuid.UUID, body: ShadowRequest, db: DB, manager: Manager
) -> dict:
    """影子评估：当前 vs 候选提示词对比得分（改提示词前先量化是否更好）。"""
    return ok(
        await eval_service.shadow_compare(
            db, role_id, body.candidate_prompt, user_id=manager.id
        )
    )
