## ADDED Requirements

### Requirement: Workflow responsibilities are modular
Workflow persistence, state transitions, projections, recovery, event handling, and external step execution SHALL reside behind separate internal modules with a compatibility facade for existing callers.

#### Scenario: Existing caller imports workflow_service
- **WHEN** existing code or tests import a public workflow operation from `workflow_service`
- **THEN** the same operation remains available while its implementation is delegated to the focused module

### Requirement: Durable and legacy orchestration are isolated
The durable orchestration entrypoint SHALL not contain the implementation of the legacy synchronous TaskCard DAG executor.

#### Scenario: A legacy workflow is resumed
- **WHEN** no WorkflowRun exists for an accepted TaskCard step
- **THEN** the facade explicitly delegates to the legacy orchestration adapter without changing the durable Worker path

### Requirement: Worker loop is independent from step execution
The background Worker loop SHALL process event dispositions without directly implementing Agent, skill, heartbeat, or workflow result logic.

#### Scenario: Step execution is deferred
- **WHEN** the event handler returns a defer disposition
- **THEN** the loop updates Outbox availability without invoking Agent execution

### Requirement: Typed skill imports remain acyclic
Skill executors SHALL depend on typed contracts and injected ports and MUST NOT import the concrete Agent base runtime.

#### Scenario: Module graph is checked
- **WHEN** the application import graph is analyzed after the split
- **THEN** no import cycle exists among Agent base, skill registry/dispatcher, and skill services

### Requirement: LangGraph reliability boundary is preserved
Any future LangGraph adapter SHALL operate through planner or transition ports and MUST NOT bypass WorkflowRun/Step, Outbox, ToolExecution, or human approval persistence.

#### Scenario: A planner adapter is selected
- **WHEN** a LangGraph planner produces workflow steps
- **THEN** submission and execution still use the existing PostgreSQL durable runtime
