## ADDED Requirements

### Requirement: Busy step events remain recoverable
The worker SHALL distinguish a workflow step with an active lease from a terminal workflow step and MUST NOT permanently complete the only execution trigger for an actively leased step.

#### Scenario: Outbox event is replayed before the step lease expires
- **WHEN** another worker claims the step execution event while the workflow step still has a valid lease
- **THEN** the event is deferred until the step lease expires or the step reaches a terminal state

### Requirement: Expired running steps are re-enqueued
The system SHALL periodically discover running workflow steps whose leases expired and SHALL enqueue a deterministic execution event for each expired step version.

#### Scenario: Original execution event is no longer pending
- **WHEN** a running step lease expires after its original Outbox event was completed or lost
- **THEN** the recovery scan creates a deduplicated step execution event and another worker may claim a new attempt

### Requirement: Recovery preserves completed effects
Recovery SHALL reuse the workflow trace and stable logical idempotency prefix for retried step executions.

#### Scenario: A worker crashes after a side effect succeeds
- **WHEN** an expired step is reclaimed as a later attempt
- **THEN** ToolExecution returns the stored result for the same logical action and does not repeat the side effect

### Requirement: Recovery failures are observable
The recovery loop SHALL isolate scan failures from normal polling and SHALL log or persist enough context to diagnose repeated failures.

#### Scenario: Recovery scan query fails
- **WHEN** the database rejects one recovery scan
- **THEN** the worker continues normal Outbox polling and retries recovery on a later interval
