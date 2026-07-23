## Context

`modularize-runtime-hotspots` 已把 Workflow Worker、技能调度和部分大文件拆成职责更明确的模块，但拆分主要发生在原有横向目录内部。当前业务行为仍集中在 `app/services`、`app/models`、`app/agents` 和 `app/knowledge`，由此产生四类系统性问题：

- 全应用仍存在 import 强连通分量；包级 `__init__` 重导出、Service 互调和局部 import 让依赖方向难以判断。
- `AsyncSession`、ORM Entity、具体 Agent/Tool 实现和事务提交穿过业务边界，调用者必须理解被调用方内部步骤。
- Workflow、Task、Agent、Capability、Environment 等 Context 共享状态或互相修改对方数据，数据所有权和失败边界不清。
- HTTP 入口和前端页面同时承担传输、业务编排、状态和副作用管理，局部修改容易扩散到多个层次。

`docs/20-DDD领域边界与分层架构规范.md` 已定义目标结构：模块化单体内以叶子 Bounded Context 拥有模型和写入数据，Context 内遵循 `Entrypoints → Application → Domain`，Infrastructure 实现 Application 定义的 port，Bootstrap 是唯一组合根，跨 Context 通过纯契约、调用方 port 或 integration event 协作。本设计说明如何在不一次性重写系统的前提下，把现有横向实现迁入该结构。

本变更使用 P0～P4 作为实施批次；它们是 docs/20 渐进迁移路线的工程编排，不重新定义其中的领域边界：

| 批次 | 主要结果 | 对应 docs/20 路线 |
|---|---|---|
| P0 | 全局依赖护栏、循环清零、Environment Projection 解环 | 阶段 1、2、6 的前置治理 |
| P1 | Proposal Management 首个完整纵向切片 | 阶段 8 的参考实现 |
| P2 | Capability、Expert/Agent、Planning/Workflow/Task 执行底座纯契约化 | 阶段 3～5 |
| P3 | Knowledge、Identity/Organization、Communication、Meeting、Operational Analytics 等逐 Context 迁移 | 阶段 6～8 |
| P4 | HTTP 薄入口和前端 feature 化，删除已无调用方的兼容入口 | 阶段 7、8 的入口收口 |

约束如下：

- 保持现有公开 HTTP 路由、响应 envelope、数据库表名和 durable runtime 语义；需要 schema 变更时必须另建 change。
- PostgreSQL WorkflowRun/WorkflowStep、transactional outbox、租约、attempt、幂等和真人停点继续是唯一运行真相源。
- 继续支持当前 Python/FastAPI/SQLAlchemy async 技术栈和 SQLite 测试路径。
- AI 仅有建议、分析和辅助执行权；高风险业务动作必须保留权限、审批和真人确认。
- 共享工作区会由多个代理并发修改；每个迁移单元必须有排他的文件所有权，并把中央组合根修改串行交给集成人。

主要利益相关者包括后端 Context 维护者、Workflow/Worker 运维者、HTTP 与前端维护者、测试/发布负责人，以及依赖现有 API 和 TaskCard 交互的用户。

## Goals / Non-Goals

**Goals:**

- 将全应用 import 循环降为零，并用自动化边界测试阻止回归。
- 让每个业务事实只有一个写入 Context，跨 Context 只交换 ID、不可变快照、纯 DTO 或 integration event。
- 让 Domain/Application 不依赖 FastAPI、SQLAlchemy、具体 Repository、Platform 实现或旧横向 facade。
- 用 Context 自有 Repository port 和 Unit of Work 明确事务所有权，消除 Service 内散落的 `commit/rollback`。
- 将 Environment Projection 改造成消费来源事件并组合只读快照的下游 Context，消除来源 Service 对它的反向调用。
- 建立纯 Agent、Capability、Planning、Workflow 和 Task 契约，同时保留 durable execution、幂等和人工停点。
- 以 Proposal Management 为参考完成纵向切片，并把同一迁移方法逐步应用到 P3 业务和底座 Context。
- 让旧模块成为单向、可删除的兼容 facade；在调用方迁完后删除，而不是永久形成第二套架构。
- 让 HTTP 入口只负责传输映射，让前端状态和副作用由业务 feature 拥有。
- 支持多个代理按排他文件集并发交付，并通过阶段性集成门禁保持主干始终可验证。

**Non-Goals:**

- 不把模块化单体拆成微服务，不引入新的数据库、消息队列或分布式事务框架。
- 不重写 PostgreSQL durable runtime，不用 LangGraph、Celery 或 Temporal 替代其状态、租约或 Outbox。
- 不进行数据库表重命名、历史数据搬迁或公开 API 版本升级。
- 不一次性删除所有 `app/services`、`app/models`、`app/schemas` 等旧路径；删除以真实调用方清零为条件。
- 不把所有 Context 预建为空目录，也不创建 `common/core/shared` 业务收容包。
- 不在结构迁移中顺带改变业务规则、UI 交互或错误语义；发现行为缺陷时单独记录和修复。
- 不以文件行数或目录数量作为成功标准；边界、依赖方向、事务和数据所有权才是验收依据。

## Decisions

### 1. 采用“纵向绞杀切片”，不做一次性目录搬迁

每个迁移单元必须覆盖一个可调用的完整用例：契约、Domain/Application、所需 port、Infrastructure adapter、Entrypoint、旧 facade 和测试。迁移顺序固定为：

1. 为旧行为补 characterization test，锁定成功、失败、权限、事务和响应语义。
2. 在目标 Context 定义 Published Language、use case 与调用方所需 port。
3. 在新 Context 内实现 Domain/Application，并用 fake port/UoW 通过测试。
4. 增加 Infrastructure adapter，复用现有表和外部系统，不改变物理数据所有权。
5. 让旧 Service/API 委托新 use case，一次只保留一个写路径。
6. 逐个迁移内部调用方到纯契约或本地 port。
7. 调用方清零后删除 facade，并收紧架构测试。

选择纵向绞杀是因为它允许每次迁移都有独立业务验收点，并能随时回到旧实现。单纯把文件从 `app/services` 移到 `app/contexts` 不会消除 ORM、事务和跨 Context 调用；一次性重写则会同时改变太多行为，无法可靠回滚。

每个切片只有一个 active writer。迁移期不允许旧 Service 和新 use case 双写同一业务对象；需要兼容读取时可以并存 read adapter，但写入路由必须由 Bootstrap 或旧 facade 明确选择一个实现。

### 2. P0 用全局依赖图和禁止边建立可执行护栏

架构测试对 `app` 下的 Python 模块构建静态 import 图，将包导入解析到规范模块名，并计算强连通分量。P0 采用两步门禁：

- 首先记录当前强连通分量及其明确 owner，测试禁止新增节点或扩大既有循环。
- 修复 Agent、Knowledge、Environment 等现存循环后，把门禁切换为“除单节点外不得存在强连通分量”，并删除临时清单。

同时增加分层和路径规则：

- `domain` 不得 import Application、Entrypoint、Infrastructure、Platform、ORM 或 Web 框架。
- `application` 不得 import ORM、具体 Repository、FastAPI、供应商 client 或旧横向 facade。
- Context A 不得 import Context B 的 Domain/Application/Infrastructure；只能使用公开 contracts/facade，或通过调用方 port 由 Bootstrap 适配。
- Platform 不得 import Context；新 Context 不得 import `app/services`、`app/models`、`app/agents`、`app/knowledge` 等兼容实现。
- Context 内部模块不得反向 import 自己的旧 facade。
- 包 `__init__` 仅发布稳定契约或保持为空；禁止通过 eager re-export 导入完整运行图。运行代码直接导入叶子模块。

测试只忽略 `TYPE_CHECKING` 下不参与运行时的导入；函数内 import 仍计入依赖图，不能用局部 import 隐藏循环。确需过渡豁免时必须精确到 `source → target`、标注 owner 和删除批次，P0 结束时不保留循环豁免。

选择全应用图而不是只检查少数子目录，是因为局部无环不能阻止循环穿过 `services → agents → contexts → services`。选择静态测试而不是仅依赖 Graphify/人工评审，是为了让同一规则进入每次提交的质量门禁。

### 3. 兼容 facade 只能是单向适配器，并以调用方清零为删除条件

旧 `app/services`、`app/api`、`app/models`、`app/schemas`、`app/agents` 和 `app/knowledge` 路径按实际兼容需要保留，但 facade 必须满足：

- 只做 re-export、参数/结果翻译或向一个主要 use case 的委托。
- 不包含领域分支、SQL、ORM 查询、跨 Service 编排、`commit/rollback` 或外部 I/O。
- 新 Context、Platform 和 Bootstrap 之外的新代码禁止 import facade。
- 同一 facade 及其目标 Context 由同一个迁移 owner 修改，避免双向依赖和接口漂移。
- facade 删除前使用静态引用扫描、运行时入口清单和契约测试确认仓库内调用方为零；若存在仓库外公开兼容承诺，则保留最小 adapter 并记录退出条件。

旧 API 路由可以继续挂载原路径，但内部必须调用 Context Entrypoint/Application。ORM 兼容入口只允许 re-export 映射类给尚未迁移的 Infrastructure，不得被 Domain/Application 使用。

替代方案是长期维护新旧两套 Service，或在 facade 中继续放兼容业务分支；两者都会使依赖方向和事务真相重新变得含糊，因此不采用。

### 4. Environment Projection 通过来源事件失效，不再被来源 Context 反向调用

Environment Projection 是组织、专家、知识、Connector、权限等来源事实的下游 read model 和快照组装者，不拥有来源业务对象。解环后的写入链路为：

```text
Organization / Expert / Wiki / Connector / Access Control
  → 业务状态与 integration event 同一 UoW 提交到 Outbox
  → Bootstrap 注册的 handler
  → InvalidateEnvironmentSnapshot use case
  → 标记相关 snapshot stale / 更新 source version
```

来源 Context 不 import Environment Projection，也不在自身 Service 完成后直接调用刷新函数。事件使用纯 envelope，至少包含 `event_id`、`event_type`、`tenant_id`、`source_id`、`source_version`、`occurred_at` 和影响范围；消费者按 `event_id` 去重，并仅接受比已见版本更新的 source version，以容忍重复和乱序。

读取链路为：

```text
Intent / Planning / Agent Application
  → 调用方定义的 ContextQueryPort
  → Environment Projection facade/adapter
  → 来源 Context published query ports 或 read model
  → ContextSnapshot(scope, provenance, versions, missing, expires_at)
```

snapshot 失效后采用按需重建；事件处理失败由 Outbox 重试，过期时间保证漏失事件不会形成永久有效缓存。重建失败返回带 `missing/stale` 信息的结果；权限或敏感范围无法确认时 fail closed。Environment 只保存 ID、来源版本、引用和自己的 read model，不反向写来源表。

选择事件失效加按需重建，而不是同步回调，是为了消除双向依赖并把来源事务与快照可用性解耦。选择版本化失效而不是每次全量刷新，是为了限制数据库和检索成本。P0 内先覆盖当前造成循环的来源；P3 再按 Context 增补更细粒度事件。

### 5. Context 间同步协作由调用方 port 隔离，异步协作使用 Outbox event

同步查询或命令的默认依赖形状为：

```text
Caller Application → Caller-owned Port → Adapter → Callee Published Contract/Use Case
```

adapter 位于调用方 Infrastructure 或 Bootstrap；Bootstrap 负责把具体实现注入 use case。调用方不读取被调用方 ORM，也不 import 对方 Domain/Application/Infrastructure。只有被多个真实消费者稳定使用的 DTO 才进入被调用方 `contracts`；调用方专用需求保留为调用方 port，避免把内部模型升级为共享语言。

需要与来源事务原子提交、允许最终一致或需要重试的协作使用 integration event：业务状态和 Outbox 同一事务保存，Platform 只负责通用 claim/lease/retry/dead-letter，Bootstrap 注册 Context handler。事件只表达已发生事实，不携带 ORM、Session、Repository 或可变 Entity。

直接 Service 调用实现简单但会重新泄漏实现和事务；所有跨 Context 都强制异步则会给只读查询增加不必要复杂度。因此同步 port 与异步 event 根据一致性语义并存。

### 6. Unit of Work 由用例拥有，Repository 默认只 flush

每个有写行为的 Context 在 Application 定义最小 `UnitOfWork` protocol，暴露该用例需要的 Repository、Outbox/Event publisher 以及 `commit/rollback` 生命周期。SQLAlchemy 实现位于该 Context Infrastructure，可共享 Platform database 的 session factory，但不得把 `AsyncSession` 暴露给 Application 或 Contracts。

普通短事务遵循：

```text
async with uow:
  aggregate = repository.get(...)
  aggregate.apply(command)
  repository.save(aggregate)       # flush, no commit
  uow.events.append(...)
  await uow.commit()
```

用例是 commit 的唯一决策者；Repository 和兼容 facade 不自行提交。事务失败由 UoW rollback，并转换为 Context 自己的应用失败。跨 Context 不共享同一个 UoW，不以共享 Session 获得伪原子性；需要协作时使用 Outbox 和幂等消费者。

LLM、Tool、HTTP、MCP、对象存储等长调用使用三阶段边界：

1. 短事务 claim/lease 或建立 pending execution，提交。
2. 事务外执行外部调用。
3. 新短事务校验 owner/version/attempt，保存结果、证据和后续事件，提交。

这延续现有 durable runtime 的可靠性语义，同时把事务机制隐藏在 Infrastructure。备选方案是给所有 Service 传同一个 Session，虽然改动较小，却无法建立 Context 数据所有权，也会继续在外部 I/O 期间持有事务，因此不采用。

### 7. P1 以 Proposal Management 建立首个完整参考切片

Proposal Management 先完成，因为它已有 Domain/Application 错误和 HTTP error mapper，可在较小范围内验证完整迁移方法。目标职责为：

- Domain：Proposal 状态、允许的转换和业务不变量，不依赖 ORM/Agent/Task。
- Application：创建、查询、预研、评审、通过/驳回、转执行意图等实际存在的用例；一个入口调用一个主要 use case。
- Ports：`ProposalRepository`、`UnitOfWork`，以及按当前行为需要定义的 `ExpertResearchPort`、`KnowledgeQueryPort`、`PlanningPort`/`TaskCreationPort` 等调用方端口。
- Infrastructure：现有 Proposal ORM 映射、repository 和到 Expert/Agent/Planning/Task published contract 的 adapter。
- Entrypoints：保持现有 HTTP schema/envelope/permission semantics 的 DTO 和错误映射。

旧 `proposal_service.py` 变成无业务分支、无事务提交的兼容委托。现有表和主键保持不变；领域对象与 ORM 使用 mapper 翻译，Application 不返回 ORM。AI 预研结果仍只是建议或证据，不能绕过真人评审直接改变提案状态。

Proposal 切片完成标准不是目录齐全，而是所有 Proposal 写行为由新 use case 拥有、内部调用方不再依赖旧 Service、Domain/Application 测试无需数据库即可运行。后续 Context 复用迁移流程和技术模式，但不复用 Proposal 的业务基类或通用 Service。

### 8. P2 用纯契约拆开 Agent、Capability、Planning、Workflow 和 Task

执行底座按以下所有权和依赖拆分：

| Context | 拥有 | 对外纯契约 | 明确不拥有 |
|---|---|---|---|
| Expert Management | 专家生命周期、版本和能力绑定 | `ExpertExecutionSnapshot` | Agent 执行记录、Tool 实现 |
| Capability Catalog | 能力定义、schema、风险、副作用和版本 | `CapabilityDefinition` | 调用记录和目标业务规则 |
| Capability Execution | invocation、授权、幂等、执行证据 | `CapabilityRequest/Result` | Wiki、数据查询、交付等目标规则 |
| Agent Execution | 一次 Agent 调用、trace 和结构化结果 | `AgentExecutionRequest/Result`、`ExecutionTrace` | Expert、Workflow、Task 状态 |
| Work Planning | WorkIntent、WorkflowPlan 和计划校验 | `PlanWorkRequest/WorkflowPlan` | durable run/step 状态 |
| Workflow Runtime | Run/Step、DAG、lease、attempt、重试、恢复和人工停点 | Start/Execute/Resume command/result/event | TaskCard、Expert ORM、具体 Tool |
| Task Management | TaskCard、分配、验收、驳回和任务日志 | Task command/result/event | WorkflowStep 执行状态 |

这些 Contracts 使用不可变、可序列化的纯数据结构，只包含标量、枚举、稳定 ID、版本、快照、引用和结构化错误；禁止 `AsyncSession`、ORM、FastAPI、SDK 对象、可调用对象或 `Any` 形式的运行依赖。运行依赖独立为 Application port，例如 `LlmPort`、`KnowledgeQueryPort`、`CapabilityExecutionPort`、`ExpertSnapshotPort`、`Clock` 和 `UsageAuthorizationPort`，由 Bootstrap 注入。

Agent Execution 不再接收 `AgentRole ORM`，只消费不可变 `ExpertExecutionSnapshot`；历史 Workflow 保存 expert ID 和 snapshot/version，专家配置更新不得改变既有运行的执行语义。Capability Execution 先读取版本化定义并校验主体、专家授权、参数、风险、审批和幂等键，再调用目标 Context port；Tool handler 不拼 URL、不读密钥、不直接修改其他 Context ORM。

Workflow step 执行保持四个明确阶段：

```text
Claim → Prepare snapshots/contracts → Execute external work → Finalize with version check
```

Workflow Runtime 只通过 `AgentExecutionPort`/`CapabilityExecutionPort` 执行，不读取 Expert ORM 或具体技能实现。Workflow 进度通过 `WorkflowProgressed` integration event 投影到 Task Management；Task 接受/驳回发布事件，Workflow handler 收到后重新校验 `waiting_human + step version + principal/policy`，再推进运行。两者不直接更新对方表。

选择多个小而深的 Context 契约，而不是一个通用 `ExecutionContext` 或 `RuntimeService`，是因为这些状态具有不同写入所有者、生命周期和失败语义。纯 DTO 也让 Application use case 能在无数据库、无网络条件下测试。

### 9. P3 按依赖顺序迁移其余 Context，而不是按横向层批量移动

P3 使用 P1 的切片模板，但按“被依赖的稳定基础能力先于业务消费者”排序：

1. Identity、Organization Structure 和 Access Control，先发布 `Principal`、组织快照和 PolicyDecision。
2. Wiki Management、Knowledge Indexing/Retrieval、Semantic Catalog、Organizational Memory，建立文档事件、检索引用和记忆来源边界。
3. Assistant Conversations、Group Messaging、Collaboration Requests，分开会话、群消息和跨部门请求所有权。
4. Meeting Management 和 Operational Analytics，消费已稳定的 Expert/Knowledge/Planning/Connector port。
5. Audit、Human Review、AI Quality、Usage & Budget 等治理/反馈 Context 按真实调用点迁移，不允许直接修改来源 Aggregate。

每个 Context 都保留原 API 和表，通过 mapper 复用现有 ORM；只有存在真实消费者时才创建 contracts。Knowledge 写入链路采用 `DocumentPublished → Indexing → IndexReady → Retrieval`，索引和记忆都是带版本、来源和范围的 read model，不能反向覆盖来源事实。Meeting 的 AI 发言、投票和纪要仍是建议，真人决议由 Meeting Management 自身用例生效。

P3 不创建一个容纳所有迁移逻辑的 `foundation_service`。跨域复用通过稳定 capability/port 发生，共享 Kernel 继续只保留与传输无关、真正稳定的最小语义。

### 10. P4 让 HTTP 成为薄 adapter，并按业务 feature 拆分前端

HTTP 迁移后的标准路径为：

```text
FastAPI route
  → 解析/校验 transport DTO 与 Principal
  → 构造 Context command/query
  → 调用一个主要 Application use case
  → 映射 Context result/error 到现有 {code, msg, data}
```

route 不直接 import ORM、Repository、LLM、其他 Service，也不提交事务。迁移期 `app/api` 可以作为路由兼容挂载点；Context-specific router/mapper 位于自己的 Entrypoints，Bootstrap 统一注册。稳定应用错误到 HTTP 的映射留在 Bootstrap/Context Entrypoint，不把 HTTP status/code 放进 Domain/Application。

前端从 Group Chat 开始按业务能力组织：

```text
features/discussion/
  api.ts
  hooks/useGroupChatSession.ts
  hooks/useChannelMembers.ts
  MessageList.tsx
  MessageComposer.tsx
  MemberPicker.tsx
  GroupChat.tsx
```

feature 拥有 API adapter、SSE/轮询生命周期、发送/已读/附件等副作用和相应状态；路由页面只组合 feature。拆分以状态所有权和变化原因划界，不创建大量只透传 props 的组件。首先用 characterization/component test 锁定消息顺序、重连、重复事件、未读、附件和成员选择行为，再移动 hook；路由和后端 API contract 保持不变。

P4 可以在后端迁移期间并行进行纯前端拆分，但 HTTP adapter 切换必须等对应 Application contract 稳定。选择 feature 组织而不是按 `components/hooks/services` 横向分层，是为了让一次讨论功能变化主要限制在一个目录。

### 11. 测试采用“行为锁定 + 边界门禁 + 分层验证”

每个切片合并前至少经过以下验证：

| 测试层 | 目的 |
|---|---|
| Characterization | 锁定旧成功/失败、权限、事务、响应和副作用行为 |
| Domain unit | 在无 DB/网络/框架条件下验证不变量和状态转换 |
| Application use case | 用 fake ports/UoW 验证编排、commit/rollback 和失败分类 |
| Contract | 验证 command/result/event 序列化、版本和 adapter 翻译 |
| Infrastructure integration | 验证 ORM mapper、repository、并发 lease、Outbox 和幂等 |
| Entrypoint | 验证参数、身份、权限、错误和 HTTP envelope 不变 |
| Architecture | 验证全局无环、分层禁止依赖、无 facade 反向引用和数据边界 |
| Regression/E2E | 验证 Proposal、Workflow/Task、Environment 和 Group Chat 关键闭环 |

关键场景包括：Environment 重复/乱序事件不会回退 source version；无权限快照 fail closed；Agent/Capability 契约不含 ORM/Session；外部调用不持有长事务；Tool/MCP 重试复用幂等结果；Task 接受后 Runtime 重新校验人工停点；旧 API 和新 Entrypoint 返回等价 envelope；facade 与直接 use case 在迁移期结果一致。

质量门按改动范围逐步执行，最终运行 `ruff`、`mypy app`、非 delivery-contract 全量 Pytest，以及前端 test/lint/build。架构测试在每个阶段运行，不能留到 P4 才统一修复。

### 12. 多代理并发以排他写集和阶段屏障协调

P0～P4 有依赖关系，不能把所有文件无约束地同时修改。采用“并行切片、串行集成”模式：

- 每个工作包在开始前声明排他写集；目标 Context、新旧 facade、对应测试由同一个 owner 持有。
- `app/bootstrap/**`、`app/main.py`、中央 route/handler registry、全局架构测试、共享 Kernel、顶层 package `__init__` 和 OpenSpec 状态由集成人串行修改，子任务只提交 wiring delta 清单。
- 同一旧文件不能被两个代理同时拆分；需要共享契约时先冻结 contract 文件及版本，再并行实现 adapter。
- 共享工作区不通过相互 cherry-pick 合并；代理不得重写、格式化或回退不在自己写集内的文件。
- 每个工作包交付 handoff：改动文件、契约版本、迁移的调用方、遗留调用方、所需中央 wiring、已运行测试和回滚点。

建议执行波次如下：

| 波次 | 可并行工作 | 阶段屏障 |
|---|---|---|
| Wave 0 | P0 依赖图/禁止边、现存循环各自解环、Characterization 基线 | 全局循环为零，中央测试全绿 |
| Wave 1 | P1 Proposal；P2 Expert/Agent contracts；P2 Capability contracts；P4 Group Chat 纯前端拆分 | Published contracts 冻结，旧 API/行为等价 |
| Wave 2 | P2 Workflow/Task 事件拆分；Environment event handler；首批 Identity/Organization/Wiki adapter | UoW、Outbox、幂等和人工停点测试全绿 |
| Wave 3 | P3 Communication/Meeting/Analytics 纵向切片；对应 HTTP Entrypoint | Context 内调用方迁完，无新 facade 依赖 |
| Wave 4 | P4 HTTP 收口、中央 wiring、删除零调用 facade、全量回归 | 全质量门、迁移 head 和回滚演练通过 |

若并发槽有限，优先保持一个集成人和若干互不重叠的 Context owner；不要为了提高并发度拆开同一 Context 的 Domain、Infrastructure 和 facade，因为那会增加契约和事务冲突。

替代方案是让每个代理自由修改中央 wiring 后再解决冲突，或按技术层把 Domain/Repository/API 分给不同代理。前者在共享工作区容易覆盖，后者会让同一用例的边界无人端到端负责，因此不采用。

## Risks / Trade-offs

- [迁移期新旧入口形成双写或双执行] → 每个业务对象只配置一个 active writer；facade 只能委托，Workflow 同一 run 不允许两套执行器推进。
- [纯契约数量增加，产生浅包装和导航成本] → 只有真实跨 Context 消费者才创建 contracts；Context 内部 DTO 保持本地，优先设计少量深 use case。
- [事件最终一致导致 Environment/Task 短暂滞后] → 返回 source version、stale/missing 信息，使用 Outbox 重试、幂等、过期重建和面向用户的 pending 状态；需要强一致的来源命令仍由来源 Context 处理。
- [事件重复、延迟或乱序破坏投影] → event ID 去重、source version 单调检查、消费者幂等，并提供可重建 read model。
- [UoW 重构改变现有隐式 commit 时机] → 先用 characterization test 锁定事务可见性；一次迁移一个用例；Repository 只 flush，用例测试显式验证 commit/rollback 次数。
- [外部调用与最终落库之间崩溃] → 保留 lease/attempt/version 条件更新、ToolExecution 幂等、确定性外部引用和恢复扫描。
- [兼容 facade 长期残留] → 为每个 facade 记录 owner、剩余调用方和删除条件；架构测试禁止新引用，P4 按零调用清单删除。
- [中央 wiring 成为多人修改热点] → Context owner 只提供 wiring delta，集成人按阶段屏障串行应用并运行 smoke test。
- [大规模移动降低 `git blame` 可读性并隐藏行为修改] → 文件移动与业务改变分开；先迁移/委托并验证，再做机械重命名和格式化。
- [前端 Hook 拆分改变 SSE/轮询时序] → 先锁定 fake timer、重连、去重和卸载清理行为；每次只转移一组状态和 effect。
- [架构规则过严阻断必要适配] → adapter 放在调用方 Infrastructure 或 Bootstrap；过渡豁免必须精确、带 owner/截止批次，不能放宽整个目录。
- [Context 过度细分] → 以独立语言、生命周期、写入数据和变化原因作为边界；简单 Context 可保持少量文件，不强制五层目录齐备。
- [并发代理基于不同契约实现] → Published contract 先冻结并有 contract test；变更契约由 contract owner 广播并串行升级消费者。

## Migration Plan

### P0：冻结行为、治理依赖和解开 Environment

1. 建立关键用例 characterization test 和当前 import SCC 清单。
2. 增加“禁止新增/扩大循环”以及分层、Context、Platform、facade 依赖测试。
3. 收紧 Agent/Knowledge 包 `__init__`，消除 eager re-export 和局部 import 掩盖的循环。
4. 为 Organization、Expert、Knowledge、Connector、Access 等当前来源定义最小版本化变更事件。
5. 在 Bootstrap 注册 Environment invalidation handler，让来源事务只写 Outbox，删除来源到 Environment 的同步反向调用。
6. 清零全部 SCC，切换到全应用无环门禁并删除临时豁免。

P0 回滚：可回退 handler wiring 并恢复旧 facade 路由，但不得同时启用同步刷新和事件刷新两个 writer。Environment snapshot 是可重建 read model，可丢弃新投影状态后由来源重新生成；来源表和 API 不变。

### P1：完成 Proposal Management 参考切片

1. 从现有 Proposal 行为提炼 Domain 状态和 use case contract。
2. 定义 Proposal Repository/UoW 和外部 Expert/Knowledge/Planning/Task ports。
3. 实现 ORM mapper/repository 和 adapters，保持现有表不变。
4. 将旧 Proposal Service 和 API 改为单向委托，迁移内部调用方。
5. 通过 Domain、Application、Infrastructure、Entrypoint 和 API 等价测试后，删除已无调用方的实现分支。

P1 回滚：Bootstrap/facade 可重新绑定旧实现；新旧实现复用同一表且不双写，无需数据迁移。若已产生新格式事件，保留向后兼容 consumer，不能删除已提交 Outbox 记录。

### P2：迁移执行与编排底座

1. 先发布并冻结 ExpertSnapshot、Capability、Agent Request/Result、WorkflowPlan、Workflow/Task event 等纯契约。
2. 提取 Context 自有 UoW 和 adapters，逐步移除 `AsyncSession`/ORM 参数。
3. Capability Catalog/Execution 先迁移定义、授权、幂等和目标 port 分发。
4. Expert/Agent 再迁移版本化快照和 ExecutionPorts。
5. 分离 Work Planning 与 Workflow Runtime；将 step executor 调整为 Claim/Prepare/Execute/Finalize。
6. 以 integration event 分开 Workflow Runtime 和 Task Management 写入所有权。
7. 在每一步保持旧 import path 委托，并验证 lease、attempt、恢复、人工停点和 Tool 幂等。

P2 回滚：按组合根逐 Context 切回旧 adapter，停止对应新 handler 后再恢复旧路径。同一 WorkflowRun 始终只能由一个 runtime binding 推进；已经持久化的 run/step/outbox/tool execution 继续由现有表解释，不改变 schema 或状态枚举语义。

### P3：逐 Context 迁移业务、知识、沟通和治理能力

1. 依次迁移 Identity/Organization/Access，稳定 Principal、snapshot 和 policy contract。
2. 迁移 Wiki/Index/Retrieval/Memory，并建立事件驱动索引与带 provenance 的查询。
3. 迁移 Assistant Conversation、Group Messaging 和 Collaboration Request。
4. 在上述基础契约稳定后迁移 Meeting 和 Operational Analytics。
5. 按调用点迁移 Human Review/Audit/AI Quality/Usage，确保它们只返回决策或记录证据，不写来源 Aggregate。
6. 每完成一个 Context，迁移其内部调用方并删除零调用 facade；未轮到的 Context 继续通过旧入口运行。

P3 回滚以 Context 为单位切回 facade binding；事件消费者可暂停后重放，read model 可重建。禁止跨多个 Context 做必须整体回滚的共享事务。

### P4：入口收口、前端 feature 化和清理

1. 将已迁移 Context 的 route 改为 command/query adapter，清除 API 对 ORM/Service 的直接引用。
2. 按 Discussion feature 拆 Group Chat 状态、SSE/轮询、副作用和展示，再按收益迁移其他页面。
3. 扫描并删除无调用方 facade、旧 re-export 和临时 dependency exemption。
4. 由集成人串行完成中央 route/handler/wiring 注册，执行应用启动和 Worker smoke test。
5. 运行后端全质量门、前端 test/lint/build、migration-head 验证和关键 E2E。
6. 更新 facade 清单和架构文档实施状态；只有所有验收通过后才结束 change。

P4 回滚可以恢复旧 route/component 组合，但保持 Context use case 和纯契约；前端构建产物可按上一版本部署。删除 facade 前必须确认没有仓库外兼容承诺，否则保留最小 adapter。

### 发布与回滚原则

- 每个 P 批次和每个 Context 都是独立可部署检查点，不等待 P0～P4 全部完成才验证。
- 数据库 schema 和公开 API 不变，因此首选代码级回滚；禁止通过删除表或回写历史状态回滚。
- 新旧事件 consumer 交替时先停旧、再启新，并以 dedupe/version 确保重放安全。
- 任何回滚都不得同时激活两个 Workflow writer、两个 Proposal writer 或两套 Environment 刷新路径。
- 若一个切片无法通过定向测试，回退该切片的 wiring/facade 委托，不回退其他已通过且文件集独立的 Context。

## Open Questions

- 当前各来源模型是否都有可单调比较的业务版本；若没有，P0 应使用现有更新时间/事务版本，还是为投影事件引入仅应用层使用的 source revision？本 change 不默认增加数据库列。
- 仓库外是否存在直接 import `app.services`/`app.agents` 的插件或脚本；在删除 facade 前需要由部署清单确认兼容窗口。
- P3 中 Human Review 和 AI Quality 目前是否已达到独立写入所有权和生命周期条件；若尚未达到，先作为有独立 port 的强模块隔离，不预建完整 Context。
