"""Pure Workflow Runtime status precedence tests."""

from types import SimpleNamespace
from typing import cast

import pytest

from app.contexts.foundations.execution.workflow_runtime.infrastructure import (
    sqlalchemy_projection,
)
from app.models.workflow import (
    RUN_CANCELLED,
    RUN_FAILED,
    RUN_QUEUED,
    RUN_RUNNING,
    RUN_SUCCEEDED,
    RUN_WAITING_HUMAN,
    STEP_CANCELLED,
    STEP_FAILED,
    STEP_RUNNING,
    STEP_SUCCEEDED,
    STEP_WAITING_HUMAN,
    WorkflowStep,
)


def _step(status: str) -> WorkflowStep:
    return cast(WorkflowStep, SimpleNamespace(status=status, last_error=None))


@pytest.mark.parametrize(
    ("statuses", "expected"),
    [
        ((), RUN_QUEUED),
        ((STEP_SUCCEEDED,), RUN_SUCCEEDED),
        ((STEP_FAILED, STEP_CANCELLED), RUN_CANCELLED),
        ((STEP_FAILED, STEP_WAITING_HUMAN), RUN_FAILED),
        ((STEP_WAITING_HUMAN, STEP_RUNNING), RUN_WAITING_HUMAN),
        ((STEP_SUCCEEDED, STEP_RUNNING), RUN_RUNNING),
    ],
)
def test_derive_run_status_preserves_precedence(
    statuses: tuple[str, ...],
    expected: str,
) -> None:
    assert sqlalchemy_projection.derive_run_status(
        tuple(_step(status) for status in statuses)
    ) == expected
