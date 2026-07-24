"""SQLAlchemy invocation repository and UoW for ToolExecution idempotency."""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.execution.capability_execution.application.ports import (
    InvocationClaim,
)
from app.contexts.foundations.execution.capability_execution.contracts.execution import (
    CapabilityExecutionError,
    CapabilityExecutionRequest,
    CapabilityExecutionResult,
    CapabilityExecutionStatus,
)
from app.models.workflow import (
    TOOL_FAILED,
    TOOL_RUNNING,
    TOOL_SUCCEEDED,
    ToolExecution,
)
from app.platform.database.unit_of_work import SessionUnitOfWork


def _json_items(values: tuple[str, ...]) -> list[Any]:
    return [json.loads(value) for value in values]


def _stored_result(record: ToolExecution) -> CapabilityExecutionResult:
    data = record.result_data or {}
    return CapabilityExecutionResult(
        status=CapabilityExecutionStatus.SUCCEEDED,
        capability_key=record.tool_key,
        capability_version=str(data.get("capability_version") or "1.0"),
        invocation_id=record.id,
        output_json=str(data.get("output_json") or "{}"),
        notes=tuple(str(item) for item in (data.get("notes") or [])),
        dataset_json=tuple(
            json.dumps(item, ensure_ascii=False, separators=(",", ":"))
            for item in (data.get("datasets") or [])
        ),
        artifact_json=tuple(
            json.dumps(item, ensure_ascii=False, separators=(",", ":"))
            for item in (data.get("artifacts") or [])
        ),
        audit_correlation_id=record.trace_id,
    )


def _result_data(result: CapabilityExecutionResult) -> dict[str, Any]:
    return {
        "capability_version": result.capability_version,
        "output_json": result.output_json,
        "notes": list(result.notes),
        "datasets": _json_items(result.dataset_json),
        "artifacts": _json_items(result.artifact_json),
    }


class SQLAlchemyCapabilityInvocationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def claim(self, request: CapabilityExecutionRequest) -> InvocationClaim:
        if request.idempotency_key is None:
            raise ValueError("Idempotent invocation requires a key")
        existing = await self._find_by_key(request.idempotency_key)
        if existing is not None:
            if existing.status == TOOL_SUCCEEDED:
                return InvocationClaim(existing.id, _stored_result(existing))
            self._mark_running(existing, request)
            await self._session.flush()
            return InvocationClaim(existing.id)

        record = ToolExecution(
            workflow_run_id=request.trace.workflow_run_id,
            workflow_step_id=request.trace.workflow_step_id,
            trace_id=request.trace.trace_id,
            attempt=request.trace.attempt or 0,
            tool_key=request.capability_key,
            idempotency_key=request.idempotency_key,
            status=TOOL_RUNNING,
            request_data=self._request_data(request),
        )
        try:
            async with self._session.begin_nested():
                self._session.add(record)
                await self._session.flush()
        except IntegrityError:
            concurrent = await self._find_by_key(request.idempotency_key)
            if concurrent is None:
                raise
            return InvocationClaim(
                concurrent.id,
                _stored_result(concurrent) if concurrent.status == TOOL_SUCCEEDED else None,
            )
        return InvocationClaim(record.id)

    async def succeed(
        self, invocation_id: uuid.UUID, result: CapabilityExecutionResult
    ) -> None:
        record = await self._require(invocation_id)
        record.status = TOOL_SUCCEEDED
        record.result_data = _result_data(result)
        record.error_msg = None
        await self._session.flush()

    async def fail(self, invocation_id: uuid.UUID, error_message: str) -> None:
        record = await self._require(invocation_id)
        record.status = TOOL_FAILED
        record.error_msg = error_message[:2000]
        await self._session.flush()

    async def begin_compatibility(
        self,
        request: CapabilityExecutionRequest,
    ) -> tuple[ToolExecution, bool]:
        claim = await self.claim(request)
        record = await self._require(claim.invocation_id)
        return record, claim.replay_result is not None

    async def succeed_compatibility(
        self, record: ToolExecution, result_data: dict[str, Any]
    ) -> None:
        record.status = TOOL_SUCCEEDED
        record.result_data = result_data
        record.error_msg = None
        await self._session.flush()

    async def fail_compatibility(self, record: ToolExecution, error_message: str) -> None:
        record.status = TOOL_FAILED
        record.error_msg = error_message[:2000]
        await self._session.flush()

    async def _find_by_key(self, key: str) -> ToolExecution | None:
        statement = select(ToolExecution).where(ToolExecution.idempotency_key == key)
        return (await self._session.execute(statement)).scalar_one_or_none()

    async def _require(self, invocation_id: uuid.UUID) -> ToolExecution:
        record = await self._session.get(ToolExecution, invocation_id)
        if record is None:
            raise LookupError(f"ToolExecution {invocation_id} is unavailable")
        return record

    @staticmethod
    def _mark_running(
        record: ToolExecution, request: CapabilityExecutionRequest
    ) -> None:
        record.status = TOOL_RUNNING
        record.workflow_run_id = request.trace.workflow_run_id
        record.workflow_step_id = request.trace.workflow_step_id
        record.trace_id = request.trace.trace_id
        record.attempt = request.trace.attempt or record.attempt
        record.request_data = SQLAlchemyCapabilityInvocationRepository._request_data(request)
        record.error_msg = None

    @staticmethod
    def _request_data(request: CapabilityExecutionRequest) -> dict[str, Any]:
        return {
            "skill_key": request.capability_key,
            "capability_version": request.capability_version,
            "action_index": request.action_index,
            "arguments": json.loads(request.arguments_json),
            "raw_text": request.raw_text,
        }


class SQLAlchemyCapabilityExecutionUnitOfWork(SessionUnitOfWork):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self._invocations = SQLAlchemyCapabilityInvocationRepository(session)

    @property
    def invocations(self) -> SQLAlchemyCapabilityInvocationRepository:
        return self._invocations


def failed_result(
    request: CapabilityExecutionRequest, error_message: str
) -> CapabilityExecutionResult:
    """Compatibility helper used by the legacy ToolExecution facade."""
    return CapabilityExecutionResult(
        status=CapabilityExecutionStatus.FAILED,
        capability_key=request.capability_key,
        capability_version=request.capability_version or "1.0",
        error=CapabilityExecutionError(code="execution_failed", message=error_message),
    )
