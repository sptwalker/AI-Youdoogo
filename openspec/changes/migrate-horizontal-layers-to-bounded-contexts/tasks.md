## 1. P0 Baseline and Architecture Guardrails

- [x] 1.1 Add a repository-wide Python import graph analyzer and characterization tests for the three current strongly connected components
- [x] 1.2 Remove eager implementation re-exports from `app.agents` and migrate runtime callers to leaf modules
- [x] 1.3 Remove eager implementation re-exports from `app.knowledge` and migrate runtime callers to leaf modules
- [x] 1.4 Add versioned source-change event contracts and an Environment Projection invalidation seam
- [x] 1.5 Replace Organization, Identity, Expert, Connector, and bootstrap Environment refresh callbacks with one-way event publication and projection handling
- [x] 1.6 Enforce zero application import cycles, inward Context dependencies, one-way facades, and side-effect-free package initialization in architecture tests

## 2. P1 Proposal Management Reference Slice

- [x] 2.1 Add characterization tests for Proposal create, research, human review, conversion, permissions, errors, and transaction visibility
- [x] 2.2 Implement framework-independent Proposal domain state and transition rules
- [x] 2.3 Implement Proposal application commands/results, repository/UoW ports, and Expert/Task/Policy ports with fake-based unit tests
- [x] 2.4 Implement SQLAlchemy Proposal repository/UoW and external adapters while preserving the existing tables and API behavior
- [x] 2.5 Convert the legacy Proposal service and HTTP route to one-way Context delegation and migrate internal callers

## 3. P2 Expert, Agent, and Capability Boundaries

- [x] 3.1 Define pure Expert execution snapshot contracts and an Expert Management query port
- [x] 3.2 Define pure Agent execution request/result/trace contracts without Session, ORM, callable, or vendor types
- [x] 3.3 Adapt the existing Agent runtime behind the new Agent Execution port and preserve usage, sources, reflection, and streaming behavior
- [x] 3.4 Separate Capability Catalog definitions from Capability Execution request/result and authorization/idempotency contracts
- [x] 3.5 Adapt skill registry, legacy directives, ToolDispatcher, and ToolExecution behind the new Capability ports
- [x] 3.6 Migrate Agent and Capability internal callers away from legacy package-root imports and concrete runtime dependencies

## 4. P2 Planning, Workflow Runtime, and Task Management

- [x] 4.1 Define pure WorkIntent, WorkflowPlan, Workflow command/result/event, Task command/result/event, and Unit of Work contracts
- [x] 4.2 Move planning policy behind a Work Planning use case that cannot mutate Workflow or Task persistence
- [x] 4.3 Split workflow step execution into Claim, Prepare, Execute, and Finalize collaborators using clean Agent/Capability ports
- [x] 4.4 Move Workflow repository/state/projection/recovery behavior behind Context-owned ports and SQLAlchemy adapters
- [x] 4.5 Replace direct Workflow-to-Task writes with idempotent WorkflowProgressed and TaskDecision event adapters
- [x] 4.6 Convert workflow, orchestration, task, worker, and skill legacy modules into one-way compatibility facades
- [x] 4.7 Preserve lease, attempt, busy defer, crash recovery, ToolExecution idempotency, and human-stop behavior with focused tests

## 5. P3 Identity, Organization, Knowledge, and Environment Contexts

- [x] 5.1 Migrate Identity use cases and Principal contracts behind Context-owned repository/UoW ports
- [x] 5.2 Migrate Organization Structure and Expert roster queries behind published snapshot contracts
- [x] 5.3 Migrate Access Control decisions behind a pure PolicyDecision port without cross-context ORM access
- [x] 5.4 Split Wiki Management, Knowledge Indexing, Knowledge Retrieval, Semantic Catalog, and Organizational Memory ownership
- [x] 5.5 Replace package-root Knowledge calls with published query/command ports and versioned document/index events
- [x] 5.6 Complete Environment Projection ContextSnapshot contracts with scope, provenance, versions, missing data, stale state, and expiry

## 6. P3 Communication, Meeting, Analytics, and Governance Contexts

- [x] 6.1 Migrate Assistant Conversations persistence/streaming behind Context use cases and ports
- [x] 6.2 Migrate Group Messaging membership, messages, realtime delivery, attachments, and archive behavior behind Context use cases
- [x] 6.3 Migrate Collaboration Requests behind owned domain/application contracts
- [x] 6.4 Migrate Meeting Management CRUD, AI actions, votes, minutes, resolutions, and task conversion behind Context ports
- [x] 6.5 Migrate Operational Analytics, Connector usage, and governed data-query collaboration behind published contracts
- [x] 6.6 Isolate Audit, Human Review, AI Quality, Usage/Budget, and System Configuration as decision/evidence ports that do not mutate source aggregates

## 7. P4 HTTP Entrypoints and Frontend Features

- [x] 7.1 Move migrated HTTP routes to Context entrypoints that invoke one Application use case and preserve the existing envelope
- [x] 7.2 Remove direct ORM, repository, concrete Agent/LLM, and legacy Service imports from HTTP route modules
- [x] 7.3 Add Group Chat characterization tests for SSE, polling fallback, deduplication, read state, attachments, membership, and cleanup
- [x] 7.4 Split Group Chat into feature-owned API adapters, session/member hooks, message list, composer, and member picker components
- [x] 7.5 Convert remaining large route pages to feature containers where state/effect ownership is currently mixed
- [x] 7.6 Remove zero-caller legacy facades, package re-exports, and temporary architecture exemptions

## 8. Documentation and Verification

- [x] 8.1 Update CLAUDE.md and docs/20 implementation status, ownership map, facade inventory, and migration guidance
- [x] 8.2 Run Ruff, Mypy, full non-delivery Pytest, frontend test/lint/build, migration-head validation, and application/worker smoke checks
- [x] 8.3 Refresh Graphify outputs and verify zero import cycles, no Context-to-legacy reverse dependencies, and no duplicate writers
