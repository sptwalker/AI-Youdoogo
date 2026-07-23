## ADDED Requirements

### Requirement: Execution contracts are framework independent
Published contracts for Agent Execution, Capability Catalog and Execution, Work Planning, Workflow Runtime, and Task Management SHALL use immutable or validation-oriented plain data structures and stable identifiers. These contracts MUST NOT expose `AsyncSession`, SQLAlchemy ORM models, FastAPI request or response types, repositories, vendor SDK objects, or mutable entities owned by another context.

#### Scenario: Execution boundary types are statically inspected
- **WHEN** contract modules and their public annotations are analyzed
- **THEN** no database session, ORM model, transport type, repository implementation, vendor SDK type, or cross-context mutable entity is present

#### Scenario: An outer adapter loads persistence records
- **WHEN** an Infrastructure adapter loads ORM rows needed by an execution use case
- **THEN** it translates them into the owning context's contract or domain values before invoking Application code

### Requirement: Agent execution uses explicit request, result, trace, and ports
Agent Execution SHALL accept an `AgentExecutionRequest`, consume an immutable expert execution snapshot and explicit `ExecutionTrace`, obtain external behavior only through injected execution ports, and return a structured `AgentExecutionResult`. Agent Execution MUST NOT receive an `AsyncSession` or `AgentRole` ORM object and MUST NOT mutate WorkflowStep, TaskCard, CapabilityDefinition, or ToolExecution records owned outside its boundary.

#### Scenario: Workflow Runtime invokes an Agent
- **WHEN** a workflow step requires Agent execution
- **THEN** Workflow Runtime calls an `AgentExecutionPort` with plain request, expert snapshot, trace, task input, and context references and receives a structured result with status, content, evidence, usage, sources, capability activity, and normalized error information

#### Scenario: Agent requests a capability
- **WHEN** an Agent needs a registered capability during execution
- **THEN** it calls the injected Capability Execution port and does not import a concrete dispatcher, Tool implementation, ORM model, or database session

### Requirement: Capability catalog and execution have separate contracts
Capability Catalog SHALL publish versioned capability definitions containing schemas, risk, side-effect, permission, and handler identity metadata. Capability Execution SHALL own invocation validation, authorization, approval checks, idempotency, execution records, dispatch, and result normalization, while target business rules MUST remain behind the target context's port.

#### Scenario: Capability invocation is accepted
- **WHEN** a request names a registered capability version and satisfies its schema, authorization, risk, approval, and idempotency requirements
- **THEN** Capability Execution records or reuses the idempotent invocation, calls the target context through a port, and returns a structured result with evidence and audit correlation

#### Scenario: Capability targets another business context
- **WHEN** a capability performs knowledge search, governed data query, connector invocation, deliverable creation, or collaboration work
- **THEN** Capability Execution delegates through that target context's published port and does not import or modify its ORM model or internal service

### Requirement: Planning, runtime, and task lifecycles remain separate
Work Planning SHALL translate a work intent into a validated `WorkflowPlan` and MUST NOT persist or mutate WorkflowRun, WorkflowStep, or TaskCard state. Workflow Runtime SHALL own durable run and step state, leases, attempts, retries, recovery, and human stops. Task Management SHALL own TaskCard assignment, acceptance, rejection, and task history.

#### Scenario: A plan is produced
- **WHEN** Work Planning accepts a valid work intent and context snapshot
- **THEN** it returns a plain `WorkflowPlan` without creating runtime or task persistence records

#### Scenario: A workflow is started
- **WHEN** Workflow Runtime accepts a valid `WorkflowPlan`
- **THEN** it creates and advances its durable run and step state without transferring write ownership to Work Planning or Task Management

#### Scenario: Human-facing task state changes
- **WHEN** a user accepts or rejects a TaskCard
- **THEN** Task Management changes its own aggregate and communicates the decision to Workflow Runtime without directly updating WorkflowStep storage

### Requirement: Cross-context execution collaboration uses ports and events
Agent, Capability, Planning, Workflow, and Task contexts SHALL coordinate synchronous requests through Application-owned ports and asynchronous state propagation through versioned integration events. They MUST NOT call another context's legacy service implementation, share a transaction object, or directly update another context's tables.

#### Scenario: Workflow progress creates or updates a TaskCard
- **WHEN** Workflow Runtime commits a progress transition that requires a human-facing task projection
- **THEN** it publishes a versioned workflow progress event and Task Management idempotently applies the event to its own TaskCard state

#### Scenario: Task decision resumes a workflow
- **WHEN** Task Management commits an accepted or rejected decision
- **THEN** it publishes a versioned task decision event and Workflow Runtime revalidates its current state and event version before applying the corresponding transition

#### Scenario: An integration event is delivered more than once
- **WHEN** a Workflow or Task integration event is duplicated, delayed, or replayed
- **THEN** the consumer preserves a single valid state transition and does not repeat the business side effect

### Requirement: Application owns ports and transaction boundaries
Each execution Application use case SHALL define the repository, Unit of Work, event publisher, clock, and external execution ports it needs. Infrastructure SHALL implement those ports, repositories SHALL flush rather than independently commit, and the use case or its Unit of Work SHALL atomically commit owned state with its Outbox events.

#### Scenario: Short state-changing use case succeeds
- **WHEN** an execution use case changes an owned aggregate and emits integration events
- **THEN** its Unit of Work commits the aggregate changes and Outbox records atomically

#### Scenario: Application use case is tested without infrastructure
- **WHEN** an Agent, Capability, Planning, Workflow, or Task use case is executed in a unit test
- **THEN** fake ports and a fake Unit of Work can verify its behavior without FastAPI, SQLAlchemy, PostgreSQL, Redis, HTTP, or an LLM provider

### Requirement: Long-running external execution does not hold a database transaction
LLM, Tool, HTTP, MCP, sandbox, and object-storage operations SHALL execute outside an open database transaction. The owning use case MUST first commit claim, lease, attempt, or pending execution state, then perform external I/O, and finally open a new transaction that verifies ownership and version before recording the result and follow-up events.

#### Scenario: Workflow step performs external execution
- **WHEN** a claimed workflow step invokes an Agent, Capability, connector, LLM, MCP server, sandbox, or object store
- **THEN** the claim or pending record is committed before the call and the result is finalized in a separate transaction after owner, lease, attempt, and version checks

#### Scenario: Lease changes during external execution
- **WHEN** the finalization transaction finds that ownership, attempt, lease, or version no longer matches the committed claim
- **THEN** it rejects the stale result and does not apply its state transition or side effects a second time

### Requirement: Contract migration preserves supported behavior
Adapters and one-way compatibility facades SHALL preserve existing public call shapes, response semantics, database schema, durable PostgreSQL workflow behavior, ToolExecution idempotency, retry and recovery behavior, and authenticated human-stop behavior while callers migrate to the clean contracts. Canonical execution modules MUST NOT depend on those facades.

#### Scenario: Existing caller uses a legacy execution entrypoint
- **WHEN** an unmigrated caller invokes a supported Agent, Capability, Workflow, Planning, or Task entrypoint
- **THEN** the compatibility adapter translates the call to the clean request and result contracts and returns the previously supported observable outcome

#### Scenario: Durable workflow resumes after contract migration
- **WHEN** an existing persisted workflow is claimed, retried, resumed after a human decision, or recovered after a worker restart
- **THEN** it follows the same valid state transitions, attempt and lease protections, idempotency rules, and evidence recording as before the migration
