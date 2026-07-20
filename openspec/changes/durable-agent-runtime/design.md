## Context

当前编排由 `orchestration_service.start/advance` 在请求会话中同步完成。`TaskCard` 同时表达普通任务、编排父卡和步骤卡；`task_service` 内部自行提交事务；恢复逻辑把执行中步骤复位后直接重跑。技能层通过文本指令和局部 import 串接 `run_agent`，Graphify 已识别多组 `base → skills → service → base` 导入环。

系统约束：继续使用 Python 3.12、FastAPI、SQLAlchemy async、PostgreSQL；保持真人验收红线；不引入 Celery、Temporal 或 LangGraph 作为本次前置依赖；SQLite 单测仍需可运行。后续接 LangGraph 时，LangGraph 只能替换规划/推进适配器，不能绕过数据库状态、幂等和人工停点。

## Goals / Non-Goals

**Goals:**

- 编排创建原子化，执行与 HTTP/SSE 请求解耦。
- 多 worker 下同一步骤同一时刻最多一个有效执行租约。
- LLM 与有副作用技能可安全重试，重复事件复用既有结果。
- 工作流拥有独立、真实的生命周期，TaskCard 仅作为人机界面镜像。
- 所有执行具备 workflow/step/attempt/trace 关联。
- 技能通过强类型接口和依赖注入执行，消除循环依赖。
- 为未来 LangGraph 提供 `WorkflowEngine`/`Planner` 适配边界。

**Non-Goals:**

- 本次不接入 LangGraph、Temporal、Celery 或外部消息队列。
- 不实现任意规模的动态工作流、定时器、补偿事务或跨服务 saga。
- 不删除现有 TaskCard API，也不改变真人验收的权限规则。
- 不在本次强制所有模型使用原生 tool calling；保留文本指令兼容层。

## Decisions

### 1. PostgreSQL 是工作流状态和队列的唯一事实源

新增 `workflow_run`、`workflow_step`、`workflow_event`、`outbox_event`、`tool_execution`。Outbox 与业务状态在同一事务写入，worker 通过条件更新抢占事件和步骤。

选择 PostgreSQL 而非 Redis 队列，是因为工作流状态、人工停点和副作用去重需要强一致；当前吞吐规模无需新增消息基础设施。Redis 继续承担预算和熔断，不作为 durable execution 真相源。

### 2. TaskCard 作为兼容镜像，不再作为工作流执行真相源

每个 `WorkflowRun` 可关联一张父 TaskCard，每个 `WorkflowStep` 可关联一张步骤 TaskCard。用户界面和既有验收 API 继续使用 TaskCard；worker 状态以 WorkflowRun/Step 为准，并同步镜像状态。

这样可渐进迁移，不要求一次性重写全部任务卡功能。未来可直接让 LangGraph checkpoint 映射到 WorkflowRun/Step，而不污染普通任务状态机。

### 3. 编排分为短事务阶段和外部执行阶段

阶段 A：规划完成后，在一个事务中创建 workflow、TaskCard 镜像、全部步骤、依赖和首个 outbox 事件。

阶段 B：worker 抢占 outbox 和步骤，短事务写入租约后立即提交；随后执行 LLM/MinIO/外部请求；完成后再用短事务落结果、事件和下游 outbox。

任何 repository/service 默认只 `flush`；提交由 use case 或 worker handler 管理。现有非编排调用点显式提交，避免隐式事务边界。

### 4. 租约 + 条件更新保证并发安全

`WorkflowStep` 包含 `version`、`attempt`、`lease_owner`、`lease_until`。抢占条件必须满足状态可运行且租约为空或已过期；更新使用 `WHERE id=:id AND version=:expected`，成功行数为 1 才获得执行权。

OutboxEvent 使用相同的 pending/processing/done/failed 状态与租约字段。PostgreSQL 可使用 `FOR UPDATE SKIP LOCKED`，实现保留条件更新后备路径以兼容 SQLite 单测。

### 5. 副作用以 ToolExecution 实现幂等

幂等键格式为 `workflow_id:step_id:attempt-scope:tool_key:action_index`。`tool_execution.idempotency_key` 唯一；执行前先插入/抢占，已成功则直接返回存储结果。

文件交付使用确定性对象路径和 ToolExecution 结果。数据库先保留 `pending` Deliverable，再上传确定性路径，最后原子标记成功；重试更新同一行而不是创建新文件。协作请求同样保存幂等键并复用既有请求。

### 6. 事件驱动推进替换递归 `advance`

worker 每次只处理一个明确事件：`workflow.advance`、`workflow.resume` 或 `workflow.recover`。步骤完成后计算新 ready steps 并写 outbox；真人 accept 只更新镜像/工作流步骤并写 resume 事件，不在请求中继续执行 LLM。

父流程状态由步骤聚合后持久化为 queued/running/waiting_human/succeeded/failed/cancelled。已成功流程不会被恢复扫描再次选中。

### 7. AgentRuntime 与技能执行采用端口/适配器

新增 `ExecutionContext`、`SkillRequest`、`SkillResult`、`SkillExecutor` 和 `ToolDispatcher`。AgentRuntime 只依赖 `ToolDispatcher` 接口；咨询技能通过注入的 `AgentRunner` 端口调用其他 Agent，不反向 import `agents.base`。

结构化动作优先采用 Pydantic schema；现有 `【取数】`、`【咨询】`、`【交付】` 文本解析器作为 `LegacyDirectiveAdapter` 生成同一 `SkillRequest`，保证兼容现有提示词和模型。

### 8. LangGraph 只作为未来 WorkflowEngine adapter

定义 `WorkflowEngine` 协议：提交计划、计算 ready steps、处理步骤完成/人工事件。首版 `DatabaseWorkflowEngine` 复用当前 DAG 逻辑。未来 `LangGraphWorkflowEngine` 可使用同一 WorkflowRun/Step、Outbox、ToolExecution 和人工验收事件，避免把可靠性职责交给图框架隐式处理。

## Risks / Trade-offs

- [双模型镜像导致状态漂移] → 所有镜像同步集中在 workflow repository，并增加一致性测试；WorkflowStep 始终为执行真相源。
- [应用内 worker 与 Web 进程同生命周期] → 租约和 outbox 保证多进程安全；部署后可用同一入口拆成独立 worker 进程。
- [外部调用无法实现严格 exactly-once] → 通过确定性幂等键实现 effectively-once，所有外部适配器必须可查询或复用结果。
- [迁移期间旧任务仍在 TaskCard] → 仅新编排创建 WorkflowRun；旧普通任务继续原状态机，避免批量回填风险。
- [文本指令仍可能歧义] → 统一先转强类型请求并校验；逐步提升原生 tool calling 覆盖率。
- [后台执行改变对话即时反馈] → SSE 立即返回 queued/running 进度卡，前端继续轮询现有 orchestration progress 接口。

## Migration Plan

1. 新增表和可空追踪字段，不修改旧数据语义。
2. 重构 task_service 事务边界，并让既有调用点显式提交。
3. 新增 workflow repository、原子创建 use case 和 TaskCard 镜像。
4. 新增 outbox worker 与手动 `run_once` 测试入口，再接入 lifespan。
5. 将桌面对话编排和人工 resume 切换到 outbox；保留旧同步函数作为短期内部兼容，不再由 API 调用。
6. 接入 ToolExecution 幂等，优先覆盖 deliver/collab，再覆盖 LLM attempt 关联。
7. 引入 typed skill dispatcher 和 legacy adapter，删除循环 import。
8. 完成全量测试、迁移升级与 Graphify 更新。

回滚时可停止 worker 并把入口切回旧同步路径；新增表和可空字段保留，不影响旧 TaskCard 数据。由于新旧流程不共享执行真相，同一 workflow 不得同时由两套执行器推进。

## Open Questions

- LangGraph 接入时采用 PostgreSQL checkpointer 还是仅把 LangGraph 作为纯推进器，待本次内核稳定后用 POC 决定。
- 独立 worker 进程的最终部署形态暂不在本次变更内；应用内 worker 先提供功能与验证基础。
