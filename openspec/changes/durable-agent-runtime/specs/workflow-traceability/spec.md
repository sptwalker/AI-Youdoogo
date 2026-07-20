## ADDED Requirements

### Requirement: End-to-end trace identifiers
Every workflow run SHALL have a stable trace identifier propagated to steps, events, Agent task records, LLM usage records, and tool executions.

#### Scenario: User inspects a completed workflow
- **WHEN** the workflow progress or audit data is queried
- **THEN** all Agent, LLM, tool, and state transition records can be correlated by workflow and trace identifiers

### Requirement: Append-only workflow events
Every workflow status transition, lease claim, retry, human approval, and terminal outcome SHALL append a workflow event.

#### Scenario: Step is retried after lease expiry
- **WHEN** a later attempt claims the step
- **THEN** the event history retains both the expired attempt and the new claim

### Requirement: Structured progress snapshot
The orchestration progress API SHALL return persisted workflow status, step status, attempt information, red-line state, and TaskCard references.

#### Scenario: Workflow waits for human approval
- **WHEN** one or more red-line steps are waiting_human
- **THEN** the progress response identifies those steps and reports the workflow as waiting_human

### Requirement: Queryable execution failures
The system SHALL persist the latest execution error and attempt count for workflow steps, outbox events, and tool executions.

#### Scenario: Retry limit is exhausted
- **WHEN** an event or step reaches its retry limit
- **THEN** the workflow exposes a failed state with a traceable error instead of silently falling back
