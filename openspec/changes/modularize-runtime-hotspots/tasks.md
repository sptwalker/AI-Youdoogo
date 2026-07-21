## 1. Recovery Safety

- [x] 1.1 Add explicit step claim outcomes and preserve the legacy claim_step compatibility API
- [x] 1.2 Add Outbox defer semantics and make busy step events wait until the active step lease expires
- [x] 1.3 Add periodic expired-step recovery scanning with deterministic deduplication and bounded batches
- [x] 1.4 Add end-to-end tests for crash-after-claim, busy replay, periodic recovery, and idempotent retry

## 2. Workflow Runtime Modules

- [x] 2.1 Extract workflow repository operations and append-only event persistence from workflow_service
- [x] 2.2 Extract workflow state transitions, lease operations, human acceptance, and output piping
- [x] 2.3 Extract workflow status aggregation, TaskCard mirrors, and progress projection
- [x] 2.4 Convert workflow_service into a compatibility facade and add import/API regression tests

## 3. Worker, Orchestration, and Skills

- [x] 3.1 Extract the workflow step executor and event handler from the Worker lifecycle loop
- [x] 3.2 Extract planning and legacy TaskCard orchestration from the durable orchestration facade
- [x] 3.3 Extract skill registry, legacy directive adapters, and ToolDispatcher while preserving app.agents.skills exports
- [x] 3.4 Add module-cycle and runtime-boundary tests, including the LangGraph planner-only boundary

## 4. Domain Service Hotspots

- [x] 4.1 Extract desktop chat streaming/orchestration emission from message persistence and participant resolution
- [x] 4.2 Extract Feishu OAuth configuration and transient state/exchange token stores from login orchestration
- [x] 4.3 Extract meeting AI speech, voting, minutes, and resolution actions from meeting CRUD
- [x] 4.4 Run focused desktop, Feishu, meeting, and API compatibility tests

## 5. Frontend Hotspots

- [x] 5.1 Extract Dashboard presentation sections and data hooks while preserving route behavior
- [x] 5.2 Extract OrgAdmin tree/editor components and validate TypeScript production build

## 6. Documentation and Verification

- [x] 6.1 Update architecture docs and README with the modular runtime and recovery flow
- [x] 6.2 Run Ruff, Mypy, Pytest, frontend build, and PostgreSQL migration-head verification
- [x] 6.3 Refresh Graphify outputs and verify no module cycles, orphan recovery gap, or oversized runtime facade remains
