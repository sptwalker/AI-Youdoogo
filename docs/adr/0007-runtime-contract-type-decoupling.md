# ADR 0007：运行时契约剔除跨 Context 产品类型（Runtime Contract v2 类型解耦收尾）

- 状态：已采纳（Accepted）
- 日期：2026-07-28
- 相关：docs/21-通用AI平台拆分架构与落地方案 Phase 4 §7.4 / §13-B、[[ADR 0005]] 运行时事件 opaque
  （本 ADR 结清其「类型解耦待全量 v2」尾账）、[[ADR 0004]] 专家写侧端口、[[ADR 0003]] 专家目录只读端口

## 背景

绞杀顺序 LLM✓（[[ADR 0001]]）→ 知识读✓（[[ADR 0002]]）→ Expert 读✓（[[ADR 0003]]）→ Expert 写✓
（[[ADR 0004]]）→ Runtime 事件 opaque✓（[[ADR 0005]]）→ 知识写✓（[[ADR 0006]]）→ **Runtime 命令/DTO
类型解耦（本 ADR）**。

`workflow_runtime/contracts/runtime.py` 本应「框架/上下文无关」，却仍具名 import 两个跨 Context 产品类型：

- `work_planning` 的 `WorkflowPlan`——仅用于 `StartWorkflowCommand.plan`；
- `expert_management` 的 `ExpertExecutionSnapshot`——仅用于 `PreparedWorkflowStep.expert`。

两者对运行时都是**穿透值**：`WorkflowPlan` 是一次性中间体（只在 legacy facade
`app/services/workflow_repository.py` 由 `PlanStepLike` 现搭现拆，建它只为跑 `__post_init__` 的 DAG 校验，
随即被 `plan_to_json`/`_new_workflow` 拍平成 JSON）；`ExpertExecutionSnapshot` 全程只做「取→装进
`PreparedWorkflowStep.expert`→递交 `AgentExecutionRequest`」，唯一结构化解包在 infra legacy adapter
`_role_from_snapshot`（该文件自身已 import 该类型）。[[ADR 0005]] 明确将此类型解耦标记为「最后拆」。

## 决策 · 契约自持形状 + 消费端收窄

1. **`WorkflowPlan` → 运行时自有拍平命令**：契约新增 `WorkflowLaunchStep`（字段名对齐
   `WorkflowPlanStep`，故下游函数体零改），`StartWorkflowCommand` 由 `plan: WorkflowPlan` 改为拍平的
   `creator_id/request/steps/title/assignee_expert_id`。删除对 `work_planning` 的具名 import。
2. **`ExpertExecutionSnapshot` → 契约 `expert: object | None`**：与同文件既有 opaque 字段
   （`input_data`/`datasets`/`artifacts`）同风格。删除对 `expert_management` 的具名 import。
3. **facade 作翻译点，保留 DAG 校验**：`workflow_repository.py` **仍**建 `WorkflowPlan` 复用其
   `__post_init__` 唯一性/未知依赖/无环校验（信任边界校验不可省，遵 ponytail「NOT be lazy」），随即映射为
   拍平 `StartWorkflowCommand`。facade 属 legacy `app/services`，本就允许 import `work_planning`——DAG 校验
   复用、零重复 `_has_cycle`。
4. **消费端在跨 Context 边界再收窄**（各 1 处 `cast`，ACL 成本）：
   - application `step_execution.py` `ExecuteWorkflowStep.execute`：判空后
     `AgentExecutionRequest(expert=cast(ExpertExecutionSnapshot, prepared.expert))`；
   - infra `legacy_execution.py` `_LegacyCapabilityExecutionAdapter.execute`：判空后
     `_role_from_snapshot(cast(ExpertExecutionSnapshot, prepared.expert))`。

## 收编范围与延后

- **端口层不动**：`application/ports.py` `ExpertSnapshotPort.get_by_id -> ExpertExecutionSnapshot | None`
  保持具类型返回——它是运行时通向 expert_management 的**接缝端口**（与 `WorkflowAgentExecutionPort` 引
  agent_execution 契约同理），非契约文件。本轮守卫只治契约文件，端口层跨 Context 依赖本就正确、不在范围。
- **不改 DB、不动 outbox、不碰源 Context 契约**：`WorkflowPlan`/`WorkIntent`/`WorkflowPlanStep`/
  `ExpertExecutionSnapshot` 本轮零改，仅切断运行时契约对它们的具名依赖。`plan_to_json` JSON 形状、
  `WorkflowRun.plan` 列内容、事件 payload 字节不变（字段名对齐）。

## 后果

- 正向：运行时契约仅剩 stdlib import，foundations/execution 运行时契约不再具名任何别的 Context 产品类型；
  Runtime Contract v2 类型解耦（[[ADR 0005]] 尾账）结清。
- 债务：facade 多一层 `WorkflowPlan`→`StartWorkflowCommand` 映射（约 10 行）+ 消费端 2 处 `cast`——ACL 成本，
  换取契约稳定与守卫可执行。

## 守卫

`tests/test_planning_workflow_task_contracts.py`：
- `test_runtime_contract_imports_no_cross_context_types`：AST 解析 `runtime.py` 的 `ImportFrom`，断言无
  `app.contexts.*` 模块落在 `workflow_runtime`/`shared_kernel` 之外（改后集合应为空）——防
  `WorkflowPlan`/`ExpertExecutionSnapshot` 或任何未来跨 Context 产品类型回潮。
- `test_new_execution_contracts_do_not_import_framework_or_orm_modules`（既有）兜底 sqlalchemy/fastapi/ORM。

自证：`test_step_execution_orders_four_phases_and_closes_transactions` 经 `ExpertSnapshotPort` 返回真
`ExpertExecutionSnapshot`，装进 `object` 字段后 `prepared.expert is expert` 身份恒等仍成立，四阶段编排不回归。
