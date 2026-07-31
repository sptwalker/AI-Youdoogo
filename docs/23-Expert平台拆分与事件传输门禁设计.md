# 23 · Expert 平台拆分与事件传输门禁设计（Phase 3）

> 依据 docs/21《通用AI平台拆分架构与落地方案》。Phase 1（LLM Gateway）、Phase 2（Knowledge
> Service）已交付并离线验收。本文定义 **Phase 3 = 拆出 Expert Platform（6–10 周）** 的完整方案，
> 并给出其**硬前置门禁**——可靠事件传输 Go/No-Go——的设计与验收口径（DoD）。

## 1. 为什么事件传输是 Phase 3 的硬前置

docs/21 三处把"可靠事件传输通过"钉为拆分的前置条件：

- **Immediate Backlog C（工程底座）**："实现 Outbox Relay / Inbox 标准模板、DLQ 和重放工具。"
- **风险表**："误把本地 Outbox 当成跨服务消息总线（中/高）——Relay / Inbox / DLQ / 重放故障演练
  通过后再拆 Runtime。触发后：长任务保持本地，停止启用远程事件消费者。"
- **架构决策**："消息中间件延迟到 Phase 3 决策——先以 EventPublisherPort + PostgreSQL Outbox
  Relay / HTTP Inbox 验证。"

Phase 3 的 Capability Provider 里，**长耗时 / 审批型工具**必须以异步事件跨服务交接（Expert 平台发
`step.ready` / 业务系统回 `completed|failed`）。这条链路不可靠（丢/重/乱序/卡死），业务投影就会错乱且
不可重建。因此：**事件传输门禁不过 → Expert 长任务留在本地 Agent Runner，不启用远程事件消费者。**

## 2. 关键前提：可靠性机制已就位，本轮只补两个薄适配

现有 `app/platform/outbox/` 已是完整事务性 outbox（非新建）：

| 能力 | 现有实现 | 复用为门禁的哪一环 |
|---|---|---|
| 生产侧幂等 | `enqueue`（`dedupe_key` 唯一约束） | 同一业务事件不重复入队 |
| 租约领取 | `claim_next`（PG `SKIP LOCKED`） | 多 worker 抢占不重复投递 |
| 退避重试 | `fail`（未达 max_attempts 回 PENDING 延后） | 瞬时故障自愈 |
| 死信 | `fail`（达上限置 FAILED）+ `list_failed` | DLQ 队列与积压指标 |
| 重放 | `replay`（仅 FAILED→PENDING） | 修根因后重投，不重放在途 |
| 积压指标 | `backlog_counts` | 门禁 backlog 观测 |
| 路由扩展缝 | `register_event_handler(event_type, handler)` | 挂 relay，不改现有路由 |
| 死信运维端点 | `GET /api/v1/outbox/dead-letters` + `/{id}/replay` | 人工重放入口 |
| 服务身份令牌 | `mint_internal_token` / `verify_internal_token`（ES256） | 跨服务鉴权（签/验分离） |

**跨服务传输真正缺的只有两件 + 一次演练**：① 出站 HTTP 投递（把 outbox 事件 POST 给对端 inbox）；
② 入站幂等 Inbox（对端收下、去重、落库、ack）；③ 端到端 Go/No-Go 演练。重试 / 租约 / 退避 / DLQ /
重放 / 生产侧去重全部免费继承。

## 3. 事件传输门禁 PoC（本轮交付）

新平台模块 `app/platform/eventing/`。**默认关闭**（`event_relay_enabled=False`）→ 现网 worker 行为零改变。

### 3.1 诚实的范围界定

- **回环（loopback）验证**：Relay 出站 HTTP 打到**本服务自己的** `/internal/events`。理由：Phase 3
  真正的远端消费者（Expert Platform）尚不存在；两个现存服务仓（gateway/knowledge）是请求/响应型、
  非事件消费者。回环能在**离线、无新服务**下端到端证明「签发→POST→验签→幂等落库→DLQ→重放」这条
  传输模板——正是门禁要证的东西。真实远端消费者是 Phase 3 主体，`# ponytail:` 标注升级路径。
- **门禁只证可靠传输**：Inbox 落库 + 去重 + ack + 一个平凡 demo 消费者（received→processed）。
  **不**在本轮接真实入站投影（乱序重排语义 / 业务投影是 Phase 3/4 Runtime 的活）。
- **不迁数据、不建远端服务、不改现网默认行为**。

### 3.2 组件

1. **`inbox_model.py`** — `InboxEvent(CommonMixin, Base)`：`event_id`(Uuid, **unique** = 入站幂等去重键)、
   `event_type`、`aggregate_type`、`aggregate_id`、`payload`、`source_service`、`status`
   (`received`/`processed`)。`create_time` 即到达时刻（复用 CommonMixin，不另建 received_at）。
2. **`inbox.py`** — `EventEnvelope`（Pydantic 线协议）；`receive_event(db, envelope, *, source)`：
   INSERT-or-ignore（`event_id` 冲突 = 已收，幂等返回 `False`，不重复处理）；`process_pending`
   平凡 demo 消费者（received→processed，证"逻辑事件只处理一次"）。
3. **`relay.py`** — `HttpInboxRelay`（`ExternalEventHandler`）：`OutboxEvent` → envelope →
   `mint_internal_token`（audience=对端、scope=`events:receive`）→ httpx POST `{peer}/internal/events`；
   非 2xx / 超时 → `raise` → 现有 outbox 退避重试 / DLQ 接管。**日志不回显 token / body 明文**（§7.1 红线）。
4. **`entrypoints/http.py`** — `POST /internal/events`：`HTTPBearer` + `verify_internal_token`
   （audience=本服务、强制 scope `events:receive`）→ `receive_event` → 202；验签失败 401、缺 scope 403。
5. **`composition.py`** + wiring — 开关 on 时 `register_event_handler("expert.step.ready", HttpInboxRelay(...))`
   （PoC 占位事件类型，证扩展缝可用）；router 装配进 `app/bootstrap`。fail-fast：开关 on 但缺 peer/私钥 → 启动报错。

### 3.3 配置（`app/core/config.py`）

| 键 | 默认 | 说明 |
|---|---|---|
| `event_relay_enabled` | `False` | 总开关；关=现网零改变 |
| `event_inbox_peer_url` | `""` | 对端 inbox 根地址；回环填自身 |
| `event_relay_event_types` | `()` | 允许中继的事件类型 allowlist |

### 3.4 Go/No-Go 门禁 DoD（演练全绿才放行 Phase 3 远程事件消费者）

`tests/test_event_transport_gate.py`（sqlite in-memory + ASGITransport 回环，仿 `test_outbox_dlq.py`）：

- [ ] **投递恰一条**：enqueue → relay 投递 → Inbox 落库恰 1 条。
- [ ] **入站幂等**：重复投递同 `event_id` → Inbox 去重、无二次处理。
- [ ] **鉴权**：无/错令牌 → 401；令牌缺 `events:receive` scope → 403。
- [ ] **DLQ**：Inbox 强制 5xx → outbox 重试耗尽 → FAILED；`list_failed` 见死信。
- [ ] **重放**：`replay()` → 重新领取投递 → Inbox 跨重放仍单条逻辑处理（不双写）。
- [ ] 无永久卡死；日志无令牌 / body 明文；relay 默认关不影响现网。

**未过 → Expert 长任务保持本地，不启用远程事件消费者（docs/21 红线）。**

## 4. Phase 3 完整方案（本轮只落文档，代码待门禁通过后逐模块增量）

> 顺序即依赖顺序。每步"单模块增量 + 消费者驱动契约 + Branch-by-Abstraction"，与 Phase 1/2 同法。

1. **事件传输门禁**（本 PoC）— 硬前置，先过 Go/No-Go。
2. **ExpertProfile 物理拆分 / 发布面**：业务 `OrgExpertMember`（组织成员关系）+ 平台
   `ExpertDefinition` / `ExpertRelease`（不可变发布）；业务表存 `expert_release_id` 映射。ADR 0008 已
   拆逻辑聚合（domain 两子聚合 + 组合根），本阶段做**物理表 + 发布流程**面。
3. **资产版本化**：Prompt / 模型策略 / Skill / Tool Descriptor → 可版本化资产（草稿 → 评测 → 发布）。
   为当前每个专家生成不可变 Release，业务表保存 `expert_release_id`。
4. **Expert Execute / SSE**：内部调 Knowledge Search（Phase 2）+ LLM Gateway（Phase 1）；
   交互式专家为第一场景，后台步骤执行为第二场景灰度。**Expert 只调 Search，不调 Answer**（防 Knowledge↔Expert 环）。
5. **Capability Provider 协议**：先迁**只读 + 短事务同步工具**；**长耗时 / 审批型工具必须走本门禁的
   事件交接**。业务副作用与最终授权仍归资源服务（Tool 定义与 Handler 分离）。
6. **回滚**：执行路由切回本地 Agent Runner；业务保留专家执行快照兼容字段；平台发布资产可导出为本地快照。

### 4.2 Module 2 详细设计（本轮交付：不可变发布面，Branch-by-Abstraction 加法式）

**范围界定（诚实）**：远端 Expert 平台尚不存在，本轮**不**做物理拆服务、**不**动 `agent_role` 现有列、
**不**改 97 处调用方的读路径。只加：一张只增不改的发布快照表 + 业务表一个软指针 + 一个发布用例。
`agent_role` 继续充当可变的 "ExpertDefinition"（身份 + 当前工作态执行配置），发布 = 把当前执行配置冻结成
一行 `ExpertRelease`。真正物理拆表 / 独立事务留待远端平台落地（`# ponytail` 标注）。

**表 `expert_release`（不可变，只增不改）** — `CommonMixin`（id / create_time=发布时刻 / update_time /
is_delete）+：

| 列 | 类型 | 说明 |
|---|---|---|
| `expert_id` | Uuid FK→agent_role.id | 属主专家 |
| `version_no` | Integer | 该专家内单调递增版本号，`(expert_id, version_no)` 唯一 |
| `prompt_template` | Text | 发布时冻结 |
| `model_role` | String(32) | daily / reasoning，发布时冻结 |
| `permission_scope` | JSONB | 发布时冻结 |
| `tools` | JSONB | 发布时冻结 |
| `duty` | Text? | 发布时冻结 |
| `released_by` | Uuid? | 发布操作人（AI 仅辅助，最终真人确认——留痕位） |

**业务表 `agent_role` 加软指针** `current_release_id: Uuid?`（**不加 FK 约束**，避免与
`expert_release.expert_id` 成循环外键、破坏 sqlite `create_all` 排序；真链由 release 行反向 FK 保证）。
指向"当前已发布"快照；回滚（Module 6）= 改指针到旧 `version_no`。

**发布用例** `ExpertManagementApplication.publish_release(expert_id, released_by=None)`：读当前专家 →
`next_version_no = max(version_no)+1` → 插入不可变 `ExpertRelease` 快照 → 置 `current_release_id`。
同一 UoW 事务内完成。**触发时机**（create/update/seed 后自动切版 vs 显式发布）由 Module 3 的
草稿→评测→发布生命周期决定，本轮只提供操作，不挂自动触发（`# ponytail`）。

**为何现在做**：不可变执行快照本身满足审计红线（"某 AI 产出用了哪个配置"可精确复现），且是 Module 3
（资产版本化）与 Module 6（回滚）的地基；非仅为远端消费者。加法式默认不改现网行为。

### 4.3 Module 3 详细设计（本轮交付：把发布快照升级为「已评测、可枚举」的版本化资产）

**范围界定（诚实）**：`草稿 → 评测 → 发布` 三段的**评测**能力已存在（`RunEvaluation` 跑 eval_case 出聚合分）、
**草稿**即 agent_role 可变执行态、**发布**即 Module 2 的 `publish_release`。Module 3 只补两处让快照成为真正
"可版本化资产"：① 发布时把**评测证据**（分数 + 用例数）冻结进 release（把独立的评测分与它所门控的版本绑定，
可审计复现）；② 提供**版本谱系读回** `list_releases`（枚举某专家全部历史版本——"可版本化"的读侧，也是 Module 6
回滚选版的地基）。**红线不变**：评测只产出分数，是否发布仍真人确认；本轮不做"过阈自动发布"（`# ponytail`）。

- `expert_release` 加两列 `eval_score: Float?`、`eval_case_count: Integer?`（发布时快照，可空=未附评测证据）。
- `publish_release(expert_id, *, released_by=None, eval_score=None, eval_case_count=None)` 透传两值。
- `ExpertReleaseRepository.list_releases(expert_id) -> tuple[ExpertReleaseView, ...]`（按 version_no 倒序）。
- `ExpertReleaseView` 增 `eval_score` / `eval_case_count` 字段。

### 4.4 Module 4 详细设计（本轮交付：已发布快照驱动执行 = Execute/SSE 消费 release 面）

**范围界定（诚实）**：Agent 执行链本身**已完整存在**且已是 Phase 3 目标形态——`AgentExecutionApplication.stream`
逐块 SSE；`CurrentKnowledgeAugmentationAdapter` 调 Knowledge **Search**（非 Answer，规避 Knowledge↔Expert
回环）；`FallbackCompletionPort` 远程为主本地兜底调 LLM 网关。**不重造**。Module 4 只补 Module 2/3 遗留的
唯一缺环：**执行读的是哪一份配置**。

**问题**：所有执行经 `SQLAlchemyExpertSnapshotQuery.get_by_id` 取 `ExpertExecutionSnapshot`，当前读**可变的**
`agent_role` 活行——于是草稿态编辑立即污染在跑的执行，且 Module 2/3 冻结的 `expert_release` 快照无人消费（写死的
博物馆）。Module 4 让**已发布的不可变 release 驱动执行**：草稿改动在真人 `publish_release` 前不影响线上运行。

**做法（加法式、单一切换点）**：`get_by_id` 先看 `agent_role.current_release_id`——
- 有指针 → 从其指向的 `expert_release` 冻结行构建快照（released 资产驱动执行）；
- 无指针（seed / 从未发布的存量专家）→ 回落读活行 `agent_role`（**零行为变更**，向后兼容）。

`snapshot_from_release(row)` 把 release 行映射为 `ExpertExecutionSnapshot`：`version` 取 `f"v{version_no}"`
（可复现该版），`prompt_template/model_role/permission_scope/tools/duty` 取冻结值；`name/title/department_id/
owner_user_id` 这些**组织归属**字段仍读活 `agent_role`（ADR 0008：org 与 execution 是两个子聚合，release 只冻
execution，组织信息本就不该进不可变执行快照）。

**红线**：只改"读哪份执行配置"，不改执行语义、不碰知识/网关链；无发布记录的专家行为逐字不变；AI 输出仍可编辑/驳回/终止。


### 4.5 Module 5 详细设计（本轮交付：Capability Provider 协议 = 传输资格声明）

**范围界定（诚实）**：能力执行栈**已完整存在**——`CapabilityExecutionApplication.execute` 走
resolve→参数校验→授权→审批门→幂等→dispatch；`CurrentCapabilityApproval` 已按 `risk` 经 human-review
驱动真人复核。远端 Capability Provider **尚不存在**，两个现存服务仓（gateway/knowledge）非事件消费者。
Module 5 **不**建远端 Provider、**不**改 in-process dispatch 语义、**不**启用事件传输（门禁默认关）。只补
Provider 协议真正缺的那块契约：**每个能力声明自身的跨服务传输资格**——哪些可作只读/短事务被 Provider
**同步就地**服务、哪些必须经 §3 事件门禁**异步交接**。这条声明是 plan #5「先迁只读+短事务同步工具；
长耗时/审批型工具必须走事件交接」的可机检落点，也是 Module 6 回滚路由与未来远端 Provider 的共同判别依据。

**做法（纯派生、加法式）**：以 `side_effect`（plan 命名的「业务副作用归资源服务」轴）为判别：

- `side_effect == NONE` → `SYNC_LOCAL`：只读/短事务，Provider 可同步就地服务（`env_context` / `data_query`）。
- 否则（`INTERNAL_WRITE` / `EXTERNAL_WRITE`）→ `EVENT_GATED`：有副作用/长耗时/审批型，必须经事件门禁
  异步交接（`collab` / `deliver`）。

`capability_transport(definition) -> CapabilityTransport` 派生函数 + `CapabilityTransport` 枚举置于 catalog
契约，经 `public` 导出；`GET /api/v1/agents/skills` 列表回带 `transport`，令角色配置面与未来 Provider 可读
传输资格。`risk` 轴保持**正交**——审批门已由 §4 current_policy 按 risk 驱动真人复核，不并入传输判别
（若日后出现「只读高危」能力再扩，`# ponytail`）。

**红线**：不改 dispatch 语义、不启用远端传输（门禁默认关）；`EVENT_GATED` 现仍就地执行，真正的远端异步
交接是 Phase 3 远端平台主体，`# ponytail` 标注升级路径；业务副作用与最终授权仍归资源服务。

### 验收（Phase 3 整体，docs/21 §Phase 3）

同一 release 可复现 Prompt / Tool / Model 配置；组织变更不生成 AI 资产版本；所有业务工具由资源服务
最终鉴权，命令具备幂等和确定状态查询。

## 5. 红线核对

- 默认关不改现网；`knowledge`/`gateway`/未来 Expert 仅持**验证公钥**，私钥只在 AI-Youdoogo。
- 无双写（事件是单向交接，非双写真源）。
- AI 决策仍真人确认（业务 / 资金 / 项目 / 人事决议须真人生效）。
- 密钥不硬编码；日志不打 Authorization / body 明文。
