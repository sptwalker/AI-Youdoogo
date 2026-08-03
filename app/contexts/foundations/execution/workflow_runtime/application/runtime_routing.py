"""Creation-time Runtime v2 routing with immutable instance ownership."""

from __future__ import annotations

from collections.abc import Mapping

from app.contexts.foundations.execution.workflow_runtime.application.runtime_v2_ports import (
    RuntimeClientPort,
)
from app.contexts.foundations.execution.workflow_runtime.contracts.runtime_v2 import (
    RuntimeEngine,
    RuntimeInstanceRefV2,
    RuntimeStartResultV2,
    RuntimeSubmissionV2,
)


class RuntimeAdapterNotConfiguredError(RuntimeError):
    """Raised when a selected runtime engine has no configured adapter."""


class RuntimeEngineTakeoverError(RuntimeError):
    """Raised when code attempts to move an active instance to another engine."""


class RuntimeRoutingPolicy:
    """Resolve an engine only for a new submission; unspecified types stay local."""

    def __init__(self, routes: Mapping[str, RuntimeEngine] | None = None) -> None:
        self._routes = dict(routes or {})

    def resolve_new(self, workflow_type: str) -> RuntimeEngine:
        if not workflow_type.strip():
            raise ValueError("runtime workflow type must not be blank")
        return self._routes.get(workflow_type, RuntimeEngine.LOCAL)

    def resolve_existing(
        self,
        instance: RuntimeInstanceRefV2,
        *,
        requested_engine: RuntimeEngine | None = None,
    ) -> RuntimeEngine:
        if requested_engine is not None and requested_engine != instance.engine:
            raise RuntimeEngineTakeoverError(
                "active runtime instances cannot be taken over by another engine"
            )
        return instance.engine


class RoutedRuntimeClient:
    """Select a branch at creation and return an engine-pinned instance reference."""

    def __init__(
        self,
        local: RuntimeClientPort,
        *,
        remote: RuntimeClientPort | None = None,
        policy: RuntimeRoutingPolicy | None = None,
    ) -> None:
        self._clients: dict[RuntimeEngine, RuntimeClientPort] = {RuntimeEngine.LOCAL: local}
        if remote is not None:
            self._clients[RuntimeEngine.REMOTE] = remote
        self._policy = policy or RuntimeRoutingPolicy()

    async def submit(self, submission: RuntimeSubmissionV2) -> RuntimeStartResultV2:
        engine = self._policy.resolve_new(submission.workflow_type)
        client = self._client(engine)
        result = await client.submit(submission)
        if result.instance.engine != engine:
            raise RuntimeError("runtime adapter returned an instance for another engine")
        if result.instance.business_key != submission.business_key:
            raise RuntimeError("runtime adapter changed the submission business key")
        if result.instance.workflow_type != submission.workflow_type:
            raise RuntimeError("runtime adapter changed the workflow type")
        return result

    def client_for_existing(
        self,
        instance: RuntimeInstanceRefV2,
        *,
        requested_engine: RuntimeEngine | None = None,
    ) -> RuntimeClientPort:
        engine = self._policy.resolve_existing(
            instance,
            requested_engine=requested_engine,
        )
        return self._client(engine)

    def _client(self, engine: RuntimeEngine) -> RuntimeClientPort:
        try:
            return self._clients[engine]
        except KeyError as exc:
            raise RuntimeAdapterNotConfiguredError(
                f"runtime adapter is not configured: {engine.value}"
            ) from exc
