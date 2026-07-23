## ADDED Requirements

### Requirement: Application-wide module graph is acyclic
The system SHALL enforce an acyclic import graph across all runtime Python modules under `app`, including legacy compatibility packages, bounded contexts, Platform, and Bootstrap. Architecture diagnostics MUST identify every participating module when a cycle is detected.

#### Scenario: Repository-wide graph satisfies the boundary check
- **WHEN** the architecture test analyzes imports for every runtime Python module under `app`
- **THEN** the resulting directed module graph contains no cycle

#### Scenario: A cross-package cycle is introduced
- **WHEN** a runtime module is changed so that its imports close a dependency path back to itself
- **THEN** the architecture test fails and reports the modules participating in the cycle

### Requirement: Layer and context dependencies point inward
Domain and Application modules MUST remain independent from delivery, persistence, Platform implementations, and legacy horizontal implementation packages. A bounded context MUST collaborate with another context only through a caller-owned port, the provider's published contract or facade, or an integration event; it MUST NOT import the other context's Domain, Application, Entrypoint, or Infrastructure internals.

#### Scenario: A context needs data owned by another context
- **WHEN** an Application use case needs a synchronous result from another bounded context
- **THEN** it calls an Application-owned port whose outer adapter translates to the provider's published contract without importing the provider's internal layers

#### Scenario: New context code references a legacy implementation package
- **WHEN** a module under `app/contexts` imports business behavior from `app.services`, `app.models`, `app.agents`, or `app.knowledge`
- **THEN** the architecture boundary check fails with the forbidden dependency

### Requirement: Compatibility facades are one-way
Every retained legacy module SHALL be a one-way compatibility facade that re-exports or unconditionally delegates to the canonical bounded-context or Platform implementation. Canonical modules MUST NOT import their legacy facades, and a facade MUST NOT retain business branching, transaction ownership, or a duplicate implementation.

#### Scenario: Existing caller uses a legacy import path
- **WHEN** an existing caller imports a supported object or operation from a retained legacy module
- **THEN** it receives the canonical object or behavior through a one-way re-export or delegation

#### Scenario: Canonical implementation is inspected for reverse dependencies
- **WHEN** architecture tests analyze a canonical Context or Platform module
- **THEN** the module has no import path back to the legacy facade that exposes it

#### Scenario: Last legacy caller is migrated
- **WHEN** repository and documented external compatibility checks show that a facade has no remaining caller
- **THEN** the facade SHALL be removed instead of becoming a permanent parallel API

### Requirement: Package initialization is side-effect free
Runtime package `__init__.py` modules SHALL be safe to import without eagerly importing implementation submodules, registering handlers or capabilities, constructing runtime objects, opening resources, or triggering application wiring. Runtime callers MUST import the leaf module or explicit published contract they use.

#### Scenario: Agent or Knowledge package is imported
- **WHEN** a caller imports the top-level Agent or Knowledge package
- **THEN** no registry mutation, handler registration, infrastructure initialization, or eager implementation-module import occurs

#### Scenario: Runtime component needs a concrete implementation
- **WHEN** a runtime caller uses an Agent, Capability, or Knowledge implementation
- **THEN** it imports the owning leaf module directly or receives the implementation from Bootstrap composition

### Requirement: Environment Projection is decoupled from source contexts
Environment Projection SHALL own only composed snapshot read models, their versions, provenance, scope, expiry, and invalidation state. Organization, Identity, Expert, Connector, Wiki, and other source contexts MUST NOT call or import Environment Projection after changing source facts; they SHALL publish an integration event or invoke an independently owned event publisher port, and Environment Projection SHALL consume that notification to invalidate or refresh its read model.

#### Scenario: A source fact changes
- **WHEN** a source context commits an organization, identity, expert, connector, or knowledge change
- **THEN** it records the corresponding integration event without importing or invoking Environment Projection

#### Scenario: Projection receives a source-change event
- **WHEN** Environment Projection consumes a supported source-change event
- **THEN** it idempotently invalidates or refreshes the affected snapshot while preserving the source context as the sole owner of the source fact

#### Scenario: Snapshot is rebuilt
- **WHEN** a caller requests a snapshot whose projection is missing, stale, or invalidated
- **THEN** Environment Projection queries source contexts through published query contracts or adapters and returns a snapshot with scope, provenance, version, missing information, and expiry metadata

### Requirement: Boundary migration preserves observable behavior
Dependency-cycle removal and facade migration SHALL preserve supported public API contracts, database schema, durable workflow semantics, authorization behavior, and existing runtime outcomes unless a separate approved specification explicitly changes them.

#### Scenario: A dependency edge is replaced by a port or event
- **WHEN** an existing synchronous service call is migrated to a port, adapter, or integration event
- **THEN** characterization and regression tests observe the same supported response, state transition, and side-effect count as before the migration
