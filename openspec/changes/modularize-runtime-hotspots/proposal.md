## Why

Durable Agent runtime 已经完成持久化、Outbox、幂等与人工停点，但几个核心模块仍同时承担过多职责，且步骤租约与 Outbox 重试之间存在可能让步骤永久停在 `running` 的恢复闭环缺口。接入 LangGraph 前，需要先把运行时边界拆清并让崩溃恢复具备端到端保证。

## What Changes

- 修复步骤执行事件在有效租约期间被重放时的处理语义：区分已抢占、正忙和已终态，正忙事件延迟到步骤租约后再尝试，不能提前完成并丢失恢复触发。
- 增加过期步骤周期扫描与确定性补发，保证即使原 Outbox 已结束，租约过期步骤仍可重新进入执行队列。
- 拆分 `workflow_service.py` 的 repository、状态机、投影/镜像和恢复职责，同时保留兼容导出。
- 拆分 `orchestration_service.py` 的规划、新 durable 入口和旧 TaskCard-only 兼容执行器，隔离双运行时。
- 拆分 `workflow_worker.py` 的轮询循环、事件处理和步骤执行器；将长函数外部调用与短事务状态更新分离。
- 拆分技能注册/提示词、旧中文指令适配和 `ToolDispatcher`，保持现有 `app.agents.skills` 公共 API 兼容。
- 拆分桌面对话流式编排、飞书登录状态/交换票据、会议 AI 动作和大型前端页面中的独立组件/Hook。
- 新增结构、恢复、兼容性和前端回归测试，并更新架构文档与 Graphify 输出。

## Capabilities

### New Capabilities

- `workflow-recovery-safety`: 覆盖 Outbox/步骤租约协调、忙碌事件延迟、过期步骤补发和崩溃后最终恢复。
- `modular-runtime-boundaries`: 覆盖工作流、编排、Worker 与技能运行时的稳定端口、兼容导出和职责隔离。
- `modular-domain-services`: 覆盖桌面对话、飞书登录、会议服务和大型前端页面的行为保持型拆分。

### Modified Capabilities

无已发布 OpenSpec capability；本变更保持现有 API、数据库表和业务语义兼容。

## Impact

- 后端：`app/services/workflow_*`、`orchestration_service`、`app/agents/skills`、桌面对话、飞书登录、会议服务及其调用方。
- 前端：Dashboard、OrgAdmin 等大型页面的展示组件和数据 Hook，路由与 API 不变。
- 运行时：Worker 增加恢复扫描；不引入新消息队列或新数据库表。
- LangGraph：进一步明确其只能接在 planner/transition adapter 上，不能旁路 PostgreSQL、Outbox、ToolExecution 或人工审批。
- 测试与文档：增加崩溃恢复集成测试、模块边界回归测试、前端构建检查和 Graphify 更新。
