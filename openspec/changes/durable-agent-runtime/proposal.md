## Why

当前任务编排在 HTTP/SSE 请求内同步执行，状态迁移由多个 service 自行提交事务，且恢复逻辑会直接重跑未完成步骤。多 worker、重复请求或进程崩溃时，可能重复调用 LLM、重复交付文件、留下半套编排数据，现有导入环也让技能扩展持续放大耦合。

现在需要先建立可靠、可追踪、可幂等的 Agent 执行内核，作为后续接入 LangGraph 的稳定持久化与工具执行边界。

## What Changes

- 新增独立的 `WorkflowRun`、`WorkflowStep`、`WorkflowEvent`、`OutboxEvent` 与 `ToolExecution` 持久化模型，停止用一张 `TaskCard` 同时表达普通任务、编排实例和步骤运行态。
- 将编排创建改为单事务：父流程、步骤、依赖与首个 outbox 事件要么全部成功，要么全部回滚。
- 新增 PostgreSQL outbox worker，通过租约、条件更新和执行尝试号抢占步骤；HTTP/SSE 入口只提交命令并返回进度，不同步跑完整 DAG。
- 为 LLM 与技能副作用增加稳定幂等键；崩溃恢复只回收过期租约，不再无条件把所有执行中步骤重置后重跑。
- 建立父流程真实终态与人工停点状态，真人验收通过事件唤醒下游步骤。
- 为 Agent、LLM、步骤和工具执行增加 workflow/step/attempt/trace 关联，支持端到端追踪。
- 引入强类型 `SkillExecutor`/`SkillRequest`/`SkillResult` 接口和 `ToolDispatcher`，通过依赖注入消除 `base → skills → service → base` 循环依赖。
- 新增结构化动作协议；保留现有中文文本指令作为兼容适配器，逐步迁移到模型 tool calling。
- **BREAKING**：编排启动接口语义从“请求内执行到停点”调整为“持久化提交并异步推进”；现有响应保留进度快照，但初始状态可能为 queued/running。

## Capabilities

### New Capabilities

- `durable-workflow-runtime`: 工作流实例、步骤、事件、租约抢占、状态推进、人工停点与崩溃恢复。
- `transactional-outbox-worker`: 事务性 outbox、后台 worker、可靠投递、重试和过期租约回收。
- `idempotent-tool-execution`: LLM/交付/协作等执行尝试的幂等键、副作用去重与结果复用。
- `typed-agent-skills`: 强类型技能契约、统一调度器、结构化动作与旧文本协议兼容层。
- `workflow-traceability`: workflow、step、attempt、AgentTaskRecord、LLM usage 与工具执行的关联追踪。

### Modified Capabilities

无现有 OpenSpec capability；现有任务卡、桌面对话和人工验收行为由上述新 capability 兼容承接。

## Impact

- 数据库：新增工作流、步骤、事件、outbox、工具执行表及必要索引；为 AgentTaskRecord/LLM 日志增加追踪外键或关联字段。
- 后端：重构 `orchestration_service`、`task_service`、`desktop_chat_service`、`scheduler`、`agents/base.py`、`agents/skills.py` 与各技能 service。
- API/SSE：编排启动改为异步提交；进度查询继续使用结构化快照。
- 运行时：应用 lifespan 启动轻量 outbox worker，并在关闭时安全停止；后续可无缝迁移为独立 worker 进程。
- 测试：增加事务回滚、并发抢占、崩溃重放、交付幂等、人工恢复、追踪链和导入环回归测试。
- 文档：更新任务编排设计、总体架构与生产运维说明，为未来 LangGraph adapter 预留边界。
