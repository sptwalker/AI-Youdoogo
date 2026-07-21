## Context

上一轮 durable runtime 将 HTTP 同步 DAG 改为 PostgreSQL WorkflowRun/Step + Outbox Worker，但当前模块仍保留迁移期兼容代码。`workflow_service.py` 同时承担 repository、状态迁移、镜像和投影；`orchestration_service.py` 同时包含 planner、新入口与旧同步执行器；`workflow_worker.py::_execute_step` 将租约、外部调用、技能和状态提交集中在一个长函数中。

当前事件租约为 300 秒、步骤租约为 600 秒。Worker 在步骤抢占后崩溃时，Outbox 可能先被重放；重放看到步骤仍有有效租约便返回，随后事件被标记完成。步骤租约最终过期后没有独立触发器，可能永久停留在 `running`。此外，现有 `WorkflowEngine` 只包住 submit/progress/human accept，Worker 的推进决策仍直接依赖数据库实现，因此完整 LangGraph runtime 尚不能替换。

约束：不修改数据库表、不改变 API schema、不引入新队列；SQLite 测试和 PostgreSQL 生产路径均需保留；旧 TaskCard-only 编排在迁移窗口内继续可用；所有旧 import path 必须通过 facade 兼容。

## Goals / Non-Goals

**Goals:**

- 关闭 Outbox 与步骤租约之间的恢复缺口，保证崩溃后最终重新执行。
- 将高风险长函数和多职责模块拆成单向依赖的 repository/state/projection/executor/adapter。
- 保持现有 API、模型、数据库和测试调用路径兼容。
- 将旧同步编排明确隔离为 legacy adapter，避免新 durable 主链继续扩散双运行时依赖。
- 为 LangGraph planner/transition adapter 提供清晰接点，同时保留 PostgreSQL 可靠性边界。
- 对 P1/P2 业务服务和前端页面做行为保持型拆分，降低单文件维护成本。

**Non-Goals:**

- 本变更不接入 LangGraph，也不更换 PostgreSQL Outbox。
- 不删除旧 TaskCard-only 数据或 API。
- 不重写飞书 OAuth、会议业务或桌面对话交互语义。
- 不以任意行数阈值为唯一目标；拆分必须对应明确职责边界。

## Decisions

### 1. 步骤抢占返回显式结果而不是 `WorkflowStep | None`

新增 `StepClaimResult`，状态为 `claimed`、`busy` 或 `terminal`，并在 busy 时携带当前 `lease_until`。`workflow_service.claim_step()` 继续作为兼容函数返回旧类型，新 Worker 使用新的 `claim_step_result()`。

选择显式结果而不是通过二次查询猜测，是因为 `None` 无法区分“另一个 Worker 正在执行”和“步骤已经完成”，两者的 Outbox 处理语义相反。

### 2. Busy 事件延迟，不直接完成

步骤执行 handler 返回 `EventDisposition`：`complete` 或 `defer(until)`。`process_one()` 对 defer 调用 Outbox 的 `defer()`，清理处理租约并将 `available_at` 至少推迟到步骤租约结束；terminal 才完成事件。

这允许原 Worker 正常完成时，延迟事件随后识别终态并结束；原 Worker 崩溃时，延迟事件在步骤租约过期后获得新 attempt。

### 3. 周期恢复扫描作为第二道保险

新增 `workflow_recovery.requeue_expired_steps()`，查询租约过期的 running 步骤并写入确定性 `workflow.step.execute` 事件。dedupe key 包含 step id 与 version，保证同一过期版本只补发一次。Worker loop 按配置间隔执行扫描，扫描失败不阻断普通事件处理。

延迟事件是主恢复路径，周期扫描覆盖事件被人工结束、历史异常数据或数据库操作中断等情况。

### 4. 工作流模块采用 facade + 单向内部模块

- `workflow_repository.py`：创建、查询、列表、append-only event。
- `workflow_state.py`：ready、claim、renew、complete、output piping、human accept、failure propagation。
- `workflow_projection.py`：WorkflowRun 聚合、TaskCard 镜像和 progress DTO。
- `workflow_recovery.py`：过期租约扫描和补发。
- `workflow_service.py`：只做兼容 re-export，不放业务实现。

内部依赖方向为 repository → projection（无反向）；state 可调用 repository/projection；recovery 只依赖 repository/outbox。Facade 不被内部模块反向 import。

### 5. Worker 拆成 loop、event handler 与 step executor

- `workflow_worker.py`：应用生命周期和轮询 facade。
- `workflow_event_handler.py`：event type 路由和 disposition。
- `workflow_step_executor.py`：步骤执行、heartbeat、Agent/Tool 调用和结果落库。

Step executor 仍遵循“先提交租约、再外部调用、最后短事务完成”的边界。Worker loop 只解释 handler disposition，不理解 Agent 或技能细节。

### 6. 新 durable orchestration 与 legacy orchestration 分离

- `workflow_planning.py`：PlanStep、解析、规划、建步骤。
- `legacy_orchestration.py`：旧 `_run_step/advance/recover_incomplete` 和 TaskCard-only 投影。
- `orchestration_service.py`：新 start/resume/progress facade，并显式调用 legacy fallback。

现有 import path 保留，测试可以逐步迁移到新模块。LangGraph 首先实现 planner 端口；完整 transition adapter 必须等 Worker 也依赖该端口后再引入。

### 7. 技能运行时分离声明、旧协议和调度

- `skill_registry.py`：Skill descriptor、启用技能和提示词元数据。
- `legacy_skill_adapters.py`：中文文本指令到 SkillRequest。
- `tool_dispatcher.py`：注册、校验、ToolExecution 幂等和 executor 调用。
- `skills.py`：兼容导出与 `execute_all/fold_notes` 聚合。

Service executor 继续只依赖 `contracts.py`，不得反向 import Agent base。

### 8. P1/P2 使用局部提取，不改变领域 API

- 桌面对话：提取 SSE/编排事件渲染和流式发送协作者。
- 飞书登录：提取 OAuth 配置、state/exchange token store 与返回地址校验。
- 会议：提取 AI 发言/投票/纪要动作，CRUD/真人投票保留在原 service。
- 前端：Dashboard/OrgAdmin 提取展示组件与数据 hooks，页面继续作为路由容器。

## Risks / Trade-offs

- [兼容 facade 掩盖新的循环依赖] → 增加 AST 模块环测试，并禁止内部模块 import facade。
- [Outbox defer 造成重复轮询] → defer 时间钳制到 lease_until，dedupe 与 ToolExecution 保证重复安全。
- [周期扫描增加数据库负载] → 仅查询带索引的 running + lease_until 范围，限制每批数量并配置扫描间隔。
- [大规模移动导致回归] → 每完成一层拆分立即运行定向测试，旧 import path 在最终阶段前不删除。
- [前端拆分改变渲染时序] → 页面 API 调用与状态归属保持不变，仅提取纯组件/Hook，执行 TypeScript build。

## Migration Plan

1. 先增加恢复结果类型、Outbox defer、周期扫描和端到端测试。
2. 在 facade 后逐个移动 workflow、worker、orchestration、skills 实现，保持旧导出。
3. 拆分业务服务和前端页面，逐域运行测试与构建。
4. 更新文档、Graphify 和模块环检查，运行全量质量门禁。

回滚时可保留新模块并将 facade 指回旧实现；数据库 schema 无变化。恢复扫描可通过配置关闭，但 defer 语义应保留以避免重新引入 orphan step。

## Open Questions

- LangGraph 后续是仅承担 planner，还是承担 transition reducer；本变更默认先采用 planner-only POC。
- 应用内 Worker 拆为独立部署进程的时机仍留待后续容量评估。
