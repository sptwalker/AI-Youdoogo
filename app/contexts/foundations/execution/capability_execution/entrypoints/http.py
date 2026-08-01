"""youdoo 同步 Capability Provider 服务面：``POST /internal/capabilities/execute``（docs/23 §6.7）。

服务身份鉴权（ES256 internal JWT，强制 ``capabilities:execute`` scope）→ **只放行 transport==
SYNC_LOCAL**（无副作用可同步就地）→ 复用既有 ``CapabilityExecutionApplication`` 全链（授权/审批/
幂等/dispatch 不减）→ 封套返结果。有写副作用（EVENT_GATED）在协议层用 409 拒（须走事件门禁）。

信任边界：``permission_keys`` 源自 definition 而非请求体——远端是服务身份，不可自我提权（获准执行
此能力即拥有其声明所需权限）。默认关（不挂路由，生产逐字不变），线协议属服务端预留，本模块无远端
调用方。红线：日志只记 capability_key/version/status/transport/trace_id，不打 token/arguments/body。
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_service
from app.contexts.foundations.execution.capability_catalog.contracts.definition import (
    CapabilityDefinition,
    CapabilityTransport,
    capability_transport,
)
from app.contexts.foundations.execution.capability_execution.application.ports import (
    CapabilityCatalogPort,
    CapabilityHandlerPort,
    HandlerExecutionResult,
)
from app.contexts.foundations.execution.capability_execution.application.use_cases import (
    CapabilityExecutionApplication,
)
from app.contexts.foundations.execution.capability_execution.contracts.execution import (
    CapabilityExecutionRequest,
    CapabilityPrincipal,
    CapabilityTrace,
)
from app.contexts.foundations.execution.capability_execution.infrastructure.current_policy import (
    CurrentCapabilityApproval,
    CurrentCapabilityAuthorization,
)
from app.contexts.foundations.execution.capability_execution.infrastructure.sqlalchemy_uow import (
    SQLAlchemyCapabilityExecutionUnitOfWork,
)
from app.core.database import get_db
from app.platform.http_runtime import ok

logger = logging.getLogger(__name__)

CAPABILITIES_EXECUTE_SCOPE = "capabilities:execute"

router = APIRouter(tags=["capability-provider"])


@dataclass(frozen=True, slots=True)
class ProviderOverride:
    """Provider 装配（catalog + handler 工厂），由组合根注入 app.state（生产/测试皆经此注入）。

    ``catalog`` 由 bootstrap 用具体 infrastructure 构造（entrypoints 不得跨 Context 依赖
    infrastructure，故经组合根注入）。``handler`` 收 (db, principal) 造 handler——
    permission_keys 已由端点从 definition 填齐；测试传 stub 避开 data_query 真实 SQL 护栏与 seed。
    """

    catalog: CapabilityCatalogPort
    handler: Callable[[AsyncSession, CapabilityPrincipal], CapabilityHandlerPort] | None = None


#: app.state 上的 Provider 装配键（组合根注入 catalog + 可选 handler 工厂）。
PROVIDER_OVERRIDE_KEY = "capability_provider_override"


class CapabilityExecuteRequest(BaseModel):
    """同步能力执行请求体（服务身份调用）。**不收 permission_keys**（信任边界，见模块头）。"""

    capability_key: str = Field(min_length=1)
    capability_version: str | None = None
    action_index: int = 0
    arguments: dict[str, Any] = Field(default_factory=dict)
    raw_text: str | None = None
    idempotency_key: str | None = None
    trace_id: uuid.UUID | None = None
    expert_id: uuid.UUID


class _RegistryHandler:
    """按 capability_key 从 skill REGISTRY 取 executor 跑一次，映回 HandlerExecutionResult。

    与 ToolDispatcher._LegacyHandlerAdapter 同范式，但走服务身份路径：无 agent 上下文可传。
    首版可执行 SYNC_LOCAL 仅 data_query（env_context 无 executor）。
    """

    def __init__(self, db: AsyncSession, principal: CapabilityPrincipal) -> None:
        self._db = db
        self._principal = principal

    async def execute(
        self,
        request: CapabilityExecutionRequest,
        definition: CapabilityDefinition,
    ) -> HandlerExecutionResult:
        del definition
        from app.agents.contracts import ExecutionContext, SkillRequest
        from app.agents.skill_registry import REGISTRY
        from app.models.agent import AgentRole

        descriptor = REGISTRY.get(request.capability_key)
        if descriptor is None or descriptor.executor_factory is None:
            raise LookupError(f"Capability handler {request.capability_key} is unavailable")
        arguments = json.loads(request.arguments_json)
        # 远端调用方无 agent 上下文：以 expert_id 造最小 role/context 供 executor 取数。
        role = AgentRole(id=self._principal.expert_id, name="capability-provider")
        context = ExecutionContext(user_id=self._principal.principal_id)
        legacy = await descriptor.executor_factory().execute(
            self._db,
            role,
            SkillRequest(
                skill_key=request.capability_key,
                action_index=request.action_index,
                arguments=arguments if isinstance(arguments, dict) else {},
                raw_text=request.raw_text,
            ),
            context,
        )
        return HandlerExecutionResult(
            notes=tuple(legacy.notes),
            dataset_json=tuple(
                json.dumps(item, ensure_ascii=False, separators=(",", ":"))
                for item in legacy.datasets
            ),
            artifact_json=tuple(
                json.dumps(item, ensure_ascii=False, separators=(",", ":"))
                for item in legacy.artifacts
            ),
        )


@router.post("/internal/capabilities/execute")
async def execute_capability(
    body: CapabilityExecuteRequest,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    _claims: Annotated[object, Depends(require_service(CAPABILITIES_EXECUTE_SCOPE))],
) -> dict[str, Any]:
    """同步执行一个 SYNC_LOCAL 能力并返结果。

    传输门：未注册 → 封套 status=rejected（200，业务拒绝）；EVENT_GATED → 409（协议层资格拒绝，
    让调用方区分「有写须走事件门禁」于业务结果）；SYNC_LOCAL → 全链执行。
    """
    override = getattr(request.app.state, PROVIDER_OVERRIDE_KEY, None)
    if override is None:  # 组合根未注入 catalog（不应发生：wiring 挂路由时必注入）。
        raise HTTPException(status_code=503, detail="capability provider 未装配")
    catalog: CapabilityCatalogPort = override.catalog

    definition = await catalog.resolve(body.capability_key, body.capability_version)
    if definition is None:
        return ok(
            {
                "status": "rejected",
                "capability_key": body.capability_key,
                "capability_version": body.capability_version,
                "error": "not_registered",
                "trace_id": str(body.trace_id) if body.trace_id else None,
            }
        )
    transport = capability_transport(definition)
    if transport is CapabilityTransport.EVENT_GATED:
        raise HTTPException(status_code=409, detail="能力有写副作用，须走事件门禁（非同步就地）")

    # permission_keys 源自 definition 而非请求体（信任边界：服务身份获准执行即拥有其声明所需权限）。
    principal = CapabilityPrincipal(
        principal_id=None,
        expert_id=body.expert_id,
        permission_keys=definition.permission_keys,
    )
    handler: CapabilityHandlerPort = (
        override.handler(db, principal)
        if override.handler is not None
        else _RegistryHandler(db, principal)
    )

    execution_request = CapabilityExecutionRequest(
        capability_key=body.capability_key,
        capability_version=body.capability_version,
        action_index=body.action_index,
        arguments_json=json.dumps(body.arguments, ensure_ascii=False),
        raw_text=body.raw_text,
        principal=principal,
        trace=CapabilityTrace(trace_id=body.trace_id),
        idempotency_key=body.idempotency_key,
    )
    result = await CapabilityExecutionApplication(
        catalog=catalog,
        authorization=CurrentCapabilityAuthorization(),
        approval=CurrentCapabilityApproval(),
        uow=SQLAlchemyCapabilityExecutionUnitOfWork(db),
        handler=handler,
    ).execute(execution_request)
    await db.commit()

    logger.info(
        "同步能力执行 key=%s ver=%s status=%s transport=%s trace_id=%s",
        result.capability_key,
        result.capability_version,
        result.status.value,
        transport.value,
        str(body.trace_id) if body.trace_id else "-",
    )
    return ok(
        {
            "status": result.status.value,
            "capability_key": result.capability_key,
            "capability_version": result.capability_version,
            "invocation_id": str(result.invocation_id) if result.invocation_id else None,
            "output_json": result.output_json,
            "notes": list(result.notes),
            "dataset_json": list(result.dataset_json),
            "artifact_json": list(result.artifact_json),
            "replayed": result.replayed,
            "error": result.error.message if result.error else None,
            "trace_id": str(body.trace_id) if body.trace_id else None,
        }
    )
