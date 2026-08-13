"""工作流模板管理接口（docs/25 P5-1，仅 admin）——只碰模板定义，不碰发起/执行/红线停点。

发起仍走 report_scheduler → plan_work/start_workflow 同一入口、同一 is_red_line 运行时判定。
失败只 raise shared_kernel 异常，由 error_wiring 自动映射 4xx；统一 {code,msg,data} 封套。
"""

from __future__ import annotations

import uuid
from typing import Annotated, Protocol

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_roles
from app.contexts.foundations.execution.workflow_templating.public import (
    CreateTemplateCommand,
    TemplateAdminView,
    TemplateStep,
    UpdateTemplateCommand,
    create_template,
    delete_template,
    get_template,
    list_templates,
    update_template,
)
from app.platform.database import get_db
from app.platform.http_runtime import ok

router = APIRouter(prefix="/workflow-templates", tags=["workflow-template"])


class AuthenticatedPrincipal(Protocol):
    id: uuid.UUID
    role_code: str


DB = Annotated[AsyncSession, Depends(get_db)]
Admin = Annotated[AuthenticatedPrincipal, Depends(require_roles("admin"))]


class StepDTO(BaseModel):
    """一步定义（校验权威在后端 validation.py，这里只作字段约束）。"""

    no: int = Field(ge=0)
    title: str = Field(min_length=1, max_length=200)
    skill: str = Field(min_length=1, max_length=64)
    instruction: str = Field(min_length=1, max_length=2000)
    depends_on: list[int] = Field(default_factory=list)
    expert_code: str | None = Field(default=None, max_length=64)


def _require_name(v: str) -> str:
    """去首尾空白后不得为空（挡纯空白名，POST/PATCH 一致约束）。"""
    v = v.strip()
    if not v:
        raise ValueError("模板名称不能为空")
    return v


class TemplateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=2000)
    department_id: uuid.UUID | None = None
    steps: list[StepDTO]

    @field_validator("name")
    @classmethod
    def _strip_name(cls, v: str) -> str:
        return _require_name(v)


class TemplateUpdate(BaseModel):
    """PATCH 语义：None 表示该字段不改。"""

    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=2000)
    department_id: uuid.UUID | None = None
    steps: list[StepDTO] | None = None
    enabled: bool | None = None

    @field_validator("name")
    @classmethod
    def _strip_name(cls, v: str | None) -> str | None:
        return _require_name(v) if v is not None else None


def _steps(dtos: list[StepDTO]) -> tuple[TemplateStep, ...]:
    return tuple(
        TemplateStep(
            no=dto.no,
            title=dto.title,
            skill=dto.skill,
            instruction=dto.instruction,
            depends_on=tuple(dto.depends_on),
            expert_code=dto.expert_code,
        )
        for dto in dtos
    )


def _view(view: TemplateAdminView) -> dict:
    return {
        "id": str(view.id),
        "name": view.name,
        "description": view.description,
        "department_id": str(view.department_id) if view.department_id else None,
        "steps": [
            {
                "no": step.no,
                "title": step.title,
                "skill": step.skill,
                "instruction": step.instruction,
                "depends_on": list(step.depends_on),
                "expert_code": step.expert_code,
            }
            for step in view.steps
        ],
        "enabled": view.enabled,
        "is_seed": view.is_seed,
    }


@router.get("")
async def list_workflow_templates(db: DB, _: Admin) -> dict:
    """模板列表（含停用）。"""
    return ok([_view(view) for view in await list_templates(db)])


@router.get("/{template_id}")
async def get_workflow_template(template_id: uuid.UUID, db: DB, _: Admin) -> dict:
    """模板详情。"""
    return ok(_view(await get_template(db, template_id)))


@router.post("")
async def create_workflow_template(body: TemplateCreate, db: DB, _: Admin) -> dict:
    """新建模板。"""
    view = await create_template(
        db,
        CreateTemplateCommand(
            name=body.name,
            description=body.description,
            department_id=body.department_id,
            steps=_steps(body.steps),
        ),
    )
    return ok({"id": str(view.id)})


@router.patch("/{template_id}")
async def update_workflow_template(
    template_id: uuid.UUID, body: TemplateUpdate, db: DB, _: Admin
) -> dict:
    """改模板。"""
    view = await update_template(
        db,
        template_id,
        UpdateTemplateCommand(
            name=body.name,
            description=body.description,
            department_id=body.department_id,
            steps=_steps(body.steps) if body.steps is not None else None,
            enabled=body.enabled,
        ),
    )
    return ok({"id": str(view.id)})


@router.delete("/{template_id}")
async def delete_workflow_template(template_id: uuid.UUID, db: DB, _: Admin) -> dict:
    """软删模板（种子模板拒删）。"""
    await delete_template(db, template_id)
    return ok()
