## ADDED Requirements

### Requirement: Transactional event enqueue
The system SHALL write outbox events in the same transaction as the workflow state change that requires them.

#### Scenario: Workflow submission commits
- **WHEN** a workflow is successfully submitted
- **THEN** a pending workflow advance event is committed with it and cannot be lost between database commit and worker notification

### Requirement: Durable outbox claim
The worker SHALL claim pending or expired outbox events with a lease and SHALL prevent concurrent processing of the same active event.

#### Scenario: Multiple application workers poll
- **WHEN** multiple processes poll the outbox concurrently
- **THEN** each event is actively processed by no more than one process

### Requirement: Retry with bounded attempts
The worker SHALL record attempts, last error, next availability, and final failure after a configured retry limit.

#### Scenario: Handler raises a transient error
- **WHEN** an outbox handler fails before the retry limit
- **THEN** the event returns to pending with a later available time and the failure is recorded

### Requirement: Non-blocking application lifecycle
The system SHALL run the outbox loop as a background task and SHALL stop it cleanly during application shutdown.

#### Scenario: Application starts with pending work
- **WHEN** FastAPI lifespan starts
- **THEN** readiness is not blocked by workflow execution and the background worker begins polling pending events
