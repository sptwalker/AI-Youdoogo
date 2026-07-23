## ADDED Requirements

### Requirement: Proposal Management owns a complete vertical slice
Proposal Management SHALL own the proposal lifecycle through its Domain, Application, Entrypoint, and Infrastructure modules. The slice MUST expose Application use cases for creating, retrieving, listing, researching, reviewing, and converting proposals, and proposal rules MUST NOT remain implemented in `app.services.proposal_service`, HTTP routers, ORM models, Agent adapters, or Task adapters.

#### Scenario: Proposal operation enters the canonical slice
- **WHEN** an HTTP entrypoint or another authorized caller creates, reads, lists, researches, reviews, or converts a proposal
- **THEN** the caller invokes a Proposal Management Application use case and the use case coordinates the owned Domain model and declared ports

#### Scenario: Proposal implementation is inspected after migration
- **WHEN** architecture tests inspect the canonical Proposal Management modules
- **THEN** the Domain and Application contain the proposal lifecycle behavior and have no dependency on legacy service implementations, FastAPI, SQLAlchemy ORM classes, or concrete Agent and Task implementations

### Requirement: Proposal lifecycle invariants are enforced by the domain
The Proposal Management Domain SHALL enforce the existing lifecycle invariants independently of HTTP and persistence. A newly created proposal MUST start in `draft`; AI research MUST NOT approve or reject a proposal; `approved` or `rejected` MUST result only from a human review of a `reviewed` proposal; a terminal proposal MUST NOT re-enter research; and conversion to one Task MUST be limited to an `approved` proposal that has not already been converted.

#### Scenario: AI research completes successfully
- **WHEN** an eligible non-terminal proposal completes AI research
- **THEN** the Domain records an AI research review and transitions the proposal through `researching` to `reviewed` without setting `approved` or `rejected`

#### Scenario: Human records a valid decision
- **WHEN** an authorized human reviewer submits `approve` or `reject` for a proposal in `reviewed`
- **THEN** the Domain records the human review and transitions the proposal to the corresponding terminal status

#### Scenario: Invalid lifecycle transition is requested
- **WHEN** research is requested for a terminal proposal, review is requested outside `reviewed`, conversion is requested before approval, or conversion is repeated
- **THEN** Proposal Management rejects the operation with its existing application or domain error semantics and does not persist a partial transition

### Requirement: Proposal Application defines explicit ports and transaction boundaries
Proposal Management Application SHALL define the repository, Unit of Work, expert-research, task-creation, visibility-policy, audit, clock, and identifier ports required by its use cases. Infrastructure adapters MUST translate ORM and external implementation objects into Proposal-owned values, repositories MUST flush rather than independently commit, and the Application or Unit of Work MUST own every Proposal transaction boundary.

#### Scenario: Proposal use case is unit tested
- **WHEN** a Proposal Application use case is executed with fake repositories, a fake Unit of Work, and fake external ports
- **THEN** its state transitions, returned result, emitted events, and commit or rollback behavior are verifiable without FastAPI, SQLAlchemy, PostgreSQL, an Agent runtime, or Task Management persistence

#### Scenario: AI research performs a long external call
- **WHEN** Proposal Management invokes the expert-research port for an eligible proposal
- **THEN** it commits the visible `researching` state before the external call and finalizes the review and `reviewed` state in a separate transaction without holding a database transaction across the Agent or reflection call

### Requirement: Proposal integrations preserve context ownership
Proposal Management SHALL collaborate with Expert or Agent Execution, Task Management, Access Control, and Audit Trail through Proposal-owned ports, provider-published contracts, or integration events. It MUST NOT pass `AsyncSession`, Proposal ORM rows, Task ORM rows, Agent ORM rows, or mutable cross-context entities across those boundaries, and it MUST NOT directly update another context's tables.

#### Scenario: Approved proposal is converted to execution work
- **WHEN** an authorized user converts an approved proposal that has not previously been converted
- **THEN** Proposal Management invokes a task-creation port with plain command data, records the returned Task identifier on its own aggregate, and does not import Task Management internals or mutate Task persistence directly

#### Scenario: Proposal research requests expert execution
- **WHEN** AI research requires the configured proposal expert
- **THEN** the Proposal use case invokes a plain expert-research contract and receives a normalized research result without receiving an Agent role ORM object or sharing its Unit of Work

### Requirement: Proposal observable behavior remains compatible
The completed Proposal Management slice SHALL preserve the supported proposal database schema, proposal and review values, row-level visibility, authorization rules, error mapping, audit effects, and API-visible state transitions. Any intentional behavior or schema change MUST be specified separately and MUST NOT be introduced implicitly by the structural migration.

#### Scenario: Existing proposal regression suite runs against the vertical slice
- **WHEN** existing API and service characterization tests exercise create, list, detail, AI research, human review, and conversion flows
- **THEN** they observe the same supported response data, visibility decisions, lifecycle transitions, audit records, and side-effect counts as before migration

#### Scenario: Existing proposal records are loaded after migration
- **WHEN** Infrastructure loads proposal and review rows written by the legacy implementation
- **THEN** the records are translated into the new Domain and returned without requiring a data migration or changing their public representation

### Requirement: Additional contexts migrate as behavior-complete vertical slices
Identity, Organization Structure, Environment Projection, Assistant Conversations, Group Messaging, Meeting Management, Wiki Management, Knowledge Indexing, Knowledge Retrieval, Semantic Catalog, Organizational Memory, and Operational Analytics SHALL migrate incrementally into their owning bounded contexts. Each migration increment MUST move one behavior-complete use case, its rules, its ports, and its data-access adapter together; it MUST NOT create an empty directory shell or merely relocate a horizontal service file unchanged.

#### Scenario: A context begins migration
- **WHEN** one of the listed contexts is selected for the next increment
- **THEN** the increment names a supported business use case, establishes its data owner and published boundary, and moves all behavior needed for that use case behind its Application entrypoint

#### Scenario: A context has more behavior than one safe increment
- **WHEN** a legacy service contains multiple independently changing use cases
- **THEN** the system migrates one characterized use case at a time while the remaining legacy operations continue to work through their existing paths

### Requirement: Vertical migration is characterization-first
Before a legacy use case is moved, the system MUST have characterization tests that lock its supported inputs, outputs, authorization, errors, state transitions, transaction boundaries, and externally observable side effects. The migrated Domain, Application, adapter, and Entrypoint tests SHALL demonstrate equivalent behavior before callers are switched.

#### Scenario: A legacy use case lacks sufficient tests
- **WHEN** a team attempts to migrate a behavior whose supported outcomes or side effects are not captured
- **THEN** characterization coverage is added before the canonical implementation replaces the legacy behavior

#### Scenario: A caller is switched to a new use case
- **WHEN** a migrated caller begins using the bounded-context Application boundary
- **THEN** characterization, contract, architecture, and regression tests pass with no duplicate write or externally visible behavior drift

### Requirement: Legacy services become temporary one-way compatibility facades
After a use case moves into a bounded context, its legacy service function SHALL only translate legacy arguments, invoke the canonical use case, and translate the result when required for compatibility. The facade MUST NOT own business branching, repository queries, transaction commits, or external execution, and the canonical context MUST NOT import the facade.

#### Scenario: An unmigrated caller invokes a moved operation
- **WHEN** an existing caller uses the retained legacy service function
- **THEN** the facade unconditionally delegates to the canonical Application use case and returns the previously supported result shape

#### Scenario: All callers of a compatibility operation are migrated
- **WHEN** repository and documented external compatibility checks show no remaining caller for the legacy operation
- **THEN** the facade operation and its obsolete implementation dependencies are removed

### Requirement: Each context retains sole write ownership during migration
Every migrated business fact SHALL have exactly one write-owning context throughout the transition. Other contexts MUST retain only identifiers, immutable snapshots, or their own read models and SHALL coordinate through versioned events or published queries with idempotent consumers where asynchronous propagation is used.

#### Scenario: A migrated source fact changes
- **WHEN** a context commits a change that another context projects or consumes
- **THEN** the source context atomically records its owned state and integration event, and the consumer updates only its own read model without writing the source table

#### Scenario: An integration event is replayed during a phased migration
- **WHEN** the same source event is delivered more than once to a new or legacy-compatible consumer
- **THEN** the consumer applies at most one valid projection or side effect and preserves the source context as the sole writer
