## ADDED Requirements

### Requirement: Unique tool execution key
Every side-effecting skill invocation SHALL have a unique idempotency key persisted before the external side effect begins.

#### Scenario: Duplicate event replays a completed tool call
- **WHEN** the same idempotency key is submitted after a successful execution
- **THEN** the system returns the stored result without invoking the external side effect again

### Requirement: Idempotent file delivery
File delivery SHALL reuse one Deliverable record and one deterministic object path for one idempotency key.

#### Scenario: Worker crashes after object upload
- **WHEN** delivery is retried after the object was uploaded but before the workflow step completed
- **THEN** the retry updates or reuses the same Deliverable and does not create a duplicate visible file

### Requirement: Idempotent collaboration request
Collaboration request creation SHALL be deduplicated by the tool execution idempotency key.

#### Scenario: Collaboration action is retried
- **WHEN** the same collaboration action is executed more than once
- **THEN** only one review request exists and subsequent executions return its reference

### Requirement: Attempt-aware LLM records
Agent and LLM usage records SHALL be associated with the workflow step and execution attempt that caused them.

#### Scenario: Expired attempt is retried
- **WHEN** a workflow step starts a later attempt
- **THEN** both attempts remain traceable while only the successful attempt may complete the step
