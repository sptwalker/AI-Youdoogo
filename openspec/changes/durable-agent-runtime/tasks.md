## 1. Persistence Foundation

- [x] 1.1 Add WorkflowRun, WorkflowStep, WorkflowEvent, OutboxEvent, and ToolExecution ORM models with indexes and status constants
- [x] 1.2 Add workflow/step/attempt/trace linkage fields to AgentTaskRecord and LlmCallLog
- [x] 1.3 Create Alembic migration 035 for durable workflow runtime tables and trace fields (034 is the existing branch merge)
- [x] 1.4 Add workflow schemas and model exports with SQLite-compatible JSON/date types

## 2. Transaction and State Correctness

- [x] 2.1 Refactor task_service create/decompose/transition to flush without committing and update callers to own commits
- [x] 2.2 Implement workflow repository with atomic run/step/TaskCard mirror creation and append-only events
- [x] 2.3 Implement versioned step claim, lease renewal/expiry recovery, and persisted parent workflow terminal states
- [x] 2.4 Add rollback, concurrent claim, parent finalization, and expired lease recovery tests

## 3. Transactional Outbox Worker

- [x] 3.1 Implement outbox enqueue, lease claim, complete, retry, and terminal failure operations
- [x] 3.2 Implement background workflow worker with run_once/run_forever and clean shutdown
- [x] 3.3 Replace synchronous orchestration advance/resume API paths with outbox submission and progress snapshots
- [x] 3.4 Start the worker from FastAPI lifespan without blocking readiness and add worker tests

## 4. Idempotent Executions and Traceability

- [x] 4.1 Implement ToolExecution idempotency service and execution context propagation
- [x] 4.2 Make file delivery reuse a deterministic Deliverable/object path for one idempotency key
- [x] 4.3 Make collaboration request execution deduplicate by idempotency key
- [x] 4.4 Link AgentTaskRecord and LlmCallLog to workflow/step/attempt/trace and expose them in progress data
- [x] 4.5 Add duplicate replay and end-to-end trace tests

## 5. Typed Skill Runtime

- [x] 5.1 Add typed SkillRequest, SkillResult, SkillExecutor, AgentRunner, and ExecutionContext contracts
- [x] 5.2 Implement ToolDispatcher and legacy directive adapters for collab, deliver, and data_query
- [x] 5.3 Refactor Agent runtime and skills to use dependency injection and remove base/skills/service import cycles
- [x] 5.4 Preserve red-line policy and add structured validation/legacy compatibility tests

## 6. Documentation and Verification

- [x] 6.1 Update docs/02, docs/14, docs/16, CLAUDE.md, and README for the durable runtime and future LangGraph adapter boundary
- [x] 6.2 Run Alembic upgrade checks and the full Ruff, Mypy, Pytest quality gates
- [x] 6.3 Refresh Graphify outputs and verify import cycles and workflow call paths
