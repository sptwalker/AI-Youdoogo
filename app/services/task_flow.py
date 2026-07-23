"""One-way compatibility facade for the Task Management state machine."""

from app.contexts.business.task_management.domain.state_machine import (
    ACCEPTED,
    CANCELLED,
    CREATED,
    DISPATCHED,
    EXECUTING,
    REJECTED,
    REPORTED,
    STATES,
    TERMINAL,
    TRANSITIONS,
    assert_transition,
    can_transition,
)

__all__ = [
    "ACCEPTED",
    "CANCELLED",
    "CREATED",
    "DISPATCHED",
    "EXECUTING",
    "REJECTED",
    "REPORTED",
    "STATES",
    "TERMINAL",
    "TRANSITIONS",
    "assert_transition",
    "can_transition",
]
