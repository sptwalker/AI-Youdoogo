# 24-Workflow Runtime 拆分落地设计（docs/21 Phase 4）

> 上游权威：`docs/21-通用AI平台拆分架构与落地方案.html` §Phase 4「拆出 Workflow Runtime」。
> 前序设计：`docs/23-Expert平台拆分与事件传输门禁设计.md`（事件门禁 / 远端交接 / 工具环）。
> 相关 ADR：0005（运行时事件 opaque payload）、0007（运行时契约类型解耦）、0008（Expert 聚合逻辑拆分）。

本文遵循铁律「文档优先 + 单模块增量」：先据证据盘清 Phase 4 七步的**已交付 vs 真缺口**，
再只为真缺口设计**最小增量**。物理独立部署按 docs/21 §11「资源建议」主动推迟。

---

## §1 定位与结论（TL;DR）

Phase 4 是 docs/21「先简单，后最复杂：LLM → 知识 → 专家 → Workflow Runtime」四步的**最后一步**，
也是耦合最深、必须在前三平台稳定后才拆的一步。

**结论（据 §2 证据）：** Phase 4 官方七步中 **step 1–5 已在 Phase 0–3 随事件门禁与 Contract v2 落地并测试**
（opaque 契约 / Planning→Runtime ACL / Run·Step·Lease·Heartbeat·Retry·HumanWait·Outbox·Inbox /
Broker·Relay 五类演练 / step.ready→completed→任务投影）。真缺口仅剩两点：

- **step 6**「新增 workflow_type 路由开关；只让新创建的流程进入远程 Runtime」；
- **step 7**「旧流程在本地 drain 到终态，监控无活动实例后再下线旧 worker」。

docs/21 §14 决策已定调本轮形态：**「运行中 Workflow 不迁移——旧实例本地 drain，新实例创建时固定执行引擎，
避免双真源。」** 因此本轮交付 = **逻辑边界收口的最小增量**：

1. **engine 溯源戳**（`workflow_run.engine` 列）——**创建期固定**、不可变；
2. **配置化引擎选择**（`workflow_engine` 开关 + `get_workflow_engine(workflow_type)` fail-closed 分派）；
3. **drain 只读闸**（`count_active_runs_by_engine`）——回答 step 7「监控无活动实例」。

**默认零行为变化**：`workflow_engine="database"`，所有新老 run 仍盖戳 `database`、仍走现有自研 DAG runtime。
**物理独立部署 / 第二引擎 / router 真分派**按 docs/21 §11（团队 2–3 人：Runtime 保持模块化边界，后续按负载拆出）
**主动推迟**，升级路径见 §7。

---

## §2 Phase 4 七步现状盘点（证据表）

| # | docs/21 §Phase4 原文 | 状态 | 证据（代码 + 测试） |
|---|---|---|---|
| 1 | 发布 Runtime Contract v2，去掉 WorkflowPlan、ExpertExecutionSnapshot 和任务卡字段 | ✅ 已交付 | `contexts/foundations/execution/workflow_runtime/contracts/runtime.py`（`WorkflowLaunchStep`/`StartWorkflowCommand`/`WorkflowProgressedV1` 均 opaque，无 work_planning 具名类型、无快照、无任务卡字段）；ADR 0005/0007；`tests/test_planning_workflow_task_contracts.py::test_runtime_contract_imports_no_cross_context_types`、`::test_new_execution_contracts_do_not_import_framework_or_orm_modules` |
| 2 | 建立 Planning → Runtime v2 的 Anticorruption Layer，把 WorkflowPlan 翻译为通用 DAG + executor_ref + opaque input/output | ✅ 已交付 | 出站 ACL：`app/services/workflow_repository.py::create_workflow`（`PlanStepLike`→`WorkflowPlan` 复用 DAG/唯一性/未知依赖校验→拍平 `StartWorkflowCommand`/`WorkflowLaunchStep`）；见 §3.2 |
| 3 | 实现 Run / Step / Lease / Heartbeat / Retry / HumanWait / Outbox / Inbox | ✅ 已交付 | `app/models/workflow.py`（`WorkflowRun`/`WorkflowStep`：`lease_owner`/`lease_until`/`version`/`attempt`）+ `platform/outbox` + `platform/eventing/inbox`；`WorkflowStepExecutionApplication`（Claim/Prepare/Execute/Finalize + heartbeat keep_alive）；`tests/test_durable_workflow.py` |
| 4 | 先完成 Broker/Relay 的积压、重复、乱序、DLQ、重放演练；不过则 Runtime 保持本地 | ✅ 已交付 | `tests/test_event_transport_gate.py`（exactly-once / 幂等 / 401·403·202 / 5xx→DLQ→replay 四例）；Go/No-Go 实跑 6 项 DoD（docs/23 §5，临时库 `youdoo_gate_live`） |
| 5 | Runtime 发 step.ready；Expert 发 completed/failed；业务系统消费进度构建任务投影 | ✅ 已交付 | 出站：`platform/eventing/relay.py::StepReadyRelay`；入站投影 ACL：`contexts/business/task_management/infrastructure/workflow_projection.py::SQLAlchemyWorkflowTaskProjection`；`tests/test_remote_step_execution.py`（停车/唤醒/双层幂等/red_line→WAITING_HUMAN/过期降级/http inbox 投影） |
| 6 | 新增 workflow_type 路由开关；只让新创建的流程进入远程 Runtime | ⛳ **本轮缺口** | 见 §4.3–§4.5：`config.workflow_engine` + `get_workflow_engine(workflow_type)` + 创建期盖戳 |
| 7 | 旧流程在本地 drain 到终态，监控无活动实例后再下线旧 worker | ⛳ **本轮缺口** | 见 §4.6：`count_active_runs_by_engine`（按 engine 统计非终态 run） |

**引擎缝已就位（step 6 的落点）：** `app/agents/workflow_engine.py` 已有 `WorkflowEngine` Protocol +
`DatabaseWorkflowEngine` + `get_workflow_engine()` 单例；docstring 已锁「LangGraph 后续只能实现此端口……
可靠状态、Outbox、真人停点仍由持久化 runtime 负责，不能由图框架旁路」。本轮只把单例升级为**配置化 fail-closed 分派**，
不改任何执行语义。

---

## §3 Runtime Contract v2 与出/入站 ACL（step 1+2+5，已交付验证）

### §3.1 opaque 契约（step 1）

`WorkflowLaunchStep` 为运行时自持的**不透明**步骤规格（`number`/`title`/`capability_key`/`instruction`/`depends_on`），
**不引用** work_planning 具名类型（ADR 0007 切断具名依赖）。`WorkflowProgressedV1` 产品字段全部退化为
**不透明路由键 `business_key` + 不透明负载 `payload: Mapping[str, object]`**（ADR 0005），值一律 JSON 安全（uuid→str）
保证 outbox 往返无损；产品语义由消费方 Context 的 ACL 解码。契约层无框架 / 无 ORM import（测试守卫见 §3.5）。

### §3.2 出站 ACL（step 2，Planning → Runtime v2）

`app/services/workflow_repository.py::create_workflow` 是**出站防腐层**：
`PlanStepLike`（鸭子协议 `no/title/skill/instruction/depends_on`）→ 仍构造 `WorkflowPlan`
**复用其 `__post_init__` 的唯一性 / 未知依赖 / 无环校验**（信任边界校验不可省）→ 随即翻译为运行时自持的
拍平 `StartWorkflowCommand` + `WorkflowLaunchStep` 元组。`WorkflowPlan` 是**过程内瞬态**、翻译完即弃，
不进契约、不进持久化——契约不再具名 work_planning 类型。

### §3.3 入站 ACL / 投影（step 5）

`contexts/business/task_management/infrastructure/workflow_projection.py::SQLAlchemyWorkflowTaskProjection`
是**入站防腐层**：消费 `WorkflowProgressedV1`，从不透明 `business_key`/`payload` 解码出任务卡字段并刷新任务投影。
产品概念只在此还原，Runtime 全程不理解任务卡 / 提案 / 专家（符合 docs/21「Runtime 只理解通用流程状态」）。

### §3.4 抽象 v2 字段 ↔ 现有实现映射

docs/21 step 2 用抽象词「通用 DAG + executor_ref + opaque input/output」描述 v2；落地对应：

| docs/21 抽象词 | 落地字段 / 机制 | 说明 |
|---|---|---|
| 通用 DAG | `WorkflowLaunchStep.number` + `.depends_on: tuple[int,...]` | 整数编号 + 依赖边，`WorkflowPlan.__post_init__` 校验无环 |
| executor_ref | `WorkflowLaunchStep.capability_key` | 步骤执行体选择键（skill/capability） |
| opaque input | `WorkflowLaunchStep.instruction` | 步骤指令（对 Runtime 不透明） |
| opaque output | `WorkflowProgressedV1.payload`（`business_key` 路由） | 进度事件不透明负载，ACL 解码 |

**诚实说明（未提升为契约字面字段者）：** docs/21 §7 曾列 `retry_policy`/`timeout`/`wait_mode` 等；本落地
**未**把它们做成契约字面字段，而是由 **runtime 机制承载**——重试=outbox 退避、超时=停车租约 `lease_until`、
真人等待=`red_line`→`WAITING_HUMAN`。`definition_key`/`version`（版本化流程注册表）当前**不存在**：
计划由 LLM 即席产出、无版本化定义注册表 → 提升为契约字段属投机，YAGNI 推迟（升级路径见 §7）。

### §3.5 测试证据

`tests/test_planning_workflow_task_contracts.py` 已覆盖：`test_runtime_event_names_no_product_fields`（ADR 0005）、
`test_runtime_contract_imports_no_cross_context_types`（ADR 0007）、
`test_new_execution_contracts_do_not_import_framework_or_orm_modules`、
`test_work_intent_and_plan_are_immutable_and_validate_dag`、
`test_step_execution_orders_four_phases_and_closes_transactions`。→ step 1/2 **无需新代码，仅本文档验证**。

---

## §4 本轮新增：engine 溯源戳 + 创建期固定 + drain 只读闸（step 6+7）

### §4.1 设计动机

docs/21 §14 决策：**「新实例创建时固定执行引擎，避免双真源。」** 关键约束——

- 引擎标识必须在**创建时刻**写入并**不可变**：一旦系统存在第二个引擎，就**无法回溯**判定某条历史 run 当年在哪个引擎跑；
  故 `engine` 列必须**先于**任何可能选中异构引擎的开关存在（保险性质，correct-on-edge-cases，非脚手架）。
- 只有 run 带 engine 戳，step 7「监控无活动实例」才能按引擎统计非终态 run、确认旧引擎排空后再下线。
- 戳的**读侧**（drain 闸）同时是本轮闭环测试的断言手段（创建→盖戳→按 engine 计数），故一并交付；
  但**运维界面 / 端点**推迟到真正发生跨引擎 drain 时再建（当前只有一个引擎，无处可 drain）。

### §4.2 数据变更（migration 040）

`WorkflowRun` 加列（加法式、可空转非空带 server_default，不改现有行语义）：

```python
engine: Mapped[str] = mapped_column(String(32), default="database", server_default="database")
```

迁移 `alembic/versions/040_workflow_run_engine.py`（`down_revision="039_expert_release_eval"`，单 head）：
`op.add_column("workflow_run", sa.Column("engine", sa.String(32), nullable=False, server_default="database"))`。
**不加索引**——drain 是罕见运维查询，非热路径（ponytail：量级增长或 drain 频繁再加 `(engine, status)` 复合索引）。

### §4.3 配置开关

`app/core/config.py` 加：

```python
workflow_engine: str = "database"  # 新建 run 固定的执行引擎；database=自研 DAG runtime（默认）。
# 未来接入远程 Runtime/LangGraph 时改此默认或按 workflow_type 传参；创建期盖 workflow_run.engine 戳。
```

### §4.4 创建期固定（不可变盖戳）

`workflow_runtime/infrastructure/sqlalchemy_repository.py::_new_workflow` 构造 `WorkflowRun` 时读配置盖戳：

```python
run = WorkflowRun(..., version=0, engine=get_settings().workflow_engine)
```

盖戳后**不提供任何改写路径**（无 setter、无 update 语句触碰 engine 列）→ 创建期固定、天然不可变。

### §4.5 引擎选择（fail-closed 分派）

`app/agents/workflow_engine.py` 把单例升级为配置化分派：

```python
_ENGINES: dict[str, WorkflowEngine] = {"database": _database_engine}

def get_workflow_engine(workflow_type: str | None = None) -> WorkflowEngine:
    """按 workflow_type（缺省读 config.workflow_engine）选引擎；未知即拒（fail-closed）。"""
    name = workflow_type or get_settings().workflow_engine
    try:
        return _ENGINES[name]
    except KeyError:
        raise ValueError(f"未知 workflow engine: {name!r}") from None
    # ponytail: 注册表当前仅 database 一项；接第二引擎时在此登记 + router 真按 workflow_type 分派。
```

**fail-closed 安全**：未知引擎名**拒绝**而非静默回落默认——防配置漂移把流程投进不存在的引擎。
既有 4 处调用（`orchestration_service.start/resume_if_step/progress`）无参调用，行为逐字不变。

### §4.6 drain 只读闸（step 7）

`sqlalchemy_repository.py` 加只读查询（与 `get_run`/`list_steps` 同处，runtime 自持读）：

```python
async def count_active_runs_by_engine(session: AsyncSession) -> dict[str, int]:
    """按 engine 统计非终态（queued/running/waiting_human）run 数——step 7「监控无活动实例」。
    返回空 dict 即所有引擎已排空，可安全下线对应 worker。"""
```

非终态 = `RUN_QUEUED`/`RUN_RUNNING`/`RUN_WAITING_HUMAN`（终态 succeeded/failed/cancelled 不计）。
**只读、不改状态**——drain 由「停止新建路由到旧引擎（§4.5）+ 旧 run 自然跑到终态」达成，本函数只做可观测。
运维端点 / 面板推迟（ponytail：无第二引擎即无处 drain；真 drain 时再包 `/internal/ops/*` 只读端点）。

### §4.7 不透明性守恒

`engine` 是**基础设施元数据**，只存于 `workflow_run` 行，**不进** `WorkflowProgressedV1.payload`、
不进任何跨 Context 契约——消费方 ACL / 任务投影对引擎无感知（Runtime 仍只理解通用流程状态）。

### §4.8 默认零行为变化

`workflow_engine="database"`（默认）→ 每条新 run 盖戳 `database` → `get_workflow_engine()` 仍返回同一
`_database_engine` → 执行链逐字不变；`count_active_runs_by_engine` 恒返回 `{"database": N}`。
现网无感知，纯增可观测 + 未来切换的挂载点。

---

## §5 默认关 / 回滚矩阵

| 维度 | 默认（本轮上线态） | 切换 / 回滚 |
|---|---|---|
| 引擎选择 | `workflow_engine="database"` → 全部走自研 DAG runtime | 改配置或传 `workflow_type` 选异构引擎；回滚=改回 `"database"`（新建即回旧引擎，已在异构引擎的 run 继续在原引擎跑完，**不跨引擎迁回**，符合 docs/21 回滚条款） |
| engine 列 | 全部行 `engine="database"`（server_default 回填存量） | 迁移可 `downgrade` drop 列（加法式，无数据损失风险） |
| drain 闸 | 只读、无副作用 | 无需回滚（不改状态） |
| 分派安全 | 未知引擎名 → `ValueError` 拒绝 | fail-closed，配置错不会静默投错引擎 |

**关键回滚语义（docs/21 §Phase4 回滚原文）：** 「停止把"新流程"路由到远程；已进入远程的流程继续在远程完成，
不跨引擎迁回；必要时暂停新建并修复。」→ engine 创建期固定 + 不可变正是此语义的数据保证（无双真源）。

---

## §6 Phase 4 验收（DoD）映射

docs/21 §Phase4 验收原文：「杀 worker、重复投递、网络分区、回执乱序和人工等待恢复演练通过；无永久卡死运行；
业务投影可从事件重建。」逐项映射到**已有**演练 / 测试：

| DoD 项 | 机制 | 证据 |
|---|---|---|
| 杀 worker 恢复 | 租约过期即重选 / 降级 | `tests/test_remote_step_execution.py::test_expired_lease_degrades_to_local`；`test_durable_workflow.py` 租约抢占 |
| 重复投递幂等 | Inbox `event_id` 唯一去重 | `tests/test_event_transport_gate.py`（同 event_id 二投仍 1 行、均 202） |
| 网络分区 / DLQ | 非 2xx→outbox 退避→DLQ→replay | `tests/test_event_transport_gate.py`（5xx→FAILED→replay→done） |
| 回执乱序 | `version` fence 挡旧版回执 | `tests/test_remote_step_execution.py::test_apply_completed_idempotent`（旧 version 二投 `second=False`） |
| 人工等待恢复 | red_line→`WAITING_HUMAN`，唤醒不自动推进 | `tests/test_remote_step_execution.py::test_red_line_step_waits_human_no_advance` |
| 无永久卡死 | 过期停车租约被重选降级本地 | 同「杀 worker」项 |
| 投影可从事件重建 | 入站 ACL 幂等重放 | `SQLAlchemyWorkflowTaskProjection` + `test_completed_via_http_inbox_projects` |

→ step 4/5 验收**无需新代码**；本轮新增测试只覆盖 §4 的 engine 戳 + 分派 + drain 闭环（见 §8 验证）。

---

## §7 诚实边界与升级路径

| 主动推迟项 | 为何推迟 | 升级路径 |
|---|---|---|
| 物理独立部署 Runtime 服务 | docs/21 §11：团队 2–3 人，Runtime 保持模块化边界，按负载后拆；容量 / 服务身份门禁未过前只做逻辑边界 | 容量 + Internal JWT 门禁过 → 把 `workflow_runtime` Context 打成独立 Deployment，engine=`"remote"` 走事件交接（step.ready 机制已在） |
| 第二引擎（LangGraph / 远程 Runtime）真实现 | 无消费者；`WorkflowEngine` Protocol + engine 戳已预留挂载点 | 实现 `WorkflowEngine` 端口 → 注册进 `_ENGINES` → router 按 `workflow_type` 真分派；可靠状态 / Outbox / 真人停点仍由持久化 runtime 负责，不得旁路 |
| router 按 workflow_type 返回不同引擎 | 当前注册表仅一项，分派恒返 database（真分派属脚手架） | 同上，随第二引擎一起启用 |
| 契约字面字段 `definition_key`/`version`/`retry_policy` | 无版本化流程注册表、无第二消费者，提升为字段属投机 | 出现版本化定义注册表或跨引擎重放需求时按需加字段（契约演进走 ADR） |
| drain 运维端点 / 面板 | 仅一个引擎，无处 drain | 真跨引擎 drain 时包只读 `/internal/ops/*` 端点消费 `count_active_runs_by_engine` |

**边界总述：** 本轮是**逻辑边界收口**——把「新建 run 固定引擎、可按引擎观测排空」这条 docs/21 §14 决策
落到数据与代码，为未来物理拆分 / 异构引擎**留好不可回填的溯源戳与 fail-closed 挂载点**，但不预建任何空壳服务。

---

## §8 不碰 / 验证

**不碰：** 执行链任何语义（Claim/Prepare/Execute/Finalize、租约、outbox、事件门禁、真人停点逐字不变）；
契约 dataclass（engine 是 infra 元数据，不进契约）；4 处 `get_workflow_engine()` 调用点（保持无参、行为不变）；
前端；`app/api/v1/*`。

**验证（提交前全量门禁）：** `uv run ruff check . ; uv run mypy app ; uv run pytest -q -m "not delivery_contract"`。
新增闭环测试断言：①创建 run → `engine=="database"`（读配置盖戳）②`count_active_runs_by_engine` 计入该非终态 run、
终态后不计 ③`get_workflow_engine("database")` 返 `_database_engine`、未知名 → `ValueError`（fail-closed）
④pin 不变式：创建后 engine 无改写路径。默认关下既有全量测试零回归。
