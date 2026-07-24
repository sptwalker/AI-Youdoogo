"""Compatibility checks for the Workflow Runtime SQLAlchemy state facade."""

from app.contexts.foundations.execution.workflow_runtime.infrastructure import (
    failure_propagation,
    human_decisions,
    progress_events,
    sqlalchemy_state,
    step_completion,
    step_leases,
)


def test_sqlalchemy_state_reexports_focused_runtime_operations() -> None:
    assert sqlalchemy_state.StepClaimResult is step_leases.StepClaimResult
    assert sqlalchemy_state.claim_step_result is step_leases.claim_step_result
    assert sqlalchemy_state.claim_step is step_leases.claim_step
    assert sqlalchemy_state.renew_step_lease is step_leases.renew_step_lease
    assert sqlalchemy_state.ready_steps is step_leases.ready_steps
    assert sqlalchemy_state.complete_step is step_completion.complete_step
    assert sqlalchemy_state.pipe_outputs is step_completion.pipe_outputs
    assert sqlalchemy_state.accept_human_step is human_decisions.accept_human_step
    assert sqlalchemy_state.apply_task_decision is human_decisions.apply_task_decision
    assert sqlalchemy_state.fail_from_outbox is failure_propagation.fail_from_outbox
    assert sqlalchemy_state._run_progress_event is progress_events._run_progress_event
    assert sqlalchemy_state._step_progress_event is progress_events._step_progress_event
