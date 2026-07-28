# ADR 0005：运行时进度事件产品字段 opaque 化（Runtime Contract v2 第一刀）

- 状态：已采纳（Accepted）
- 日期：2026-07-27
- 相关：docs/21-通用AI平台拆分架构与落地方案 Phase 4 §7.4 / §13-B、[[ADR 0004]] 专家写侧端口、
  [[ADR 0003]] 专家目录只读端口、[[ADR 0001]] LLM 完成统一端口

## 背景

绞杀顺序 LLM✓（[[ADR 0001]]）→ 知识✓（[[ADR 0002]]）→ Expert 读✓（[[ADR 0003]]）→ Expert 写✓
（[[ADR 0004]]）→ **Runtime 事件（本 ADR）**。

`workflow_runtime/contracts/runtime.py` 的运行时事件 `WorkflowProgressedV1`（docs/21 §7.4，耦合表）
在**字段名上直接命名产品概念**：`parent_task_id`/`creator_id`/`title`/`request_text`/`task_card_id`/
`step_title`/`capability_key`/`instruction`/`red_line`/`expert_id`/`depends_on_task_ids`/
`result_content`（共 12 个）。foundations/execution 的运行时契约本应与业务产品无关，这些字段让它反向
知道了 business/task_management 的产品模型。docs/21 §13-B「起草 Runtime Contract v2，去除产品字段」正指此处。

## 决策 · 事件产品字段 opaque 化

1. `WorkflowProgressedV1` 只保留运行时通用字段（`event_id`/`workflow_id`/`run_version`/`occurred_at`/
   `transition`/`run_status`/`step_status`/`step_id`/`step_version`/`step_number`/`error`），新增不透明
   路由键 `business_key: str` 与不透明产品负载 `payload: Mapping[str, object]`；删除上述 12 个具名产品字段。
   `payload` 值一律 JSON 安全（uuid→str），保证 outbox 往返无损。
2. 生产侧（`progress_events.py`、`sqlalchemy_repository.py` 的 created 事件、`sqlalchemy_projection.py` 的
   run 完成事件）从 ORM 组装 `payload` dict + `business_key`；outbox 序列化（`events.py`）通用字段按名落库、
   `payload` 键平铺，反序列化时非通用键归拢回 `payload`。行为字节级等价，只是落点从具名字段改为 payload 键。
3. 产品字段名的**唯一归属地**下沉到消费方 Context：`task_management/infrastructure/workflow_event_acl.py`
   的 `decode_workflow_progress(event) -> WorkflowProjectionData` 把 `payload` 解回产品字段，投影
   `SQLAlchemyWorkflowTaskProjection` 只读解码结果。ACL 属 infrastructure（可 import uuid/ORM），不进 contracts。

## 收编范围与延后

- **只做事件产品字段 opaque 化，不做全量 v2**：不引入 `StartWorkflowV2` 命令形，不解耦运行时契约顶部两处
  跨 Context 类型 import（`WorkflowPlan`、`ExpertExecutionSnapshot`）——docs 标「最后拆」，属后续更深增量。
  **（已由 [[ADR 0007]] 收编：两处 import 已剔除，`StartWorkflowCommand` 拍平自持、`expert` 契约 opaque。）**
- 本 ADR 完成后 docs/21 §13-B「运行时事件产品字段已 opaque 化」闭合；类型解耦（全量 v2）仍待后续。
  **（类型解耦已由 [[ADR 0007]] 结清。）**

## 后果

- 正向：运行时事件契约不再具名任何产品概念，foundations→business 的反向语义耦合消除；产品字段增删只动
  消费方 ACL，运行时契约稳定。新增在事件上具名产品字段被守卫阻断。
- 债务：4 处生产侧各自组装 payload（源为不同 ORM/规格对象，形状不一），约 5 行/处重复——接缝成本，
  类型解耦时若统一进 v2 命令再归并。

## 守卫

`tests/test_planning_workflow_task_contracts.py`：
- `test_runtime_event_names_no_product_fields`：断言 `WorkflowProgressedV1` 的 `dataclasses.fields` 名集合
  与 12 个产品 token 交集为空，且含 `business_key`/`payload`。

自证：`tests/test_workflow_runtime_event_acl.py` 证生产者 payload → `decode_workflow_progress` 字段还原一致，
且 outbox `to_payload → from_payload` 往返保 `payload`/`business_key`/通用字段不失真，无需真实 DB。
