"""智能体接口：触发运营日报 + 查询留痕/角色。

触发类操作需 admin/executive；留痕与角色查询任意登录用户可见。
所有AI产出仅供参考，可编辑/驳回（前端负责），后端只负责生成与留痕。
"""

import uuid
from dataclasses import asdict
from datetime import date, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import ops
from app.agents.base import run_agent
from app.api.deps import CurrentUser, require_roles
from app.core.database import get_db
from app.core.exceptions import AppError, ok
from app.integrations.feishu import notify
from app.models.agent import AgentRole, AgentTaskRecord
from app.models.system import SysUser
from app.schemas.agent import (
    AgentRoleCreate,
    AgentRoleOut,
    AgentRoleUpdate,
    AnomalyCheckRequest,
    DailyReportRequest,
    FeedbackRequest,
    ProposalRequest,
    TaskRecordOut,
)
from app.services import (
    agent_role_service,
    anomaly,
    audit_service,
    feedback_service,
    ops_data,
)

router = APIRouter(prefix="/agents", tags=["agents"])

DB = Annotated[AsyncSession, Depends(get_db)]
Manager = Annotated[SysUser, Depends(require_roles("admin", "executive"))]
Admin = Annotated[SysUser, Depends(require_roles("admin"))]


@router.post("/ops/daily-report")
async def ops_daily_report(body: DailyReportRequest, db: DB, manager: Manager) -> dict:
    """生成平台运营部当日运营日报（结果含 status，失败时 error_msg 说明原因）。

    rows 省略时从已入库的运营指标按 stat_date 取数（先上传 Excel 再生成即可）。
    """
    if body.rows is not None:
        rows = [r.model_dump() for r in body.rows]
    else:
        try:
            query_date = date.fromisoformat(body.stat_date)
        except ValueError as exc:
            raise AppError("stat_date 需为 YYYY-MM-DD，或直接在 rows 传入数据") from exc
        rows = await ops_data.get_ops_metrics(db, query_date)
    record = await ops.generate_daily_report(
        db, stat_date=body.stat_date, rows=rows, operator_id=manager.id
    )
    if record.status == "success" and record.output_content:
        await notify.push_ops_message(f"【运营日报 {body.stat_date}】\n{record.output_content}")
    return ok(TaskRecordOut.model_validate(record).model_dump(mode="json"))


@router.post("/ops/anomaly-check")
async def ops_anomaly_check(body: AnomalyCheckRequest, db: DB, manager: Manager) -> dict:
    """检测当日运营指标异常（对比前一日）；有异常则生成告警播报并留痕。"""
    try:
        d = date.fromisoformat(body.stat_date)
    except ValueError as exc:
        raise AppError("stat_date 需为 YYYY-MM-DD") from exc
    today = await ops_data.get_ops_metrics(db, d)
    if not today:
        raise AppError("该日无运营数据，请先上传")
    prev = await ops_data.get_ops_metrics(db, d - timedelta(days=1))
    alerts = anomaly.detect_anomalies(today, prev)

    record = None
    if alerts:
        rec = await ops.generate_anomaly_alert(
            db, stat_date=body.stat_date, alerts=alerts, operator_id=manager.id
        )
        record = TaskRecordOut.model_validate(rec).model_dump(mode="json")
        if rec.status == "success" and rec.output_content:
            await notify.push_ops_message(f"【运营告警 {body.stat_date}】\n{rec.output_content}")
    return ok({"alerts": [asdict(a) for a in alerts], "record": record})


@router.post("/ops/proposal")
async def ops_proposal(body: ProposalRequest, db: DB, manager: Manager) -> dict:
    """生成运营优化提案（AI 仅建议权，需真人确认后方可落地）。"""
    record = await ops.generate_proposal(
        db, topic=body.topic, context=body.context, operator_id=manager.id
    )
    return ok(TaskRecordOut.model_validate(record).model_dump(mode="json"))


@router.get("/records")
async def list_records(
    db: DB,
    _: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> dict:
    """智能体执行留痕（最近 N 条，倒序）。"""
    stmt = (
        select(AgentTaskRecord)
        .where(AgentTaskRecord.is_delete.is_(False))
        .order_by(AgentTaskRecord.create_time.desc())
        .limit(limit)
    )
    records = list((await db.execute(stmt)).scalars())
    return ok([TaskRecordOut.model_validate(r).model_dump(mode="json") for r in records])


@router.get("/roles")
async def list_roles(db: DB, _: CurrentUser) -> dict:
    """已配置的智能体角色。"""
    roles = await agent_role_service.list_agent_roles(db)
    return ok([AgentRoleOut.model_validate(r).model_dump(mode="json") for r in roles])


@router.post("/roles")
async def create_role(body: AgentRoleCreate, db: DB, _: Admin) -> dict:
    """新增部门智能体角色（仅 admin）——新增部门智能体即建一行，零新代码。"""
    role = await agent_role_service.create_agent_role(
        db,
        name=body.name,
        prompt_template=body.prompt_template,
        duty=body.duty,
        model_role=body.model_role,
        permission_scope=body.permission_scope,
        tools=body.tools,
    )
    return ok(AgentRoleOut.model_validate(role).model_dump(mode="json"))


@router.patch("/roles/{role_id}")
async def update_role(role_id: uuid.UUID, body: AgentRoleUpdate, db: DB, admin: Admin) -> dict:
    """更新智能体角色（仅 admin）：改提示词/职责/档位/启用状态等。"""
    role = await agent_role_service.update_agent_role(
        db,
        role_id,
        prompt_template=body.prompt_template,
        duty=body.duty,
        model_role=body.model_role,
        is_active=body.is_active,
        permission_scope=body.permission_scope,
        tools=body.tools,
    )
    if body.prompt_template:  # 红线：提示词应用留痕（与 service 一致，空串不算改，不污染审计）
        await audit_service.audit(
            db, actor_id=admin.id, actor_role=admin.role_code, action="agent.prompt.apply",
            summary=f"应用提示词 {role.name}", target_type="agent_role", target_id=role.id,
        )
    return ok(AgentRoleOut.model_validate(role).model_dump(mode="json"))


@router.post("/records/{record_id}/feedback")
async def add_feedback(
    record_id: uuid.UUID, body: FeedbackRequest, db: DB, user: CurrentUser
) -> dict:
    """给一条智能体产出打分（1~5）+ 评语，驱动提示词自优化。"""
    fb = await feedback_service.add_feedback(
        db, task_record_id=record_id, rater_id=user.id, score=body.score, comment=body.comment
    )
    return ok({"id": str(fb.id), "score": fb.score})


@router.post("/roles/{role_id}/optimize-prompt")
async def optimize_prompt(role_id: uuid.UUID, db: DB, admin: Admin) -> dict:
    """基于低分反馈产出改进版提示词（仅建议；须真人经 PATCH /roles 确认落地）。"""
    return ok(await feedback_service.optimize_prompt(db, role_id, user_id=admin.id))


class ConsultRequest(BaseModel):
    """与 AI 顾问实时对话（单条消息 + 近期历史，供上下文）。"""

    message: str = Field(min_length=1, max_length=2000)
    history: list[dict] = Field(default_factory=list)  # [{role: user/ai, content}]


@router.post("/roles/{role_id}/consult")
async def consult(role_id: uuid.UUID, body: ConsultRequest, db: DB, user: CurrentUser) -> dict:
    """与某 AI 顾问实时对话（知识库加持、留痕）。任意登录用户可用。

    红线：AI 回复仅参考意见，不产生任何生效动作。
    """
    role = await db.get(AgentRole, role_id)
    if role is None or role.is_delete or not role.is_active:
        raise AppError("AI 顾问不存在或已停用", code=404, status_code=404)
    # 折叠近期历史（最多 6 轮）为上下文
    convo = "\n".join(
        f"{'我' if h.get('role') == 'user' else role.name}：{h.get('content', '')}"
        for h in body.history[-6:]
    )
    msg = f"以下是我们的对话：\n{convo}\n\n我：{body.message}" if convo else body.message
    record = await run_agent(
        db, role, task_type="desktop_consult",
        input_summary=f"对话：{body.message[:40]}",
        user_message=msg, user_id=user.id, use_knowledge=True,
    )
    return ok({
        "reply": record.output_content or record.error_msg or "（无回应）",
        "status": record.status,
    })
