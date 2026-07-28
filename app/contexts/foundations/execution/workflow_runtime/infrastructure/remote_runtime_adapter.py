"""Explicitly unwired placeholder for a future remote Runtime v2 transport."""

from __future__ import annotations

from app.contexts.foundations.execution.workflow_runtime.contracts.runtime_v2 import (
    RuntimeStartResultV2,
    RuntimeSubmissionV2,
)


class RemoteRuntimeNotConfiguredError(RuntimeError):
    """Raised until authentication, transport, and reliability gates are complete."""


class RemoteRuntimeAdapter:
    """Reserve the remote branch without making an unsafe production network call."""

    async def submit(self, submission: RuntimeSubmissionV2) -> RuntimeStartResultV2:
        del submission
        raise RemoteRuntimeNotConfiguredError(
            "remote workflow runtime is not configured; keep routing local"
        )
