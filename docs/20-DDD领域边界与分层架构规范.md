# 20 · 基础底座域与 DDD 分层架构规范

> 状态：已评审生效，渐进迁移中（2026-07-22）。
> 范围：定义基础底座域、业务域、技术 Platform、Context 内分层、依赖方向和渐进迁移路线。
> 目标形态：模块化单体，不拆微服务，不改变现有 API 与 durable runtime 语义。
> 相关事实源：工作流运行语义以 `docs/14-任务编排层设计.md` 为准；本文负责代码边界和数据所有权。
> 生效规则：本文是后端领域边界、数据所有权、依赖方向和迁移顺序的事实源；`CLAUDE.md` 与
> `docs/05-开发规范手册.md` 已同步。

## 0. 实施状态

本规范按模块化单体渐进落地，不以一次性移动全部文件为验收标准：

| 阶段 | 状态 | 当前结果 |
|---|---|---|
| 阶段 0：边界评审 | 已完成 | Foundation/Business/Platform/Bootstrap 与 Context Map 正式生效 |
| 阶段 1：边界护栏 | 已完成首版 | 新增静态 import boundary test；兼容 facade 仅在仍有历史调用方时保留 |
| 阶段 2：Platform 与 Bootstrap | 进行中 | Bootstrap、Database、Outbox、HTTP Runtime 已落地；旧 `AppError` 调用及异常 facade 已移除 |
| 阶段 3：Capability 与 Connector | 部分开始 | Governed Data Query 的 SQL 护栏已迁入首个真实 Context |
| 阶段 4：Business Context | 部分开始 | Proposal Management 已拥有纯 Domain/Application 错误和 HTTP entrypoint mapper |
| 阶段 5～8 | 待按业务增量执行 | 保持现有 API、表和 durable runtime 语义，逐 Context 迁移 |

迁移期 `app/api/core/models/schemas/services/agents/knowledge/llm/integrations` 中尚有历史入口。新实现必须进入
对应 Context 或 Platform；仍有调用方的旧模块只能向新实现单向 re-export，新模块禁止反向依赖
兼容 facade。旧异常入口的仓库内调用方已迁移完成，因此不再保留 facade。

## 1. 核心结论

项目应分成四类代码边界：

```text
业务场景域
  ↓ 使用稳定业务能力
基础底座域
  ↓ 通过端口使用技术机制
Platform

Bootstrap 负责装配全部模块
```

四类边界的含义：

| 类型 | 回答的问题 | 示例 |
|---|---|---|
| 业务场景域 | 公司正在处理什么业务问题 | 提案、会议、运营分析 |
| 基础底座域 | 多个业务场景共同依赖什么稳定业务能力 | Wiki、专家、Tool、API Connector、Workflow |
| Platform | 这些能力具体如何连接数据库、网络和供应商 | PostgreSQL、Redis、HTTP、MinIO、LLM Gateway |
| Bootstrap | 选择哪些实现并如何启动系统 | FastAPI app、lifespan、worker、handler 注册 |

Wiki、Expert、Tool、Connector/API 都是具有业务语义和生命周期的基础底座域；数据库、HTTP client、Redis、
对象存储只是 Platform 技术实现。

禁止把所有底座能力放进一个 `foundation/common/core` 大包。每个底座 Context 必须有独立的数据所有权、
公开契约和依赖边界。

## 2. 概念定义

### 2.1 业务域组（Business Area）

业务域组只用于导航，例如 `knowledge`、`execution`、`governance`。域组本身不拥有模型、表或 Service，
组内叶子目录才是限界上下文。

### 2.2 限界上下文（Bounded Context）

限界上下文拥有一套明确的语言、模型、规则、数据和公开契约。一个业务对象只能有一个写入所有者。

例如：

- Expert Management 拥有专家生命周期；
- Agent Execution 拥有一次 Agent 执行记录；
- Workflow Runtime 拥有 WorkflowStep 状态；
- Task Management 拥有 TaskCard；
- Capability Execution 拥有 ToolExecution。

它们不能共享一个通用 `Agent/Task/Status` 领域模型。

### 2.3 基础底座域（Foundation Context）

基础底座域是被多个业务场景复用、但仍然具有业务语义的限界上下文。

一个能力满足以下信号中的至少三项时，可以成为基础底座 Context：

1. 有独立 Aggregate、表或写入所有权；
2. 有自己的业务术语、生命周期或状态机；
3. 有独立的权限、失败、重试或审计语义；
4. 被两个以上业务场景消费；
5. 可以用少量稳定 command/query/event 对外服务；
6. 与调用方有不同的变化原因和变化频率；
7. 替换技术实现不应改变它的业务契约。

“很多地方 import”“文件很长”或“可以复用”本身不能证明它是基础域。

### 2.4 Platform

Platform 是无业务语义的技术机制。Platform 可以知道 `URL/timeout/event_type/object_path`，但不能知道：

- 哪个专家可以使用某个 Tool；
- WorkflowStep 什么时候完成；
- 某个提案是否允许通过；
- 某个 Wiki 页面是否对某部门可见。

### 2.5 代码层

每个复杂 Context 内部采用：

```text
contracts       对外发布的稳定语言，按需创建
domain          业务规则、不变量、实体和值对象
application     command/query/use case/ports/事务编排
entrypoints     HTTP、事件、Worker、CLI 等入站适配器
infrastructure  ORM、repository、外部 client 等出站实现
```

简单 Context 可以保持为少量文件，但依赖规则不变。禁止为了目录整齐预建空层。

### 2.6 Shared Kernel

Shared Kernel 是经多个 Context 共同确认的极小稳定契约，不是新的业务 Context，也不是通用业务代码收容所。
当前只包含与传输无关的应用失败分类，不得包含 HTTP status/code、FastAPI、ORM、外部服务类型
或可变领域模型。特定 Context 的业务失败仍应使用本地领域语言，例如 Proposal Management 不使用
通用错误取代自己的提案规则错误。

## 3. 目标目录结构

```text
app/
  bootstrap/
    app.py
    lifecycle.py
    wiring.py

  contexts/
    shared_kernel/
      application_errors.py

    foundations/
      knowledge/
        wiki_management/
        knowledge_indexing/
        knowledge_retrieval/
        semantic_catalog/
        organizational_memory/

      workforce/
        organization_structure/
        expert_management/
        capability_catalog/
        environment_projection/

      execution/
        agent_execution/
        capability_execution/
        work_planning/
        workflow_runtime/
        task_management/
        deliverable_management/

      integration/
        connector_management/
        connector_execution/
        governed_data_query/

      communication/
        assistant_conversations/
        group_messaging/
        collaboration_requests/

      governance/
        identity/
        access_control/
        human_review/
        audit_trail/
        system_configuration/

      ai_operations/
        provider_management/
        usage_budget/
        ai_quality/

    business/
      proposal_management/
      meeting_management/
      operational_analytics/

  platform/
    database/
    outbox/
    http_runtime/
    llm_gateway/
    cache/
    realtime/
    object_storage/
    observability/
    security/
    integrations/
```

`foundations/knowledge` 等域组目录只允许包含子 Context 和说明文档，禁止在域组级创建共享 `service.py`、
`models.py` 或 `domain.py`。

## 4. 基础底座域总表

边界等级：

- **A**：现有代码中已有独立模型、入口、状态或生命周期，应建立独立 Context；
- **B**：先作为强模块隔离，拥有独立 port，达到数据所有权条件后升格为独立 Context。

### 4.1 Knowledge Foundation

| Context | 等级 | 拥有 | 公开能力 |
|---|---|---|---|
| Wiki Management | A | KnowledgeBase、KnowledgeFile、Wiki 页面、版本、范围、机密属性、文档生命周期 | Create/Publish/ArchiveDocument、GetDocument |
| Knowledge Indexing | B | Chunk/Vector 索引 read model、索引版本、重建状态 | IndexDocument、RemoveDocumentIndex |
| Knowledge Retrieval | A | 召回、融合、rerank、引用和检索结果契约 | SearchKnowledge、RetrieveWithCitations |
| Semantic Catalog | B | 业务术语、别名、指标口径和语义映射 | ResolveTerm、ResolveMetric |
| Organizational Memory | B | 记忆条目、来源、提炼、巩固和淘汰策略 | DistillConversation、RecallMemory |

### 4.2 Workforce Foundation

| Context | 等级 | 拥有 | 公开能力 |
|---|---|---|---|
| Organization Structure | A | 部门树、主管、岗位、组织归属和外部组织映射 | GetOrganizationSnapshot、AssignMember |
| Expert Management | A | 专家档案、职责、Prompt 策略、模型策略、知识范围、能力绑定、启停和版本 | GetExpertSnapshot、AssignCapabilities |
| Capability Catalog | A | Skill/Tool 定义、版本、输入输出 schema、风险级别、副作用类型 | ListCapabilities、GetCapabilityDefinition |
| Environment Projection | A | 面向 Agent 的组织/专家/知识/数据源组合快照、版本和失效状态 | GetEnvironmentSnapshot、InvalidateSnapshot |

### 4.3 Execution Foundation

| Context | 等级 | 拥有 | 公开能力 |
|---|---|---|---|
| Agent Execution | A | AgentExecutionRequest/Result、AgentTaskRecord、trace、一次执行协调 | ExecuteAgent |
| Capability Execution | A | CapabilityInvocation、ToolExecution、参数校验、授权、幂等、重放和结果归一 | ExecuteCapability |
| Work Planning | A | WorkIntent、WorkflowPlan、PlanStep、规划策略和计划校验 | PlanWork |
| Workflow Runtime | A | WorkflowRun/Step/Event、DAG 推进、attempt/version/lease、恢复和真人停点 | StartWorkflow、ExecuteStep、ResumeWorkflow |
| Task Management | A | TaskCard、分配、负责人、验收、驳回和任务日志 | CreateTask、AcceptTask、RejectTask |
| Deliverable Management | A | Deliverable、ArtifactVersion、对象路径、下载授权和交付状态 | CreateDeliverable、PublishArtifact |

### 4.4 Integration & Data Foundation

| Context | 等级 | 拥有 | 公开能力 |
|---|---|---|---|
| Connector Management | A | Connector、Endpoint、CredentialRef、归属、启停、能力和健康状态 | RegisterConnector、GetConnectorSnapshot |
| Connector Execution | A | ConnectorInvocation、调用策略、限流语义、标准化响应和调用记录 | InvokeConnector |
| Governed Data Query | A | DataCatalog、QueryRequest、SQL guard、Dataset 和查询访问约束 | QueryDataset、DescribeDataCatalog |

### 4.5 Communication Foundation

| Context | 等级 | 拥有 | 公开能力 |
|---|---|---|---|
| Assistant Conversations | A | 真人与助理的一对一会话、消息、流式响应和归档状态 | SendAssistantMessage、ArchiveConversation |
| Group Messaging | A | Channel、Message、Member、未读、附件消息和群归档状态 | SendGroupMessage、ManageMembers |
| Collaboration Requests | A | 跨部门请求、风险级别、授权通道、确认和复核状态 | CreateCollaborationRequest、ReviewRequest |

### 4.6 Governance Foundation

| Context | 等级 | 拥有 | 公开能力 |
|---|---|---|---|
| Identity | A | SysUser、登录身份、JWT identity、飞书绑定和登录状态 | Authenticate、ResolvePrincipal |
| Access Control | A | ResourceGrant、资源可见性政策和访问决策 | CanRead、CanWrite、GrantAccess |
| Human Review | B | ReviewRequest、reviewer、风险等级、审核结果和超时 | RequestHumanReview、RecordReviewDecision |
| Audit Trail | A | 追加式 actor/action/target/result 审计记录 | AppendAuditRecord、QueryAuditTrail |
| System Configuration | B | 可编辑配置、密钥状态、版本和变更历史 | ResolveConfig、UpdateConfig |

Human Review 只拥有“审核请求”的生命周期，不拥有来源业务对象。审核通过后，来源 Context 必须重新校验自己的
状态和不变量，再决定是否生效。

### 4.7 AI Operations Foundation

| Context | 等级 | 拥有 | 公开能力 |
|---|---|---|---|
| Provider Management | A | Provider 卡片、模型档位、主备关系、启停、凭据密文和连通性状态 | GetModelRoute、ManageProvider |
| Usage & Budget | A | LLM 用量、成本归因、部门/用户预算和超限政策 | AuthorizeUsage、RecordUsage |
| AI Quality | B | EvalCase、评分、反馈、影子评估、反思和提示词候选验证 | RunEvaluation、RecordFeedback |

## 5. 关键底座域的边界

### 5.1 Wiki/Knowledge

Wiki Management 与 Retrieval 必须分开：

```text
Wiki Management
  → DocumentPublished event
Knowledge Indexing
  → IndexReady event
Knowledge Retrieval
  → SearchResult + Citations
```

职责边界：

- Wiki Management 决定文档是否存在、是否发布、属于哪个知识空间、谁可见；
- Knowledge Indexing 负责把已发布文档转换成可检索索引；
- Knowledge Retrieval 负责查询、召回、排序和引用；
- Access Control 提供访问决策，但不拥有知识文档；
- Agent Execution 只调用 `KnowledgeSearchPort`，不得直接 import 检索实现。

Knowledge Indexing 暂时可以是 Wiki Management 内的强模块，但必须独立 port 和测试，不能与上传接口、
文档 CRUD、搜索算法混成一个 Service。

### 5.2 Expert

Expert Management 是专家业务资产的唯一所有者：

```text
Expert
  ├─ identity/profile
  ├─ organization assignment
  ├─ duty and prompt policy
  ├─ model policy
  ├─ capability bindings
  ├─ knowledge scope
  └─ version/status
```

Expert Management 对外提供不可变执行快照：

```text
ExpertExecutionSnapshot
  expert_id
  expert_version
  role_and_duty
  system_prompt
  model_policy
  capability_ids
  tool_permissions
  knowledge_scope
```

规则：

- Workflow Runtime 只保存 `expert_id + snapshot/version`；
- Agent Execution 只消费快照，不读取 `AgentRole` ORM；
- Capability Catalog 拥有 Tool/Skill 定义，Expert 只保存 capability ID 和授权策略；
- 专家更新后不得改变历史 Workflow 的执行语义。

### 5.3 Capability Catalog 与 Tool 调用

Tool 不是一段 Python 函数，也不等于外部 API。Tool 是面向 Agent 的稳定业务能力契约。

Capability Catalog 定义：

```text
CapabilityDefinition
  capability_id
  version
  name
  description
  input_schema
  output_schema
  risk_level
  side_effect_type
  required_permissions
  handler_key
```

Capability Execution 执行：

```text
Agent Execution
  → CapabilityRequest
Capability Execution
  → 查 CapabilityDefinition
  → 校验 ExpertSnapshot 授权
  → 校验参数和风险策略
  → 建立 ToolExecution 幂等记录
  → 调目标 Context port
  → 保存结果或错误
  → 返回 CapabilityResult
```

具体 Tool 的业务逻辑必须留在目标 Context：

| Tool | 目标 Context |
|---|---|
| `search_wiki` | Knowledge Retrieval |
| `query_business_data` | Governed Data Query |
| `call_external_api` | Connector Execution |
| `generate_report` | Deliverable Management |
| `request_colleague` | Collaboration Requests |

Capability Execution 只负责目录查找、参数校验、授权、幂等和分发，不拥有 Wiki、数据查询、交付或协作规则。

### 5.4 Connector/API 调用

API 调用必须分为业务配置和技术传输：

```text
Connector Management         业务底座
  - 调用哪个外部系统
  - Endpoint 和能力是什么
  - 使用哪个 CredentialRef
  - 谁可调用
  - 是否启用
  - 健康状态

Connector Execution          业务底座
  - 调用策略和限流语义
  - 输入输出映射
  - 供应商错误归一
  - 调用记录

Platform HTTP Runtime        技术底座
  - DNS/TLS/HTTP
  - timeout/retry
  - connection pool
  - request/response bytes
```

标准链路：

```text
Capability Execution
  → ConnectorInvocation
Connector Execution
  → ConnectorSnapshot
  → Credential Resolver port
  → Platform HTTP Runtime
  → External API
  → 标准化 ConnectorResult
```

禁止让 Tool handler 自行拼 URL、读取环境变量、注入密钥或直接返回供应商 SDK 对象。

### 5.5 Agent Execution

Agent Execution 负责一次 Agent 调用的完整协调，但不拥有专家、工作流或 Tool 业务规则。

```text
AgentExecutionRequest
  expert_snapshot
  execution_trace
  task_input
  conversation_context
  knowledge_context

AgentExecutionResult
  status
  content
  capability_requests/results
  usage
  sources
  error
```

建议把当前 `ExecutionContext` 拆成：

- `ExecutionTrace`：workflow/step/attempt/trace/principal 等纯数据；
- `ExecutionPorts`：LLM、Knowledge、Capability、Usage、Clock 等依赖；
- `AgentExecutionRequest`：本次执行输入；
- `AgentExecutionResult`：稳定输出。

Agent Execution 不接收 `AsyncSession`、`AgentRole ORM` 或 FastAPI Request。

### 5.6 Work Planning 与 Workflow Runtime

两个 Context 不能继续混为一个 Workflow Service：

```text
Work Planning
  WorkIntent → WorkflowPlan

Workflow Runtime
  WorkflowPlan → WorkflowRun/WorkflowStep
  → claim/lease/attempt
  → Agent Execution
  → state transition/recovery
```

Work Planning 拥有计划语义，Workflow Runtime 拥有 durable execution 语义。未来 LangGraph 只能实现 Planning 或
WorkflowEngine adapter，不能成为第二套状态真相源。

### 5.7 Task Management 与 Human Review

Task Management 拥有 TaskCard 的人机协同生命周期。Workflow Runtime 拥有 WorkflowStep 的执行生命周期。

```text
WorkflowProgressed
  → Task Management projection
  → TaskCard reported

Human accepts TaskCard
  → TaskAccepted event
  → WorkflowRuntime.AcceptHumanStep
  → Runtime 再次验证 waiting_human
```

Human Review 可统一承载审核请求、审核人、风险等级和决定记录，但不能直接把 Proposal、Meeting、Task 或 Workflow
改成成功状态。业务生效动作始终由来源 Context 执行。

## 6. 业务场景域

当前已经形成的业务场景 Context：

| Context | 拥有 | 使用的基础底座 |
|---|---|---|
| Proposal Management | 提案、评审、通过/驳回和转执行意图 | Expert、Agent、Knowledge、Human Review、Work Planning |
| Meeting Management | 会议、议题、参会、投票、纪要和真人决议 | Expert、Agent、Knowledge、Human Review、Work Planning |
| Operational Analytics | 运营指标、异常事实、趋势和分析口径 | Connector、Data Query、Semantic Catalog、Agent、Deliverable |

未来销售、研发、财务、HR 等真实业务流程出现独立规则、数据和生命周期后，再建立对应业务 Context；不能仅因
存在一个部门或专家角色就预建空领域。

以下内容不是业务 Context：

- Desktop/Dashboard：工作台组合入口；
- FastAPI API：传输入口；
- Feishu/ThinkingData client：Platform integration；
- LLM provider SDK：Platform adapter；
- 通用页面、DTO、ORM Base。

## 7. 核心 Context Map

```text
Proposal Management ─┐
Meeting Management  ─┼─command/event→ Work Planning
Assistant Conversation┘

Work Planning ──WorkflowPlan──→ Workflow Runtime
Workflow Runtime ──query──────→ Expert Management
Workflow Runtime ──command────→ Agent Execution

Agent Execution ──query───────→ Knowledge Retrieval
Agent Execution ──authorize───→ Usage & Budget
Agent Execution ──command─────→ Capability Execution

Capability Execution ──query──→ Capability Catalog
Capability Execution ──command→ Connector Execution
Capability Execution ──command→ Governed Data Query
Capability Execution ──command→ Deliverable Management
Capability Execution ──command→ Collaboration Requests

Workflow Runtime ──progress event──→ Task Management
Task Management ──accepted event───→ Workflow Runtime

Organization Structure ──changed event──→ Expert Management
Identity ──Principal──→ Access Control
Access Control ──decision──→ 各 Context Entrypoint/Application

Wiki Management ──published event──→ Knowledge Indexing
Knowledge Indexing ──ready event────→ Knowledge Retrieval
Conversation/Group Messaging ──archive event──→ Organizational Memory

Provider Management ──route snapshot──→ Platform LLM Gateway
Agent Execution ──usage event──────────→ Usage & Budget
Agent Execution ──quality sample───────→ AI Quality
```

箭头表示 command/query/event 契约，不表示允许直接 import 对方内部模块。

## 8. Context 内分层定义

### 8.1 Contracts

职责：当前 Context 对其他 Context 发布的稳定语言。

可以包含：

- 不可变 command/query/result DTO；
- integration event；
- facade/protocol；
- ID、版本和快照。

禁止包含：

- ORM、`AsyncSession`；
- FastAPI Request/Response；
- Context 内部 Entity；
- SQL、HTTP client、供应商 SDK；
- 调用者必须理解的内部执行步骤。

只有存在真实消费者时才创建 Contracts。

### 8.2 Domain

职责：实体、值对象、Aggregate、不变量、业务状态机和领域事件。

依赖规则：

```text
domain → 标准库 + 当前 Context domain
domain ─X→ application / entrypoints / infrastructure / platform / 其他 Context
```

禁止 I/O、数据库操作、环境变量、HTTP、LLM 和供应商类型。

### 8.3 Application

职责：一个明确用例的编排、端口定义、事务边界和 domain event 到 integration event 的转换。

典型用例：

```text
PublishWikiDocument
GetExpertExecutionSnapshot
ExecuteCapability
InvokeConnector
ExecuteAgent
PlanWork
StartWorkflow
AcceptTask
RequestHumanReview
```

Application 定义自己需要的 port，Infrastructure 实现。Application 禁止 import ORM、具体 Repository、FastAPI
和供应商 client。

### 8.4 Entrypoints

职责：把 HTTP、SSE、消息、Worker、CLI 输入转换成 command/query，并映射输出和错误。

标准形状：

```text
解析输入 → 身份/参数校验 → 构造 command → 调用一个主要 use case → 映射输出
```

Entrypoint 禁止直接查询 Repository、执行 SQL、调用 LLM 或包含业务状态机。

### 8.5 Infrastructure

职责：实现 Repository、Gateway、Clock、EventPublisher、ObjectStorage 等 application port。

可以依赖 SQLAlchemy、Redis、MinIO、httpx 和 Platform；禁止包含核心业务决策，禁止返回 ORM/SDK 对象给内层。

### 8.6 Bootstrap

职责：对象创建、依赖注入、route/handler 注册、lifespan、worker 启停和资源释放。

Bootstrap 是唯一允许同时认识多个 Context 和具体 Infrastructure 的位置，高 fan-out 属于正常现象。

## 9. 依赖规则

### 9.1 Context 内

```text
Entrypoints ─→ Application ─→ Domain
Infrastructure ─────────────→ Application Ports / Domain
Bootstrap ──────────────────→ 全部外层实现
```

### 9.2 Context 间

同步查询默认形状：

```text
调用方 Application
  → 调用方定义的 Port
  → Adapter
  → 被调用方 Contracts/Facade
```

异步协作默认形状：

```text
业务状态 + Outbox 同事务提交
  → Platform Outbox Worker
  → Bootstrap 注册的业务 Handler
  → 下游 Application Use Case
```

### 9.3 数据所有权

1. 一个业务对象只有一个写入 Context；
2. 其他 Context 只保存 ID、不可变快照或自己的 read model；
3. 禁止跨 Context 直接更新对方表；
4. 禁止跨 Context 传递 ORM 或共享可变 Entity；
5. 跨 Aggregate/Context 默认最终一致；
6. 事件消费者必须处理重复、延迟、乱序和版本兼容。

### 9.4 Platform 依赖

```text
Bootstrap → Context + Platform
Context Infrastructure → Platform
Platform → 第三方技术库

Platform ─X→ 任何业务 Context
Domain/Application ─X→ Platform 具体实现
```

业务 handler 由 Bootstrap 注册到 Outbox/Realtime registry，Platform 不得反向 import 业务模块。

## 10. 事务与可靠性

### 10.1 普通短事务

```text
Application Use Case
  → load Aggregate
  → domain behavior
  → save Aggregate
  → append Outbox
  → commit
```

Repository 默认 `flush`，完整用例的 commit 由 UnitOfWork/Application 决定。

### 10.2 LLM、Tool、API 长调用

```text
事务 1：claim/lease/ToolExecution pending → commit
事务外：LLM / Tool / HTTP / object storage
事务 2：校验 owner/version/attempt → 保存结果和后续事件 → commit
```

禁止在等待外部 I/O 时持有长数据库事务。

### 10.3 Outbox

Platform Outbox 只拥有：

- event 存储；
- claim、lease、retry、defer、dead-letter；
- dedupe key；
- handler registry 和分发机制。

Outbox 不得使用 Workflow 专属 `StepExecutionDisposition`，应使用通用结果：

```text
Completed
Deferred(available_at, reason)
RetryableFailure(error)
TerminalFailure(error)
```

## 11. 当前文件目标归属

| 当前文件/职责 | 目标 Context/Platform | 说明 |
|---|---|---|
| `models/knowledge.py`、`knowledge_base_service.py` | Wiki Management | Wiki/文档模型和生命周期 |
| `knowledge/ingest.py`、`chunk.py`、`embedding.py` | Knowledge Indexing | 索引构建和重建 |
| `knowledge/retrieval.py`、`rerank.py` | Knowledge Retrieval | 检索和引用契约 |
| `semantic_service.py` | Semantic Catalog | 术语、别名和指标口径 |
| `memory_service.py` | Organizational Memory | 消费归档事件生成记忆 |
| `agent_role_service.py`、`AgentRole ORM` | Expert Management | 专家业务模型与 ORM 分离 |
| `skill_registry.py` | Capability Catalog | 能力定义、schema、风险和版本 |
| `tool_dispatcher.py`、`ToolExecution` | Capability Execution | 授权、幂等、调度和执行记录 |
| `agents/base.py::run_agent` | Agent Execution | 输入输出改为纯 DTO，不接收 Session/ORM |
| `agents/contracts.py::ExecutionContext` | Agent Execution | 拆为 Trace、Request、Result、Ports |
| `workflow_planning.py` | Work Planning | 输出 WorkflowPlan |
| `workflow_repository.py` | Workflow Runtime application + infrastructure | 用例编排与持久化分开 |
| `workflow_state.py` | Workflow Runtime domain + application | 状态规则与 lease 协调分开 |
| `workflow_step_executor.py` | Workflow Runtime application | 通过 AgentExecutionPort 执行 |
| `workflow_projection.py` | Workflow Runtime query + Task projection | 按写入所有权拆分 |
| `workflow_event_handler.py` | Workflow Runtime entrypoint | 通用 lease/retry 移到 Platform Outbox |
| `workflow_worker.py` | Bootstrap + Platform Outbox facade | 生命周期和轮询机制分开 |
| `task_service.py`、`models/task.py` | Task Management | 状态规则移入 domain |
| `deliver_service.py`、`models/deliverable.py` | Deliverable Management | 文件业务生命周期 |
| `data_source_service.py` | Connector Management | DataSource 演进为 Connector 元数据 |
| `connectivity_service.py` | Connector Management/Execution | 健康语义与网络实现分开 |
| `data_query_service.py`、`data_catalog_service.py`、`sql_guard.py` | Governed Data Query | 查询和 SQL 护栏 |
| `integrations/feishu/*`、`thinkingdata/client.py` | Platform Integrations | 底层供应商 client |
| `desktop_chat_service.py`、`desktop_chat_repository.py` | Assistant Conversations | 工作台聚合与会话数据分开 |
| `discussion_service.py` | Group Messaging | 频道、消息、成员、未读 |
| `realtime_service.py` | Group Messaging adapter + Platform Realtime | 群语义与 Redis 机制分开 |
| `collab_service.py` | Collaboration Requests | 跨部门请求和复核 |
| `org_service.py`、`org_template.py`、`org_sync_service.py` | Organization Structure | 组织模型；飞书 client 在 Platform |
| `auth_service.py`、`feishu_login.py` | Identity | 身份和飞书登录映射 |
| `permission_service.py`、`resource_grant_service.py` | Access Control | 资源访问政策 |
| `audit_service.py` | Audit Trail | 追加式审计记录 |
| `config_service.py`、`runtime_config.py` | System Configuration + Platform Config | 可编辑配置语义与读取机制分开 |
| `ai_provider_service.py` | Provider Management | Provider 卡片和路由快照 |
| `llm/factory.py`、`fallback.py`、`health.py` | Platform LLM Gateway | 模型调用实现 |
| `llm/usage.py`、预算共享状态 | Usage & Budget | 用量政策与供应商 usage 解析分开 |
| `eval_service.py`、`feedback_service.py`、`reflection_service.py` | AI Quality | 评估和反馈闭环 |
| `environment_service.py` | Environment Projection | 事件失效的组合 read model |
| `proposal_service.py` | Proposal Management | 提案业务场景 |
| `meeting_service.py`、`meeting_ai_actions.py` | Meeting Management | 会议规则与 Agent adapter 分开 |
| `ops_data.py`、`anomaly.py` | Operational Analytics | 运营业务事实和异常 |
| `outbox_service.py` | Platform Outbox | 不包含任何业务 handler |
| 稳定应用失败分类 | Shared Kernel | 不携带 HTTP 元数据；特定业务错误留在所属 Context |
| 应用失败到 HTTP envelope 的映射 | Bootstrap / Context Entrypoint | 全局分类由 Bootstrap 映射，Context 特定错误由自己的 HTTP adapter 映射 |

## 12. 禁止规则

以下规则应逐步由边界测试强制：

1. Domain 禁止 import FastAPI、Pydantic HTTP schema、SQLAlchemy、Redis、httpx；
2. Application 禁止 import ORM、具体 Repository、供应商 client；
3. Context A 禁止 import Context B 的 domain/application/infrastructure；
4. Context 间只能通过本地 port、对方 contracts/facade 或 integration event；
5. Platform 禁止 import 任何 Context；
6. ORM model 禁止 import service/application；
7. Entrypoint/Worker 禁止绕过 Application 直接调用 Repository；
8. Tool handler 禁止直接拼 URL、读取密钥或修改其他 Context ORM；
9. Workflow Runtime 禁止直接读取 Expert ORM 或调用具体 Tool 实现；
10. Agent Execution 禁止直接修改 WorkflowStep；
11. Capability Execution 禁止承载 Wiki、查询、交付、协作的业务逻辑；
12. 禁止新增无所有权的 `common/shared/utils/base/service` 业务模块；
13. 兼容 facade 只允许旧入口使用，新模块禁止反向 import facade；
14. 业务域组目录禁止放共享 Service、Entity 和 Repository。
15. Shared Kernel 禁止依赖 Framework、Platform 或外层兼容入口，禁止放入 Context 特定规则。

## 13. 测试分层

| 测试 | 验证 | 真实依赖 |
|---|---|---|
| Domain unit | 不变量、状态转换和值对象 | 无 |
| Application use case | 编排、端口、事务结果 | fake ports/UoW |
| Contract test | DTO/event 兼容和 adapter 翻译 | 可选序列化器 |
| Infrastructure integration | ORM、并发、外部协议 | DB/mock server |
| Entrypoint test | 参数、身份、错误和传输映射 | FastAPI client |
| Architecture boundary | import 方向、循环和禁用依赖 | 静态分析 |
| End-to-end | 少量关键闭环 | 完整环境 |

边界测试至少覆盖：

- Domain/Application 不依赖 FastAPI、SQLAlchemy 和 Platform 实现；
- Platform 不依赖 Context；
- Context 不跨域 import 内部模型；
- Expert/Agent/Capability/Workflow 四条边界；
- Environment Projection 不被来源 Context 反向调用；
- 新模块不反向 import 兼容 facade。
- Shared Kernel 无 Framework、Platform 和外层依赖；已删除的异常 facade 不得回归。

## 14. 渐进迁移路线

### 阶段 0：评审基础底座 Context

先确认：

1. Wiki Management、Indexing、Retrieval 是否按三个职责隔离；
2. Expert Management 与 Capability Catalog 是否分开；
3. Capability Catalog 与 Capability Execution 是否分开；
4. Connector Management、Connector Execution、HTTP Runtime 是否三层分开；
5. Work Planning 与 Workflow Runtime 是否分开；
6. Human Review 是否先作为 B 级候选 Context；
7. Desktop 是否只作为组合入口。

通过后更新 `CLAUDE.md` 和 `docs/05`。

### 阶段 1：建立边界护栏

- 增加 import boundary test；
- 禁止新增跨层和跨 Context 依赖；
- 仅在仓库内外仍有调用方时保留现有路径作为兼容 facade。

异常子迁移已完成：历史 `AppError` 构造点已替换为 Shared Kernel 或所属 Context 的具体错误，
`app.core.application_error` 与 `app.core.exceptions` 已删除，HTTP 契约由 Bootstrap/Entrypoint 适配并由契约测试锁定。

### 阶段 2：提取 Platform Outbox 与 Bootstrap

- 保持表、事件和 worker 行为不变；
- 通用 claim/lease/retry/defer 进入 Platform；
- Workflow/Discussion 等业务 handler 留在 Context；
- lifecycle 和 handler registry 进入 Bootstrap。

### 阶段 3：提取 Capability 与 Connector 底座

- `skill_registry` 形成 Capability Catalog；
- `ToolDispatcher/ToolExecution` 形成 Capability Execution；
- DataSource 形成 Connector Management；
- HTTP/Feishu/ThinkingData client 保留在 Platform；
- Tool handler 改为调用目标 Context port。

### 阶段 4：拆分 Expert 与 Agent Execution

- `AgentRole` 业务含义迁入 Expert Management；
- 定义版本化 ExpertExecutionSnapshot；
- `run_agent` 改为纯 Request/Result；
- 拆分 ExecutionTrace 与 ExecutionPorts。

### 阶段 5：拆分 Planning、Runtime 与 Task

- 提取 `PlanWork`、`StartWorkflow`、`ExecuteWorkflowStep`；
- Planning 只输出 WorkflowPlan；
- Runtime 只负责 durable execution；
- TaskCard 转为 Task Management 投影；
- 旧 `/tasks/{id}/run` 进入 durable Runtime。

### 阶段 6：拆分 Wiki/Knowledge

- KnowledgeBase/File 迁入 Wiki Management；
- ingest/index 通过 DocumentPublished event 驱动；
- Retrieval 通过稳定 query port 暴露；
- Semantic Catalog 和 Memory 先作为 B 级模块隔离。

### 阶段 7：治理与沟通底座

- Identity、Access Control、Audit 分离；
- Environment 改为事件失效 projection；
- Assistant Conversation、Group Messaging、Collaboration Requests 分离；
- 评估是否升格 Human Review。

### 阶段 8：业务场景迁移与清理

- 迁移 Proposal、Meeting、Operational Analytics；
- 删除旧横向 `app/services/models/schemas` 入口；
- 删除兼容 facade；
- 按实际业务需求新增部门业务 Context，不预建空壳。

## 15. 评审验收清单

1. 基础底座域和纯技术 Platform 是否已明确分开；
2. Wiki、Expert、Tool、API 是否有独立数据所有权和公开契约；
3. Tool 是否被定义为业务能力，而不是 Python 函数或 HTTP API；
4. Connector/API 配置、调用语义和 HTTP 传输是否分开；
5. Expert 是否只绑定 capability ID，不拥有 Tool 实现；
6. Agent Execution 是否不接收 Session/ORM；
7. Capability Execution 是否不承载目标业务逻辑；
8. Work Planning 与 Workflow Runtime 是否分开；
9. TaskCard 是否归 Task Management；
10. Outbox 是否归 Platform，业务 handler 是否归各 Context；
11. Human Review 是否只协调审核，不直接修改来源业务状态；
12. Context 间是否只通过 port/contracts/event 协作；
13. 是否以模块化单体渐进迁移，不拆微服务；
14. 是否停止向横向 `app/services` 大平铺继续增加新业务代码。

## 16. 最终判断标准

架构是否有效，不看目录数量，而看：

- 一个业务事实是否只有一个写入所有者；
- 一次业务变化是否主要限制在一个 Context；
- 调用方是否只理解稳定契约，不理解内部步骤；
- Tool/API/LLM/DB 等技术细节是否被隐藏；
- 核心规则是否可在无数据库、无网络、无框架条件下测试；
- 新模块是否隐藏了复杂度，而不是增加透传和跳转；
- 基础底座是否真正被多个业务场景复用，同时保持独立语言和生命周期。
