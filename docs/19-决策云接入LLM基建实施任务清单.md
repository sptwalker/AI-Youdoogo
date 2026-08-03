# 决策云接入 LLM 基建实施任务清单

> 状态：待实施清单（2026-07-29）
> 输入：[`docs/18-决策云接入LLM基建与Lodge落地方案.md`](18-决策云接入LLM基建与Lodge落地方案.md)。
> 本清单只安排决策云仓库的工作；`llm_api`、`llm_wiki`、Lodge 的改造以明确契约/验收作为前置条件，不把它们尚未实现的能力当作可调用能力。

## 1. 执行边界、术语与总依赖

### 1.1 不变量（所有 Epic 的验收前提）

1. 决策云继续是提案、会议、审批、任务及 `WorkflowRun` 的真相源；`app/models/workflow.py:WorkflowRun`、`WorkflowStep`、`WorkflowEvent` 绝不迁移到 `llm_api`、`llm_wiki` 或 Lodge。
2. 会话记忆、偏好、推断和 agent scratchpad 继续由 `app/contexts/foundations/knowledge/organizational_memory/contracts.py:DistillConversationCommand` 及其本地实现拥有；不发布、不迁移到 Wiki。
3. 业务调用只描述 `purpose` 与 `CapabilityNeeds`，绝不出现实际模型名、provider URL、provider key 或 fallback model list。`model_role` 只是迁移兼容字段，不能成为新业务 API。
4. 身份失效、ACL 拒绝、预算拒绝、purpose/policy 拒绝一律 fail closed；不得以 `app/llm`、本地个人知识或宽松本地查询绕过。只有经审批、默认关闭的可用性应急开关可处理非敏感场景。
5. 浏览器的 Lodge target token 不转发给下游；后端到 `llm_api`/`llm_wiki` 使用各自服务凭证，代表真人时另带短期 delegated token。JWT、Authorization、prompt 全文均不进普通日志。

### 1.2 阶段标签与并行规则

| 标签 | 含义 | 可切生产流量？ |
|---|---|---|
| **立即实施** | 只依赖本仓库；可以建立 DTO、开关、表、测试和观测，但默认不调用未来接口。 | 否，除纯观测/兼容代码。 |
| **依赖 llm_api 后实施** | 必须以 `llm_api` 已上线 capability API、双凭证鉴权、稳定错误/SSE 契约为前置。 | 先影子，再灰度。 |
| **依赖 llm_wiki 后实施** | 必须以 Wiki 已装配 delegated/service status、检索 provenance、受控 ingestion 为前置。 | 先低敏只读，再发布。 |
| **依赖 Lodge 后实施** | 必须以 Lodge 注册 `youdoogo`、target handoff、JWKS/status/token exchange 为前置。 | 先双栈，再切换。 |
| **最终退役** | 只有迁移数据、流量、审计和回滚窗口都达到门槛后才删除旧路径。 | 是，且需变更批准。 |

并行编号中的 `||` 表示可并行；`->` 表示必须完成后才开始。所有带远程调用的任务均需先有契约测试（可用 fake HTTP/JWKS）再接真实环境。

### 1.3 已核实的改造锚点

以下为本清单使用的真实仓库锚点，避免把总体设计直接复制为无落点的计划：

- `app/contexts/foundations/model_gateway/contracts/completion.py:LlmCompletionRequest/LlmCompletionPort`
- `app/contexts/foundations/model_gateway/public.py:build_local_llm_completion_port`
- `app/contexts/foundations/model_gateway/infrastructure/local_adapter.py:LocalLlmAdapter`
- `app/llm/roles.py:get_llm_for_role` 与 `app/llm/fallback.py:FallbackChatModel`
- `app/api/v1/ai_providers.py:router` 与 `app/models/ai_provider.py:AiProvider`
- `app/contexts/foundations/knowledge/knowledge_retrieval/contracts.py:KnowledgeRetrievalPort/KnowledgeHit/Citation`
- `app/contexts/foundations/knowledge/knowledge_retrieval/infrastructure/sqlalchemy_retrieval.py:search/answer`
- `app/models/knowledge.py:KnowledgeBase/KnowledgeFile/KnowledgeVector`
- `app/platform/outbox/model.py:OutboxEvent`、`app/platform/outbox/repository.py:enqueue/claim_next/fail`
- `app/models/llm_log.py:LlmCallLog` 与 `app/models/workflow.py:WorkflowRun`
- `app/api/deps.py:get_current_user`、`app/api/v1/auth.py:router`、`app/core/security.py:decode_access_token`
- `app/platform/service_identity/jwt.py:ServiceTokenIssuer/ServiceTokenVerifier`
- `app/core/sse.py:sse_response`、`app/api/v1/meetings.py:ai_speak`
- `frontend/src/api/http.ts`、`frontend/src/api/auth.ts`、`frontend/src/pages/Login.tsx`、`frontend/src/components/RequireAuth.tsx`
- `app/core/config.py:Settings`、`.env.example`、`.env.production.example`、`ops/cce/runtime.yaml.tmpl`、`scripts/ci/deploy-cce.sh`

## 2. Epic 0 — 立即实施：契约、护栏和可观测地基

### T0.1 [P0｜立即实施｜可与 T0.2、T0.5、T0.6 并行] 调用点盘点与防回退守卫

- **目的**：把现有“按角色选本地模型”的调用面冻结为可度量基线，禁止新增业务直连模型/本地检索，防止迁移期间出现第二条绕行链路。
- **真实文件/符号**：`app/contexts/foundations/model_gateway/public.py:build_local_llm_completion_port`，`app/llm/roles.py:get_llm_for_role`，`tests/test_architecture_boundaries.py::test_llm_completion_flows_through_model_gateway_seam`，`tests/test_model_gateway_seam.py`。
- **具体改动**：补充 AST/导入守卫，限定 `app/contexts/**` 只能经 model gateway public/contract 获得 completion port；建立 purpose、业务类型、是否流式、`business_ref` 哈希的基线记录。盘点 `app/llm` 的消费点并为每项登记迁移 owner；不在本任务改业务行为。
- **依赖**：无；T0.2 的新 DTO 名称应在守卫规则合入前冻结。
- **验收标准**：CI 能列出所有豁免且无无主豁免；新增业务文件 import `get_llm_for_role` 或 LangChain 完成模型即失败；基线不含 prompt、JWT、API key、明文业务 ID。
- **验证命令**：`uv run pytest tests/test_architecture_boundaries.py tests/test_model_gateway_seam.py -q`；`uv run ruff check app tests`。
- **回滚**：移除新增 guard/telemetry 开关；不删除既有 LLM 日志或业务记录。
- **风险**：过严的静态规则会误伤探针或测试；用最小、带失效日期的白名单，禁止无限期豁免。

### T0.2 [P0｜立即实施｜T0.1 完成前可并行；T0.3/T0.4 依赖] CapabilityNeeds 与调用上下文契约

- **目的**：将 `model_role` 演进为不泄露模型控制面的业务能力描述，使远程/本地实现可由同一端口承接。
- **真实文件/符号**：`app/contexts/foundations/model_gateway/contracts/completion.py:LlmCompletionRequest/LlmCompletionResponse/LlmCompletionStreamChunk/TokenUsage`，`app/contexts/foundations/execution/agent_execution/application/ports.py:LlmExecutionPort`，`docs/adr/0001-llm-completion-port.md`。
- **具体改动**：新增纯 dataclass `CapabilityNeeds`（reasoning、context、modality、cost_tier、latency、streaming、structured_output），`ActorContext`、`BusinessRef`、`RequestMetadata`；请求改为 `purpose`、消息、能力、request/idempotency key，响应增加 route decision、policy version、稳定 error/fallback reason。保留只读兼容构造器把旧 `model_role` 映射为 purpose，禁止 DTO 序列化出 `model`、provider 或密钥字段。
- **依赖**：无；枚举和值域须先与 `llm_api` 共同冻结，但不能等待其实现才编写本地契约测试。
- **验收标准**：contracts 不 import FastAPI、HTTP client 或 LangChain；非法 purpose/超时/空幂等键被拒；新调用方不需要模型名；旧流在迁移窗口仍能被明确映射并产生 warning/metric。
- **验证命令**：`uv run pytest tests/test_model_gateway_seam.py tests/test_execution_contracts.py -q`；`uv run mypy app/contexts/foundations/model_gateway`。
- **回滚**：composition 继续只构造 `LocalLlmAdapter`；保留兼容字段，不丢弃旧调用的可读性。
- **风险**：把 provider 语义伪装进 purpose 或无限扩张枚举；以 allowlist 和版本化契约评审阻断。

### T0.3 [P0｜立即实施（fake/关闭态）｜依赖 T0.2；可与 T0.5/T0.6 并行] RemoteLlmApiAdapter、SSE、错误与幂等骨架

- **目的**：在不依赖远程服务上线的前提下完成可测试的 HTTP 边界，避免以后在业务路由里散落重试与 SSE 解析。
- **真实文件/符号**：新增 `app/contexts/foundations/model_gateway/infrastructure/remote_llm_api_adapter.py`，`app/contexts/foundations/model_gateway/contracts/completion.py:LlmCompletionPort`，`app/core/sse.py:sse_response`，`app/api/v1/meetings.py:ai_speak`，`tests/test_sse.py`。
- **具体改动**：实现端口的 non-stream/stream 双路径；统一发送 `X-Request-ID`、`Idempotency-Key`、服务凭证和（存在时）delegated token；按 deadline 取消 `httpx` 请求。把远程 `route.started/delta/usage/route.completed/stream.error` 映射为本地 stream chunk，首个 `delta` 后禁止自动重放；将 401/403/402/409/422/429/5xx/超时归一为业务可判定错误码。利用 fake transport/respx 测协议，实际 base URL 未配置时 fail closed，不回落本地。
- **依赖**：T0.2；真实接入另依赖 T1.1；用户委托令牌另依赖 T3.1/T3.3。
- **验收标准**：非流式同 idempotency key 重试只返回一个逻辑结果；流式首 token 前可按服务返回的安全标记重试一次、首 token 后只能报错并保留已发文本；错误帧不泄露 Authorization/prompt；客户端断开能关闭上游请求。
- **验证命令**：`uv run pytest tests/test_sse.py tests/test_model_gateway_seam.py -q`；新增后执行 `uv run pytest tests/test_http_adapter_cleanup.py -q`。
- **回滚**：`MODEL_GATEWAY_MODE=local` 不实例化 remote adapter；已生成的 request_id/审计仅保留，不重放业务动作。
- **风险**：把上游 SSE 直接透传给浏览器造成协议和密钥泄露；只允许本地受控事件白名单。

### T0.4 [P0｜立即实施｜依赖 T0.2；T1.2 前不切流] Composition 开关与模型控制面冻结

- **目的**：让模型调用只有一个切换点，并从现在起阻止本地 Provider 控制面继续扩大。
- **真实文件/符号**：`app/contexts/foundations/model_gateway/public.py:build_local_llm_completion_port`，`app/contexts/foundations/model_gateway/infrastructure/local_adapter.py:LocalLlmAdapter`，`app/llm/factory.py:build_candidates`，`app/llm/fallback.py:FallbackChatModel`，`app/api/v1/ai_providers.py:router`。
- **具体改动**：新增 `build_llm_completion_port()`，只读取 `MODEL_GATEWAY_MODE=local|shadow|remote|local_emergency`；shadow 仅异步比对、绝不向用户生成第二个结果或重复业务副作用。对 `/ai-providers` 新增“冻结新增/变更”运行态门禁和审计，保留读取与退役盘点；业务降级保留在 use case（如保存草稿、Workflow 重试），不得在 adapter 选择模型。
- **依赖**：T0.2、T0.5；`remote` 模式依赖 T1.2；`local_emergency` 的审批流程依赖 T4.2。
- **验收标准**：全仓业务调用经 public factory；shadow 不改变 API 输出、用量账或工作流状态；没有任何新代码从请求体/数据库读取实际模型名；默认模式保持 local。
- **验证命令**：`uv run pytest tests/test_model_gateway_seam.py tests/test_ai_provider.py -q`；`uv run pytest tests/test_architecture_boundaries.py -q`。
- **回滚**：环境变量切回 `local`；不删除 Provider 卡片、密钥或 `AiProvider` 表。
- **风险**：shadow 意外二次执行非幂等业务；shadow 只允许 adapter 层的只读远程请求和脱敏比较。

### T0.5 [P0｜立即实施｜可与 T0.1–T0.4 并行] 配置、Secret、链路观测与审计扩展

- **目的**：为远程调用提供受控配置、密钥引用和可回溯证据，而不是把 provider key 搬到新的环境变量。
- **真实文件/符号**：`app/core/config.py:Settings`，`.env.example`，`.env.production.example`，`ops/cce/runtime.yaml.tmpl`，`scripts/ci/deploy-cce.sh`，`app/models/llm_log.py:LlmCallLog`，`app/bootstrap/observability.py`。
- **具体改动**：增加非敏感项 `MODEL_GATEWAY_MODE`、`LLM_API_BASE_URL`、超时、purpose allowlist、`KNOWLEDGE_RETRIEVAL_MODE`、`LLM_WIKI_BASE_URL`、Lodge issuer/JWKS/audience/status TTL；将每个下游的服务凭证、mTLS 和 token-exchange 凭证列为 Secret key。新增 Alembic 迁移扩展 `LlmCallLog` 或独立调用审计表，记录 request/route decision、purpose、capability/provenance/business-ref 哈希、SSE completion、稳定失败码，不记录 token/prompt/实际模型名（模型仅留基建受限审计）。
- **依赖**：T0.2；字段名须与 T1.1/T2.1/T3.1 契约对齐。
- **验收标准**：生产配置缺远程模式所需 Secret 时启动失败；健康/异常/日志无 Secret；同一 request_id 能关联本地业务审计、LLM/Wiki 调用和 workflow trace；迁移可升级、可降级。
- **验证命令**：`uv run pytest tests/test_config.py tests/test_llm_usage.py tests/test_metrics.py -q`；`uv run alembic upgrade head`；`python scripts/ci/preflight_vars.py`（提供 CI 所需变量）。
- **回滚**：关闭远程模式并保留新列/表；应用回退前先执行兼容性检查，禁止删除审计数据。
- **风险**：把 Secret 名当作值写进 ConfigMap 或 frontend bundle；以部署脚本 Secret key 校验和前端构建扫描拦截。

### T0.6 [P1｜立即实施（契约/关闭态）｜可与 T0.2–T0.5 并行] RemoteLlmWikiAdapter 与远程检索 composition

- **目的**：预先建立远程 Wiki 的端口实现和 local/dual-read/remote 切换，不假设当前 Wiki delegated/service 调用已经可用。
- **真实文件/符号**：`app/contexts/foundations/knowledge/knowledge_retrieval/contracts.py:KnowledgeRetrievalPort/SearchKnowledgeQuery/KnowledgeHit/Citation`，`app/contexts/foundations/knowledge/knowledge_retrieval/public.py:build_local_knowledge_search_port`，`app/contexts/foundations/knowledge/knowledge_retrieval/infrastructure/sqlalchemy_retrieval.py:search/answer`，新增 `remote_llm_wiki_adapter.py`。
- **具体改动**：扩展 hit/citation 为 source system、document/version/chunk/namespace、retrieved_at、ACL decision、query hash；新增 remote adapter 仅面向已存在 `/api/v1/search`/`ask` 的版本化 DTO 和 fake client。新增 composition `local|dual_read|remote`：dual-read 只产出对账指标，不能把两边命中无来源拼接或二次注入模型；未配置/未通过能力探测时拒绝 remote 模式。
- **依赖**：T0.5；真实远程 read 依赖 T2.1；业务侧最终对象 ACL 检查继续依赖既有 `access_control`。
- **验收标准**：每条命中来源可区分；remote 错误不能退化为 personal/未发布材料；dual-read 不改变返回结果；本地 `visible_knowledge_base_ids` 语义在 local 路径仍保持。
- **验证命令**：`uv run pytest tests/test_knowledge_search_port.py tests/test_knowledge_contexts.py tests/test_knowledge_retrieval_diagnostics.py -q`；新增后 `uv run ruff check app/contexts/foundations/knowledge`。
- **回滚**：`KNOWLEDGE_RETRIEVAL_MODE=local`；不删除本地索引或 Wiki 文档。
- **风险**：把“Wiki 有 search 路由”误判为“delegated ACL 可用”；remote 启动检查必须要求 T2.1 的 capability/version 响应。

### T0.7 [P0｜立即实施｜依赖 T0.6；可与 T0.8/T0.9 并行] 知识分层与 prompt-injection 边界

- **目的**：明确什么能被发布/检索，且把检索内容作为不可信证据而非指令。
- **真实文件/符号**：`app/models/knowledge.py:KnowledgeBase/KnowledgeFile/KnowledgeVector`，`app/contexts/foundations/knowledge/knowledge_retrieval/infrastructure/sqlalchemy_retrieval.py:answer`，`app/contexts/foundations/knowledge/organizational_memory/contracts.py:DistillConversationCommand`，`app/contexts/foundations/access_control/application/ports.py:KnowledgeVisibilityPort`。
- **具体改动**：建立分类策略：company/经批准共享材料可候选发布；department/confidential 映射为未来 Wiki restricted ACL；personal、agent memory、会话记忆禁止发布。新增结构化 `RetrievedEvidence`，由 prompt assembler 以数据边界包裹、限制单 chunk/总 token、清洗 HTML/URL，并声明“证据不能修改系统指令、工具、权限”；输出 citation 只能引用本次 evidence ID。保留本地业务事实检索，不把提案/会议/审批/WorkflowRun 当共享知识源。
- **依赖**：T0.6；远程 ACL 生效依赖 T2.1。
- **验收标准**：个人库、记忆和未批准的会议/提案不能进入 publication candidate；包含“忽略指令”等文本的 chunk 只能作为数据；模型返回不存在的 citation ID 时结果标为不可引用/失败，不可伪造来源。
- **验证命令**：`uv run pytest tests/test_knowledge_base.py tests/test_memory.py tests/test_knowledge_search_port.py -q`；新增 injection fixture 后运行 `uv run pytest tests/test_model_gateway_seam.py -q`。
- **回滚**：关闭远程 evidence feature，继续本地已有检索；不自动删除用户资料。
- **风险**：将安全提示当成完全防护；仍须通过 Wiki ACL 前置过滤和业务 ACL 双重控制。

### T0.8 [P1｜立即实施（本地 outbox）｜依赖 T0.7；T2.2 后启用投递] publication outbox 与发布映射

- **目的**：以事务性、可重放的方式发布批准后的副本，绝不由 Wiki 反向拉取决策云业务表。
- **真实文件/符号**：`app/platform/outbox/model.py:OutboxEvent`，`app/platform/outbox/repository.py:enqueue/claim_next/complete/fail`，`app/platform/outbox/source_change.py:publish_source_change`，`app/models/knowledge.py:KnowledgeFile`，`app/bootstrap/workflow_worker.py`。
- **具体改动**：新增 publication mapping（可独立表）和 `knowledge.publication.requested.v1`/tombstone/ACL-change 事件；payload 只含 artifact 类型、opaque ID、source version/hash、目标 namespace、审批证据，正文在 worker 受控读取。dedupe key 固定 `youdoogo-publication:{artifact}:{id}:v{version}`；借用 lease/retry/DLQ/replay 模式，记录 external document ID/version、状态、最后错误。发布入口必须显式审批，不扫描全库自动同步。
- **依赖**：T0.7、T0.5；真实写入依赖 T2.2；worker 注册方式需与现有 bootstrap 对齐。
- **验收标准**：同一版本重复 enqueue 只一条 event；事务回滚不会产生 outbox；撤回只产生 tombstone/ACL 收紧，不删除业务原件；死信可人工重放且保留 attempt/audit。
- **验证命令**：`uv run pytest tests/test_event_transport.py tests/test_durable_workflow.py tests/test_knowledge_contexts.py -q`；`uv run alembic upgrade head`。
- **回滚**：停止 publication worker，保留 pending event 和 mapping；无需删除远端历史。
- **风险**：worker 重试导致重复写/重复计费；版本化 external ID、下游 idempotency key 与 mapping 三层去重。

### T0.9 [P0｜立即实施｜依赖 T0.6/T0.7；可与 T0.8 并行] citation provenance 与业务结果版本绑定

- **目的**：让每个引用可审计、可复核，且资料更新后仍能知道生成时使用的是哪个版本。
- **真实文件/符号**：`app/contexts/foundations/knowledge/knowledge_retrieval/contracts.py:Citation/KnowledgeAnswer`，`app/models/llm_log.py:LlmCallLog`，`app/models/workflow.py:WorkflowRun/WorkflowStep/WorkflowEvent`，`app/contexts/business/meeting_management/entrypoints/operations.py:ai_expert_speak_stream`。
- **具体改动**：新建 provenance 表（或严谨 JSONB schema）关联 `business_ref(type,id,output_version)`、request_id、citation set hash，逐项存 source_system/document_id/document_version/chunk_id/namespace/retrieved_at/query_hash/rank/acl decision/citation label；禁止存 document 全文、JWT。提案、会议生成物、审批说明和 workflow 输出只有在调用链提供 business_ref 时写入；没有可引用证据的结果显式标记“无外部引用”。
- **依赖**：T0.5、T0.6；远程完整字段依赖 T2.1。
- **验收标准**：同一引用集可稳定 hash；文档当前版本改变不改写历史 provenance；跨用户/跨业务对象读取 provenance 仍经过本地业务 ACL；对 WorkflowRun 仅记录关联，不把 run payload/状态同步出去。
- **验证命令**：`uv run pytest tests/test_meetings.py tests/test_proposal_application.py tests/test_durable_workflow.py -q`；`uv run alembic upgrade head`。
- **回滚**：停止写新 provenance；保留已写记录和业务结果，不尝试“回填当前版本”。
- **风险**：把 citation 表做成无边界的 prompt 存档；数据库约束、长度上限和日志脱敏共同限制。

## 3. Epic 1 — 依赖 llm_api：能力完成调用的真实接入

### T1.1 [P0｜依赖 llm_api 后实施｜T0.2/T0.3/T0.5 -> T1.1；可与 T2.1/T3.1 并行] capability API 联调门

- **目的**：确认 `llm_api` 的新能力接口真实提供 server-side 选模、双凭证验证、预算与稳定 SSE，而不是沿用可带 model 的旧 OpenAI 兼容接口。
- **真实文件/符号**：本仓 `remote_llm_api_adapter.py`（T0.3 新增）、`LlmCompletionPort`；外部前置为 `llm_api/internal/httpapi/router.go` 的 capability 路由、`CallerAuthV3`、CapabilityNeeds schema（以版本化 OpenAPI/契约包为准）。
- **具体改动**：固定 HTTP schema、header、SSE event、错误码与 health/capability discovery；对请求强制拒绝 `model`、provider、user/department 自报字段。配置服务身份和 token-exchange 目标 audience；只在集成环境以受控 test org 请求，不接生产流量。
- **依赖**：`llm_api` 已实现 `POST /v1/capability-completions`、service+delegated 双凭证、预算前置、idempotency store、SSE terminal usage；没有这些能力，本任务阻塞且保持 T0.3 关闭态。
- **验收标准**：wrong audience、缺服务凭证、缺 required delegation、伪造 department、预算超限均被远端拒绝；无模型名请求得到 route decision/usage；远端能回显 request_id 且不记录敏感头。
- **验证命令**：`uv run pytest tests/test_model_gateway_seam.py tests/test_sse.py -q`；在隔离环境运行新增 `uv run pytest tests/test_llm_gateway.py -q`（以 respx/OpenAPI fixture + 联调 profile）。
- **回滚**：撤销 test service credential，`MODEL_GATEWAY_MODE=local`；不降低 audience、ACL 或预算校验以“临时打通”。
- **风险**：以 API key 单独替代真人授权；仅可作为迁移期服务认证，需服务与 delegated token 职责分离。

### T1.2 [P0｜依赖 llm_api 后实施｜依赖 T1.1；T1.3 后再灰度] 远程流式、错误与业务降级接通

- **目的**：把真实远程调用安全映射到现有业务 SSE 和 Workflow 语义，不让基础设施失败伪造业务成功。
- **真实文件/符号**：`app/core/sse.py:sse_response`，`app/api/v1/meetings.py:ai_speak`，`app/contexts/foundations/model_gateway/infrastructure/remote_llm_api_adapter.py`，`app/models/workflow.py:WorkflowStep`。
- **具体改动**：接入 T1.1 的事件协议；将用户断开、deadline、429、路由无可用模型、预算/身份/策略拒绝转换为明确结果。可重试的工作流步骤按 `WorkflowStep.attempt` 和 request/idempotency key 入队；交互流只显示已发部分+可重试状态。认证/ACL/预算拒绝不重试到本地；网络/5xx 才依 purpose 分类进入等待/重试。
- **依赖**：T1.1、T0.8（异步工作流降级时）；现有 SSE 前端消费测试。
- **验收标准**：首 token 后上游断流只产生一个 `error`，不重复前缀；401/403/402 不触发本地 fallback；workflow crash/retry 不重复调用/计费；业务状态保持草稿、等待或失败的真实状态。
- **验证命令**：`uv run pytest tests/test_sse.py tests/test_workflow_status_policy.py tests/test_durable_workflow.py -q`；`uv run pytest tests/test_llm_usage.py -q`。
- **回滚**：切回 local；正在进行的远程 run 标为可恢复/待重试，不将已流式输出当作已确认决策。
- **风险**：SSE HTTP 200 后错误无法改状态码；统一终止事件与客户端状态机，禁止仅依 HTTP status。

### T1.3 [P1｜依赖 llm_api 后实施｜依赖 T1.1；可与 T2.1/T3.1 并行] 影子评测、成本/延迟门和 purpose 灰度

- **目的**：用可量化证据替代“一次性切换”，按 purpose 而非模型名灰度。
- **真实文件/符号**：`app/models/llm_log.py:LlmCallLog`，`app/bootstrap/observability.py`，`app/contexts/foundations/model_gateway/public.py:build_llm_completion_port`（T0.4），`tests/test_eval.py`。
- **具体改动**：shadow 对低风险、可脱敏样本记录质量代理、p95、超时率、错误码、tier、成本和拒绝率；配置 purpose allowlist/百分比/kill switch。建立发布阈值：无 P0 安全拒绝绕过、错误预算达标、质量不低于基线、预算可解释；正式请求只发送一次，shadow 不落业务副作用。
- **依赖**：T1.1、T0.5；生产灰度依赖 T1.2 和变更批准。
- **验收标准**：每个切换 purpose 有基线、阈值、owner、回滚开关；指标能按 request_id/business type 聚合且不含敏感内容；阈值不达标自动停止扩大比例。
- **验证命令**：`uv run pytest tests/test_metrics.py tests/test_eval.py tests/test_llm_usage.py -q`；在 staging 运行约定 smoke（不带真实生产数据）。
- **回滚**：将该 purpose 比例设为 0，保留匿名统计和已完成审计。
- **风险**：shadow 消耗双份预算或泄露数据；只使用已批准的脱敏样本/隔离预算，生产 shadow 默认禁用。

## 4. Epic 2 — 依赖 llm_wiki：受控知识读取、发布与引用

### T2.1 [P0｜依赖 llm_wiki 后实施｜T0.6/T0.7/T0.9 -> T2.1；可与 T1.1/T3.1 并行] Wiki delegated/service status 与只读远程检索

- **目的**：在 Wiki 真正完成鉴权装配后启用 remote/dual-read，确保 ACL 在检索前而不是决策云响应后执行。
- **真实文件/符号**：本仓 `remote_llm_wiki_adapter.py`（T0.6）、`KnowledgeRetrievalPort`、`KnowledgeVisibilityPort`；外部前置为 Wiki `internal/auth/identity_resolver.go`、`internal/httpapi/authz.go:RouteAsk/RouteSearch`、`internal/store/retrieval.go:HybridSearch` 的已部署实现。
- **具体改动**：传输 `aud=llm_wiki` delegated token、服务凭证和受签名 membership context；校验远程 capability/version；严格保留 external document/version/chunk/ACL provenance。对于共享资料必需的审批/高风险用途，Wiki 不可用即进入待重试；仅允许已声明 local workset 的低风险 purpose 使用本地路径，且结果要标明来源。
- **依赖**：Wiki 已有 delegated/status checker 与 service status checker 的实际装配、`act.client_id=youdoogo` allowlist、ACL 在 vector/BM25/rerank 前过滤；T3.3 用于委托 token。
- **验收标准**：tenant/membership 篡改、过期 delegation、无 service credential、ACL 越权均无任何 hit/citation；无权 chunk 不进入模型上下文；每个远程 citation 都有 version；本地二次 ACL 只收紧业务对象访问，不扩权。
- **验证命令**：`uv run pytest tests/test_knowledge_search_port.py tests/test_knowledge_contexts.py tests/test_access_control_infrastructure.py -q`；staging 合约矩阵（allowed/denied/expired/status-down）全部通过。
- **回滚**：切 `KNOWLEDGE_RETRIEVAL_MODE=local`，保留 Wiki 内容/历史 provenance；对必须共享知识的 purpose 停止而非回读 personal memory。
- **风险**：把 `membership_context` 当任意请求 JSON；仅从已验证委托 token/受信映射生成并限制长度、版本、client。

### T2.2 [P1｜依赖 llm_wiki 后实施｜依赖 T0.8/T2.1；可与 T3.1 并行] publication worker、撤回和版本对账

- **目的**：将明确批准的报告、纪要快照和知识条目以幂等副本发布到 `youdoogo.shared`，而不是迁移业务数据。
- **真实文件/符号**：`app/platform/outbox/repository.py:claim_next/complete/fail`，`app/platform/outbox/model.py:OutboxEvent`，`app/models/knowledge.py:KnowledgeFile`，T0.8 的 publication mapping；外部前置为 Wiki ingestion handler/`RouteServiceIngestion` 和 version/tombstone 契约。
- **具体改动**：实现 consumer：读取批准的 artifact snapshot，调用 Wiki upsert，写回 mapping；source namespace、external ID、source hash、idempotency key 固定。撤回、ACL 改变和内容修订发 versioned event；失败采用退避/DLQ/人工 replay；对账 hash、ACL、chunk count、remote version。禁止读取/发布 `WorkflowRun`、会议发言原文、审批流明细、私密记忆。
- **依赖**：T0.8；Wiki 已实现 service ingestion、namespace 限制、atomic content+ACL write、tombstone/version 与幂等。
- **验收标准**：重复投递只产生一个 Wiki 文档版本；撤回不删除 Proposal/Meeting/WorkflowRun 原件；对账失败阻止把该库设为 remote 主读；审计能回答谁批准、何时发布、哪个版本撤回。
- **验证命令**：`uv run pytest tests/test_event_transport.py tests/test_knowledge_base.py tests/test_durable_workflow.py -q`；staging 执行 publish/retry/tombstone/replay 四组合同测试。
- **回滚**：停 worker、保留 outbox；通过 Wiki tombstone/收紧 ACL 撤回副本，绝不物理删除审计证据。
- **风险**：发布规则演变成全量同步；入口只接受显式 publish command 和批准记录。

### T2.3 [P1｜依赖 llm_wiki 后实施｜依赖 T2.1/T2.2] 库级主读迁移与本地索引保留策略

- **目的**：按库、按数据类别完成远程主读，而非一次性删除 `KnowledgeVector`。
- **真实文件/符号**：`app/models/knowledge.py:KnowledgeBase/KnowledgeFile/KnowledgeVector`，`app/contexts/foundations/knowledge/knowledge_retrieval/infrastructure/sqlalchemy_retrieval.py:search`，`KnowledgeRetrievalPort`。
- **具体改动**：给共享候选库加入 remote mapping/sync state/read routing；先 dual-read 对账，达标后将指定 company/approved shared 库设 remote primary。department/confidential 仅在 Wiki ACL 继承/管理 API 实际上线后迁移；personal 和 organizational memory 永远 local。保留本地原件/索引到迁移验收与回滚窗口结束。
- **依赖**：T2.1、T2.2；未来 Wiki knowledge-base/继承 ACL API 若未上线则本任务只做 company approved subset。
- **验收标准**：每个切库有 hash/ACL/chunk/retrieval quality 证据；当前任何 personal 库不被 remote 路由；远程未就绪库继续 local，不能假设未来路由存在。
- **验证命令**：`uv run pytest tests/test_knowledge_base.py tests/test_knowledge_search_port.py tests/test_retrieval_hybrid.py -q`；staging 迁移对账报告通过。
- **回滚**：库级切回 local，停止新的 publish；保留 mapping 和远端副本用于审计。
- **风险**：把本地搜索空结果等同迁移成功；必须以映射、版本、ACL 和抽样检索四项同时达标。

## 5. Epic 3 — 依赖 Lodge：resource server、身份投影与浏览器认证

### T3.1 [P0｜依赖 Lodge 后实施｜T0.5 -> T3.1；可与 T1.1/T2.1 并行] Lodge resource-server：JWKS、status、session 与安全降级

- **目的**：用 Lodge `aud=youdoogo` target token 替换浏览器身份信任根，同时保持后端资源服务器自主校验。
- **真实文件/符号**：新增 `app/platform/lodge_identity/*`，`app/api/deps.py:get_current_user`，`app/core/security.py:decode_access_token`，`app/platform/service_identity/jwt.py:ServiceTokenVerifier`，`app/core/config.py:Settings`。
- **具体改动**：实现固定 issuer/HTTPS JWKS client（kid cache、unknown-kid 限流和受控 refresh），验证 RS256、`typ`、单一 aud=`youdoogo`、exp/jti/sid/identity_ver/entitlement；实现 Lodge status client 和短缓存。令牌首次使用与缓存到期调用 status；status down 时新登录和敏感写 fail closed/暂停，不能用过期缓存扩权。建立本地 server-side session，cookie Secure/HttpOnly/SameSite/正确 base path，禁止 query token。
- **依赖**：Lodge 已注册 `youdoogo`、支持 target handoff、发行 v2 target token、JWKS、online status 与会话/identity version；未满足则不替换 HS256。
- **验收标准**：wrong/multi audience、HS256、未知 kid、过期 token、被禁用用户、撤销 sid、identity version 回退全被拒；status 不可用不扩大权限；token 不写日志/localStorage。
- **验证命令**：`uv run pytest tests/test_auth.py tests/test_service_identity.py tests/test_identity_characterization.py -q`；新增 JWKS/status fake server 合同测试。
- **回滚**：在时间盒迁移窗口仅让批准的 break-glass 管理员走旧认证；不得通过跳过 JWKS/status 校验恢复服务。
- **风险**：错误缓存 JWKS/status 造成撤销延迟；TTL、fail-closed、撤销演练和可观测指标共同控制。

### T3.2 [P0｜依赖 Lodge 后实施｜依赖 T3.1；可与 T3.3 并行] 用户投影、组织映射和本地业务 ACL

- **目的**：以 Lodge `sub` 作为不可变外部键，保留本地业务用户、部门和审批权限，而非共享用户表或以用户名匹配。
- **真实文件/符号**：`app/contexts/foundations/identity/contracts.py:Principal`，`app/contexts/foundations/identity/application/contracts.py:IdentityUserResult`，`app/contexts/foundations/identity/infrastructure/sqlalchemy_repository.py`，`app/api/deps.py:require_roles`，`app/models/system.py`（实际用户模型）及 Alembic migrations。
- **具体改动**：为本地用户投影增加 unique `lodge_subject`、identity/membership revision、同步状态/时间；编写受控 projection upsert 和停用逻辑，稳定关联现有 UUID 用户。Lodge 角色仅映射为决策云上限角色；提案/会议/审批/工作流等细粒度授权继续由本地 `access_control` policy 判定。部门映射由签名 membership/status 驱动，拒绝前端/业务 body 自报 department。
- **依赖**：T3.1；Lodge 提供稳定 sub、组织/membership revision、状态/变更语义。
- **验收标准**：重名用户不会串号；禁用/部门/角色变更在 TTL 内收紧权限；投影失败不授予默认管理员；业务 ACL 测试仍覆盖本地资源。
- **验证命令**：`uv run pytest tests/test_identity_application.py tests/test_org_sync.py tests/test_access_control_application.py tests/test_auth.py -q`；`uv run alembic upgrade head`。
- **回滚**：停止 projection consumer、保留只读映射快照；不恢复跨库双向写或共享 `users` 表。
- **风险**：将 Lodge system role 直接当业务审批权限；在映射层只赋角色上限，审批另走本地 policy。

### T3.3 [P0｜依赖 Lodge 后实施｜依赖 T3.1；T1.1/T2.1 依赖] 后端服务凭证与 delegated token exchange

- **目的**：建立浏览器、服务、代表用户三种不能互换的凭证，支持下游预算归因与 Wiki ACL。
- **真实文件/符号**：`app/platform/service_identity/contracts.py:ServiceIdentityClaims`，`app/platform/service_identity/jwt.py:ServiceTokenIssuer/ServiceTokenVerifier`，`app/core/config.py:internal_jwt_*`，T0.3/T0.6 adapter。
- **具体改动**：新增 credential provider：为 `llm_api` 和 `llm_wiki` 分别获取/缓存短期服务凭证；有真人动作时以已验证本地 session 换取 `aud=llm_api|llm_wiki`、`token_profile=delegated`、`act.client_id=youdoogo`、depth=1 的短 token。服务 token 不能代表用户；后台 Workflow 标记 `actor=service`，不伪造 user。迁移期下游专属 Secret 可作服务认证，但不取代 delegated token 或长存 JWT。
- **依赖**：Lodge 已实现 service registration、target-audience token exchange、scope intersection、状态校验和轮换；T1.1/T2.1 的下游验证实现。
- **验收标准**：浏览器 token 不能调用下游；一个下游 token 不能在另一下游使用；缺 delegated token 的用户 ACL 请求被拒；服务凭证轮换无明文落库/日志。
- **验证命令**：`uv run pytest tests/test_service_identity.py tests/test_auth.py -q`；staging 执行 audience/replay/delegation-depth/rotation 合同矩阵。
- **回滚**：撤销 `youdoogo` service grant，禁用 remote mode；保留本地业务状态，不能将 token exchange 放宽为通配 audience。
- **风险**：以现有内部 RS256 当作 Lodge 信任根；它只能是过渡封装，最终 issuer/JWKS/status 必须来自 Lodge。

### T3.4 [P1｜依赖 Lodge 后实施｜依赖 T3.1/T3.2；可与 T1.3 并行] 前端认证和退出迁移

- **目的**：前端只使用决策云会话，不保存或转发 Lodge access token，并安全完成 handoff、登出和迁移双栈。
- **真实文件/符号**：`frontend/src/api/http.ts`，`frontend/src/api/auth.ts`，`frontend/src/pages/Login.tsx`，`frontend/src/components/RequireAuth.tsx`，`app/api/v1/auth.py:feishu_start/feishu_exchange/refresh`。
- **具体改动**：替换登录按钮为跳转 Lodge handoff；`/auth/me` 以 HttpOnly 本地 session 判断登录，HTTP client 使用 `withCredentials` 而非 `setToken`/localStorage。移除飞书 exchange 成功后把 access token 写 session/local storage 的依赖；实现本地 logout 清 session、跳 Lodge logout、处理过期/撤销返回登录。保留旧登录仅迁移窗口、feature flag 和 break-glass 策略内可见。
- **依赖**：T3.1/T3.2；Lodge handoff cookie 的实际 path/domain/return-to allowlist。
- **验收标准**：bundle 和 storage 中没有 Lodge/JWT access token；刷新页面仍由 cookie session 恢复；CSRF/Origin/return_to 异常被拒；登出、禁用、session revoke 都回到登录页。
- **验证命令**：`cd frontend && npm run test && npm run lint && npm run build`；`uv run pytest tests/test_auth.py tests/test_feishu_frontend_contract.py -q`。
- **回滚**：前端 feature flag 回旧登录页（仅窗口内）；保留 server-side session 清理，不把 token 恢复到 localStorage。
- **风险**：cookie session 导致 CSRF；所有状态变更采用 Origin/CSRF 策略、SameSite 和 API 端二次认证。

## 6. Epic 4 — 迁移、灰度、回滚和交付门

### T4.1 [P0｜立即实施后贯穿执行｜依赖 T0.5；与全部实施任务并行] 数据迁移与兼容性演练

- **目的**：让 schema、用户投影、知识 mapping 和审计字段以可回滚、可观测方式演进。
- **真实文件/符号**：`alembic/env.py`，`alembic/versions/004_llm_call_log.py`，`alembic/versions/012_knowledge_base.py`，`alembic/versions/035_durable_workflow.py`，`app/models/llm_log.py:LlmCallLog`，`app/models/knowledge.py:KnowledgeFile`。
- **具体改动**：每个 Epic 拆独立 expand/backfill/contract migration：先加 nullable 列/新表/索引与双写观察，再回填/核验，最后才收紧约束或删旧字段。身份映射只读快照导入；知识发布 mapping 只对明确批准的 artifact 建档；禁止把提案、会议、审批、WorkflowRun 或私密工作记忆当迁移源。
- **依赖**：各上游任务的 schema；生产操作依赖备份、锁表评估和变更窗口。
- **验收标准**：每个 migration 有 upgrade、downgrade/前向修复说明、数据量与锁时评估；重复 backfill 幂等；回填核验可输出不含敏感数据的计数/哈希报告。
- **验证命令**：`uv run alembic upgrade head`；`uv run pytest tests/test_database_unit_of_work.py tests/test_environment.py -q`；在 staging 执行 `uv run alembic downgrade -1 && uv run alembic upgrade head`（仅对允许降级的迁移）。
- **回滚**：优先前向修复；对已发布 schema 使用 feature flag 停写，绝不靠删除生产数据回滚。
- **风险**：单次大表回填阻塞业务；分批、可续跑、低峰执行并监控锁等待。

### T4.2 [P0｜依赖 T1.2/T2.1/T3.1 后实施｜可与 T4.1 并行] 灰度、降级与统一 kill switch

- **目的**：把安全拒绝与可用性故障严格分开，提供按 purpose/库/认证路径的最小回滚面。
- **真实文件/符号**：`app/contexts/foundations/model_gateway/public.py`，`app/contexts/foundations/knowledge/knowledge_retrieval/public.py`，`app/core/config.py:Settings`，`app/core/shared_state.py`，`app/models/workflow.py:WorkflowRun`。
- **具体改动**：定义阶段开关：LLM local/shadow/remote、purpose 百分比、knowledge local/dual/remote、库级 read routing、Lodge dual-stack。对 401/403/402/policy deny 固定 fail closed；对网络/5xx/timeout 只按已批准 purpose 进入重试、草稿、待人工或（非生产非敏感）`local_emergency`。每个开关具 owner、过期时间、审计事件和 one-command rollback。
- **依赖**：T1.2、T2.1、T3.1；应急 local provider 仅在 T0.4 未退役前存在。
- **验收标准**：演练可在五分钟内停止单个 purpose/库/认证入口；预算/ACL/身份拒绝演练证明没有 local bypass；WorkflowRun 恢复不会重复外部副作用。
- **验证命令**：`uv run pytest tests/test_workflow_status_policy.py tests/test_durable_workflow.py tests/test_auth.py tests/test_budget.py -q`；staging game-day（timeout、budget denied、ACL denied、status down）。
- **回滚**：按开关缩小到 local/旧认证或暂停，不删除 outbox、审计或远端证据。
- **风险**：把“local emergency”常态化；仅非生产/非敏感、双人批准、自动过期、告警四项同时满足。

### T4.3 [P0｜立即实施后贯穿执行｜依赖 T0.5；与全部任务并行] 可观测、告警与交付门

- **目的**：在每次扩大影响面前证明治理链路、质量和可恢复性都有效。
- **真实文件/符号**：`app/bootstrap/observability.py`，`app/models/llm_log.py:LlmCallLog`，`app/platform/outbox/model.py:OutboxEvent`，`scripts/ci/smoke-youdoogo.sh`，`scripts/ci/deploy-cce.sh`，`tests/test_metrics.py`。
- **具体改动**：指标按 request_id、purpose、source_system、错误家族、route tier、SSE 完成、budget decision、Wiki ACL decision、outbox backlog/DLQ、JWKS/status cache、身份投影延迟切片；只采 hash/计数，不采 token/prompt。为每阶段建立 dashboard、阈值、告警 owner、runbook 和交付门记录。
- **依赖**：T0.5；远程维度依赖相应 Epic 接通。
- **验收标准**：能从一个 request_id 追踪到本地业务/远程调用/引用/工作流；无敏感字段采集；告警经故障注入验证；每一门未达标不能扩灰度。
- **验证命令**：`uv run pytest tests/test_metrics.py tests/test_audit_config.py -q`；`bash scripts/ci/smoke-youdoogo.sh`（按现有环境变量）；`git diff --check`。
- **回滚**：关闭新增 exporter 或采样，不关掉安全审计；保留聚合指标。
- **风险**：高基数 business ID 导致成本/可用性问题；仅使用 hash、采样和受控 label。

### 分阶段交付门

| 门 | 允许交付 | 必须同时满足 | 不满足时动作 |
|---|---|---|---|
| G0 | 合并立即实施地基 | T0.1–T0.7 测试、配置无密钥、无流量切换 | 保持 local/local read/旧认证。 |
| G1 | `llm_api` 影子 | T1.1 双凭证/预算/SSE 合同全绿，T1.2 故障测试通过 | 停留 shadow，不能 remote。 |
| G2 | Wiki 低敏只读 | T2.1 ACL 前置与 provenance 合同全绿，T0.7 注入测试通过 | 停留 local/dual-read 对账。 |
| G3 | 受控发布及库级主读 | T2.2 幂等、DLQ、撤回、对账通过；T2.3 指定库迁移达标 | 停 worker、库级回 local。 |
| G4 | Lodge SSO 切换 | T3.1–T3.4 audience/status/revoke/前端存储测试通过，旧 token 使用率可观测 | 仅时间盒 break-glass 回旧入口。 |
| G5 | 最终退役 | T5.1/T5.2 盘点为零、回滚窗口结束、变更批准 | 延长保留期，不删除旧数据。 |

## 7. Epic 5 — 最终退役（不得提前执行）

### T5.1 [P1｜最终退役｜依赖 G1、G4、至少两个稳定发布周期] 本地模型控制面退役

- **目的**：移除生产日常模型选择、Provider 密钥和进程内 fallback，使选模/预算/健康完全归 `llm_api`。
- **真实文件/符号**：`app/llm/roles.py:get_llm_for_role`，`app/llm/factory.py`，`app/llm/fallback.py:FallbackChatModel`，`app/api/v1/ai_providers.py:router`，`app/models/ai_provider.py:AiProvider`，`frontend/src/pages/AiProviders.tsx`。
- **具体改动**：先只读归档 Provider 卡片与使用审计，验证所有 production purpose 已 remote；删除普通 provider CRUD/测试/卡片 composition 和本地 fallback 链。若保留 `LocalEmergencyAdapter`，必须编译期与运行时隔离、默认关闭、非敏感非生产、双人批准、自动过期并留审计；业务代码仍不指定模型名。
- **依赖**：G1 之后 remote 已覆盖全部目标 purpose；T4.2 的回滚演练；密钥轮换/销毁批准。
- **验收标准**：生产代码无 direct provider credential、无业务 `get_llm_for_role` 调用、无普通 `AiProvider` 管理入口；远程拒绝不触发本地模型；密钥销毁有证据。
- **验证命令**：`rg -n "get_llm_for_role|FallbackChatModel|AI_PROVIDER|DASHSCOPE_API_KEY|ZHIPU_API_KEY" app frontend tests`（结果只允许显式迁移/应急豁免）；`uv run pytest tests/test_architecture_boundaries.py tests/test_model_gateway_seam.py -q`。
- **回滚**：不恢复旧密钥/自动 fallback；仅按 T4.2 的短期受审批 emergency 方案处置。
- **风险**：提前删除使下游故障不可恢复；以稳定周期、演练和密钥销毁清单作为硬门。

### T5.2 [P1｜最终退役｜依赖 G3、G4、T4.1] 本地共享知识路径和旧认证退役

- **目的**：完成已批准共享材料的远程主读与 Lodge 认证收口，同时永久保留业务状态和私密记忆边界。
- **真实文件/符号**：`app/models/knowledge.py:KnowledgeVector`，`app/contexts/foundations/knowledge/knowledge_retrieval/infrastructure/sqlalchemy_retrieval.py`，`app/api/deps.py:get_current_user`，`app/api/v1/auth.py:login/refresh/feishu_*`，`app/core/security.py:create_access_token/decode_access_token`。
- **具体改动**：只对已逐库验收的 shared material 停止本地重复索引/主读；保留 personal、工作记忆、未发布业务 evidence 和其访问控制。旧 HS256/password/飞书 handoff 在 sunset date 后删除路由和前端入口；保留数据迁移只读映射与审计查询。不得删除 Proposal、Meeting、Approval、WorkflowRun 或任何 organizational memory 来“完成迁移”。
- **依赖**：G3/G4、T2.3、旧 token 使用率为零并超过公告窗口；数据保留/合规批准。
- **验收标准**：远程主读库都有 mapping/version/ACL 对账；无旧 JWT 可访问 API；私密/业务状态表仍存在且被本地 ACL 保护；所有系统各自拥有身份 schema，只以 Lodge subject 映射，不共享 `users` 表。
- **验证命令**：`uv run pytest tests/test_knowledge_base.py tests/test_memory.py tests/test_auth.py tests/test_access_control_application.py -q`；`cd frontend && npm run test && npm run build`；生产前运行迁移盘点 SQL/只读报告。
- **回滚**：库级恢复 local read、保留已退役认证数据只读；不重启共享 users 写入，也不放宽 Lodge resource-server 校验。
- **风险**：把“共享材料已迁移”扩大为“所有知识和业务数据可删”；退役清单必须逐表/逐库签字，禁止通配删除。

## 8. 建议分支、提交粒度与原装工具链

建议使用短生命周期、可独立回滚的分支（示例）：

1. `feat/llm-foundation-contract-observability`：T0.1、T0.2、T0.5（契约与扩展 migration 分开提交）。
2. `feat/remote-llm-adapter-shadow`：T0.3、T0.4、T1.1–T1.3；真实联调提交不得混入 provider 退役。
3. `feat/wiki-retrieval-provenance-publication`：T0.6–T0.9、T2.1–T2.3；每个 migration、adapter、worker、切流配置独立提交。
4. `feat/lodge-resource-server-projection`：T3.1–T3.4；后端 resource server、投影 migration、前端登录迁移分别提交。
5. `chore/decommission-local-controls`：仅在 G5 后执行 T5.1/T5.2，不与功能开发混合。

每个提交应包含：一个可解释改动、对应测试、配置样例/运维说明（若适用）和回滚开关；禁止在同一提交中同时“启用远程流量 + 删除本地数据/认证入口”。本项目原装验证工具链如下，按改动范围取用并在每个交付门记录输出：

```bash
uv run ruff check app tests
uv run mypy app
uv run pytest
uv run alembic upgrade head
cd frontend && npm run lint && npm run test && npm run build
bash scripts/ci/smoke-youdoogo.sh
git diff --check
```

其中迁移、CCE 部署和 smoke 只可在对应受控环境、具备必要变量时执行；本清单不把缺少外部服务时的失败伪装成应用代码故障。

## 9. 实施前检查清单

- [ ] `llm_api`、`llm_wiki`、Lodge 分别提供版本化契约和 staging endpoint；未实现项仍处于关闭态。
- [ ] 已指定每个 purpose、共享库、认证迁移的 owner、灰度比例、质量/安全阈值和 rollback owner。
- [ ] 不变量评审已确认：业务状态与私密工作记忆不迁移；业务代码不指定模型；身份/ACL/预算拒绝无本地绕过。
- [ ] 已完成备份、迁移演练、Secret 轮换和 status/JWKS/ACL/预算故障注入演练。
- [ ] 仅在对应 G0–G5 门全部通过后扩大流量或执行退役。
