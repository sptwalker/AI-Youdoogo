"""Runtime v2 ports owned by the application boundary."""

from __future__ import annotations

from typing import Protocol

from app.contexts.foundations.execution.workflow_runtime.contracts.runtime_v2 import (
    RuntimeStartResultV2,
    RuntimeSubmissionV2,
)


class RuntimeClientPort(Protocol):
    """Narrow branch-by-abstraction boundary for accepting new workflows."""

    async def submit(self, submission: RuntimeSubmissionV2) -> RuntimeStartResultV2: ...
