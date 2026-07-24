"""Focused tests for the shared legacy directive execution skeleton."""

from __future__ import annotations

import uuid
from typing import cast

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.contracts import ExecutionContext, SkillRequest, SkillResult
from app.agents.directive_dispatch import (
    dispatch_requests as canonical_dispatch_requests,
)
from app.agents.directive_dispatch import (
    merge_execution_context as canonical_merge_execution_context,
)
from app.agents.legacy_skill_adapters import dispatch_requests, merge_execution_context
from app.models.agent import AgentRole


def _role() -> AgentRole:
    return AgentRole(name="测试专家", prompt_template="")


def test_legacy_skill_adapter_reexports_shared_dispatch_helpers() -> None:
    assert dispatch_requests is canonical_dispatch_requests
    assert merge_execution_context is canonical_merge_execution_context


async def test_dispatch_requests_prefers_injected_dispatcher() -> None:
    class ForbiddenExecutor:
        def requires_idempotency(self, _request: SkillRequest) -> bool:
            return False

        async def execute(
            self,
            _db: AsyncSession,
            _role: AgentRole,
            _request: SkillRequest,
            _context: ExecutionContext,
        ) -> SkillResult:
            raise AssertionError("dispatcher path must not execute a fallback executor")

    class Dispatcher:
        async def dispatch(
            self,
            _db: AsyncSession,
            _role: AgentRole,
            request: SkillRequest,
            _context: ExecutionContext,
        ) -> SkillResult:
            return SkillResult(notes=[request.skill_key])

    def forbidden_factory() -> ForbiddenExecutor:
        raise AssertionError("dispatcher path must not construct a fallback executor")

    result = await dispatch_requests(
        cast(AsyncSession, object()),
        _role(),
        [SkillRequest(skill_key="query", action_index=0)],
        ExecutionContext(dispatcher=Dispatcher()),
        executor_factory=forbidden_factory,
        failure_note=lambda request: f"failed:{request.action_index}",
    )

    assert result.notes == ["query"]


async def test_dispatch_requests_isolates_one_action_failure() -> None:
    class Executor:
        def requires_idempotency(self, _request: SkillRequest) -> bool:
            return False

        async def execute(
            self,
            _db: AsyncSession,
            _role: AgentRole,
            request: SkillRequest,
            _context: ExecutionContext,
        ) -> SkillResult:
            if request.action_index == 0:
                raise RuntimeError("boom")
            return SkillResult(notes=["second action completed"])

    result = await dispatch_requests(
        cast(AsyncSession, object()),
        _role(),
        [
            SkillRequest(skill_key="query", action_index=0),
            SkillRequest(skill_key="query", action_index=1),
        ],
        ExecutionContext(),
        executor_factory=Executor,
        failure_note=lambda request: f"failed:{request.action_index}",
    )

    assert result.notes == ["failed:0", "second action completed"]


def test_merge_execution_context_preserves_values_and_unions_exclusions() -> None:
    existing_user = uuid.uuid4()
    existing = ExecutionContext(
        user_id=existing_user,
        user_intent="existing intent",
        excluded_skills=frozenset({"collab"}),
    )

    merged = merge_execution_context(
        existing,
        user_id=uuid.uuid4(),
        user_intent="replacement intent",
        exclude={"deliver"},
    )

    assert merged.user_id == existing_user
    assert merged.user_intent == "existing intent"
    assert merged.excluded_skills == frozenset({"collab", "deliver"})
