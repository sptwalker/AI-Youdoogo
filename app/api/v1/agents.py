"""Thin HTTP adapters for Agent-facing operations."""

from __future__ import annotations

import uuid
from typing import Annotated, Protocol

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, require_roles
from app.contexts.business.operational_analytics.entrypoints import (
    agent_operations as operational_operations,
)
from app.contexts.foundations.execution.agent_execution.contracts.consult import (
    ConsultExpertCommand,
    ConsultHistoryTurn,
)
from app.contexts.foundations.execution.agent_execution.entrypoints import (
    operations as agent_execution_operations,
)
from app.contexts.foundations.execution.capability_catalog.entrypoints import (
    operations as capability_operations,
)
from app.contexts.foundations.governance.ai_quality.contracts.quality import (
    RecordFeedbackCommand,
)
from app.contexts.foundations.governance.ai_quality.entrypoints import (
    operations as quality_operations,
)
from app.contexts.foundations.governance.audit_trail.contracts.audit import (
    AppendAuditRecordCommand,
)
from app.contexts.foundations.governance.audit_trail.entrypoints.operations import (
    append_audit_record,
)
from app.contexts.foundations.workforce.expert_management.entrypoints import (
    operations as expert_operations,
)
from app.contexts.foundations.workforce.expert_management.entrypoints.legacy import (
    legacy_view,
)
from app.platform.database import get_db
from app.platform.http_runtime import ok
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

router = APIRouter(prefix="/agents", tags=["agents"])

DB = Annotated[AsyncSession, Depends(get_db)]


class AuthenticatedPrincipal(Protocol):
    id: uuid.UUID
    role_code: str


Manager = Annotated[
    AuthenticatedPrincipal,
    Depends(require_roles("admin", "executive")),
]
Admin = Annotated[AuthenticatedPrincipal, Depends(require_roles("admin"))]


@router.post("/ops/daily-report")
async def ops_daily_report(body: DailyReportRequest, db: DB, manager: Manager) -> dict:
    """Generate the operational daily report from inline or stored metrics."""
    record = await operational_operations.create_daily_report(
        db,
        stat_date=body.stat_date,
        rows=(
            [row.model_dump() for row in body.rows]
            if body.rows is not None
            else None
        ),
        operator_id=manager.id,
    )
    return ok(TaskRecordOut.model_validate(record).model_dump(mode="json"))


@router.post("/ops/anomaly-check")
async def ops_anomaly_check(body: AnomalyCheckRequest, db: DB, manager: Manager) -> dict:
    """Compare daily metrics and optionally generate an alert record."""
    result = await operational_operations.check_anomalies(
        db,
        stat_date=body.stat_date,
        operator_id=manager.id,
    )
    record = (
        TaskRecordOut.model_validate(result.record).model_dump(mode="json")
        if result.record is not None
        else None
    )
    return ok({"alerts": [alert.to_dict() for alert in result.alerts], "record": record})


@router.post("/ops/proposal")
async def ops_proposal(body: ProposalRequest, db: DB, manager: Manager) -> dict:
    """Generate an advisory operational proposal."""
    record = await operational_operations.create_operational_proposal(
        db,
        topic=body.topic,
        context=body.context,
        operator_id=manager.id,
    )
    return ok(TaskRecordOut.model_validate(record).model_dump(mode="json"))


@router.get("/records")
async def list_records(
    db: DB,
    user: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> dict:
    """Return recent immutable Agent execution evidence with the caller's own rating."""
    records = await agent_execution_operations.list_execution_records(db, limit)
    mine = await quality_operations.list_my_feedback(
        db, user.id, tuple(record.id for record in records)
    )
    scored = {feedback.task_record_id: feedback for feedback in mine}
    result = []
    for record in records:
        view = TaskRecordOut.model_validate(record)
        feedback = scored.get(record.id)
        if feedback is not None:
            view.my_score = feedback.score
            view.my_comment = feedback.comment
        result.append(view.model_dump(mode="json"))
    return ok(result)


@router.get("/roles")
async def list_roles(db: DB, _: CurrentUser) -> dict:
    """List configured non-personal experts."""
    roles = await expert_operations.list_roster(db)
    return ok(
        [
            AgentRoleOut.model_validate(legacy_view(role)).model_dump(mode="json")
            for role in roles
        ]
    )


@router.get("/skills")
async def list_skills(_: CurrentUser) -> dict:
    """List versioned capability definitions for role configuration."""
    definitions = await capability_operations.list_capabilities()
    return ok(
        [
            {
                "key": definition.key,
                "label": definition.label,
                "description": definition.description,
                "default_on": definition.default_enabled,
            }
            for definition in definitions
        ]
    )


@router.post("/roles")
async def create_role(body: AgentRoleCreate, db: DB, _: Admin) -> dict:
    """Create one configurable expert profile."""
    role = await expert_operations.create_expert(
        db,
        name=body.name,
        prompt_template=body.prompt_template,
        duty=body.duty,
        model_role=body.model_role,
        department_id=None,
        permission_scope=body.permission_scope,
        tools=body.tools,
        tier="member",
        title="",
        report_to_id=None,
    )
    return ok(AgentRoleOut.model_validate(legacy_view(role)).model_dump(mode="json"))


@router.patch("/roles/{role_id}")
async def update_role(role_id: uuid.UUID, body: AgentRoleUpdate, db: DB, admin: Admin) -> dict:
    """Update an expert profile and retain prompt-application evidence."""
    role = await expert_operations.update_expert(
        db,
        expert_id=role_id,
        name=None,
        prompt_template=body.prompt_template,
        duty=body.duty,
        model_role=body.model_role,
        is_active=body.is_active,
        permission_scope=body.permission_scope,
        tools=body.tools,
        title=None,
        tier=None,
        report_to_id=None,
        department_id=None,
    )
    if body.prompt_template:
        await append_audit_record(
            db,
            AppendAuditRecordCommand(
                actor_id=admin.id,
                actor_role=admin.role_code,
                action="agent.prompt.apply",
                summary=f"应用提示词 {role.name}",
                target_type="agent_role",
                target_id=role.expert_id,
            ),
        )
    return ok(AgentRoleOut.model_validate(legacy_view(role)).model_dump(mode="json"))


@router.post("/records/{record_id}/feedback")
async def add_feedback(
    record_id: uuid.UUID,
    body: FeedbackRequest,
    db: DB,
    user: CurrentUser,
) -> dict:
    """Record human feedback for one Agent execution."""
    feedback = await quality_operations.record_feedback(
        db,
        RecordFeedbackCommand(
            task_record_id=record_id,
            rater_id=user.id,
            score=body.score,
            comment=body.comment,
        ),
    )
    return ok({"id": str(feedback.feedback_id), "score": feedback.score})


@router.post("/roles/{role_id}/optimize-prompt")
async def optimize_prompt(role_id: uuid.UUID, db: DB, admin: Admin) -> dict:
    """Return an advisory prompt improvement based on low-scored evidence."""
    suggestion = await quality_operations.suggest_prompt_improvement(
        db,
        role_id,
        user_id=admin.id,
    )
    return ok(
        {
            "role_id": str(suggestion.role_id),
            "current_prompt": suggestion.current_prompt,
            "suggested_prompt": suggestion.suggested_prompt,
            "based_on_samples": suggestion.based_on_samples,
        }
    )


class ConsultRequest(BaseModel):
    """One consultation message plus recent transport history."""

    message: str = Field(min_length=1, max_length=2000)
    history: list[dict] = Field(default_factory=list)


@router.post("/roles/{role_id}/consult")
async def consult(role_id: uuid.UUID, body: ConsultRequest, db: DB, user: CurrentUser) -> dict:
    """Consult an active expert without applying any business action."""
    result = await agent_execution_operations.consult_expert(
        db,
        ConsultExpertCommand(
            expert_id=role_id,
            message=body.message,
            history=tuple(
                ConsultHistoryTurn(
                    role=str(turn.get("role", "")),
                    content=str(turn.get("content", "")),
                )
                for turn in body.history
            ),
            user_id=user.id,
        ),
    )
    return ok({"reply": result.reply, "status": result.status})
