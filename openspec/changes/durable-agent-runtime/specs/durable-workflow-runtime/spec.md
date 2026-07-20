## ADDED Requirements

### Requirement: Atomic workflow creation
The system SHALL persist a workflow run, all workflow steps, dependencies, TaskCard mirrors, initial events, and the first outbox event in one database transaction.

#### Scenario: Step creation fails
- **WHEN** any workflow step or dependency cannot be persisted
- **THEN** the system rolls back the workflow run, all step and TaskCard mirrors, and all related events

### Requirement: Exclusive step lease
The system SHALL allow at most one active worker lease for a runnable workflow step.

#### Scenario: Two workers claim the same step
- **WHEN** two workers concurrently attempt to claim one queued step
- **THEN** exactly one claim succeeds and only that worker may invoke the Agent runtime

### Requirement: Persisted workflow lifecycle
The system SHALL persist workflow status independently from TaskCard status and SHALL support queued, running, waiting_human, succeeded, failed, and cancelled terminal semantics.

#### Scenario: All steps complete
- **WHEN** every workflow step reaches succeeded
- **THEN** the workflow run becomes succeeded and its parent TaskCard mirror leaves executing state

### Requirement: Human approval stop
The system MUST NOT automatically advance a red-line step beyond waiting_human.

#### Scenario: Human accepts a red-line step
- **WHEN** an authenticated human accepts the linked TaskCard
- **THEN** the workflow step becomes succeeded and a resume event is enqueued without executing downstream work inside the HTTP request

### Requirement: Lease-based recovery
The system SHALL recover only steps whose execution lease has expired.

#### Scenario: Process crashes during a step
- **WHEN** a worker disappears and the step lease expires
- **THEN** another worker may claim a new attempt while completed and waiting_human steps remain unchanged
