# ADR 0009：跨服务契约治理策略（Envelope / SemVer 兼容 / 消费者契约测试，实现归 Phase 1）

- 状态：已采纳（Accepted）
- 日期：2026-07-28
- 相关：docs/21-通用AI平台拆分架构与落地方案 §8「契约、数据一致性与版本治理」/ §11 Phase 1 / §14、
  [[ADR 0001]] LLM 完成统一端口（Phase 1 首个 Remote adapter 落点）、docs/adr/README.md（seam 索引 · A1）

## 背景

绞杀链 [[ADR 0001]]–[[ADR 0008]] 已把全部跨 Context 依赖收进 session-free 端口与不透明契约，§13-B 代码
解耦 DoD 闭合；A1（docs/adr/README.md seam 索引）已封存边界并给出「契约版本治理 · 策略指针」。A 组只剩
**A2：把 docs/21 §8 的契约治理从「设计草案」固化为「已采纳决策」**，并明确其实现时点。

A1 事实核查已确认关键约束：当前跨 Context 的 5 个 Protocol 端口**各仅一个本地实现、无远端传输**，端口/DTO
**不携带** `schema_version`。docs/21 §8 把 Envelope、SemVer 兼容、一致性模型写为面向**远端发布契约**
（OpenAPI/AsyncAPI）的治理策略——§8.1 的 `schema_version`/`actor_id`/`caller_service` 属**远端传输层**，
非进程内 Protocol 签名。本 ADR 只**采纳策略并锁定实现时点**，不在 Phase 0 落任何 Envelope 字段（避免过早
脚手架，与 A1 结论一致）。

## 决策 · 采纳 §8 治理策略，实现随 Phase 1 首个 Remote adapter

1. **公共 Envelope（§8.1）采纳为远端契约必备**：首个 Remote adapter（[[ADR 0001]] `RemoteLlmAdapter`，
   docs/21 §11 Phase 1）落地时，其发布契约的**每个跨服务请求/响应/事件**携带 `tenant_key`（当前 Adapter
   固定映射 youdoogo）、`trace_id`、`request/event id`、`actor_id`、`caller_service`、`schema_version`；
   事件另加 `event_id`/`occurred_at`/`correlation_id`；`idempotency_key` 只加于创建命令与副作用操作，不加
   给纯查询/流式生成。**Envelope 是远端边界产物，进程内 Protocol 保持不变。**
2. **SemVer 兼容规则（§8.2）采纳为发布纪律**：每个远端服务发布自己的 OpenAPI/AsyncAPI + 版本化客户端；
   内部领域模型与公开 DTO 分离，DB 实体永不作网络契约；**同一主版本只做向后兼容字段追加，删除/改名/语义
   变化必须升主版本**；不建「大 common 项目」（§8 callout），共享仅限极薄追踪/身份 Envelope 或生成客户端。
3. **事件 `<name>.vN` 判别符约定固化**：现存 outbox 事件类型串（`workflow.progressed.v1`、`INDEX_READY_V1`
   等，见 A1 索引）即本地形态的消息 schema 判别符；远端化时映射为 AsyncAPI 的版本化 channel/message，`.vN`
   语义与 §8.2 主版本规则对齐——`.v(N+1)` 仅在破坏性变更时引入，向后兼容追加不升 `.vN`。
4. **消费者契约测试入 CI（§8.2）定为 Provider 变更门禁**：Provider 契约变更必须验证所有已登记消费者。
   Phase 0 已有的 seam 越界守卫（`test_architecture_boundaries.py` 等，见 A1 索引）是**进程内**前身；
   远端化后升级为跨服务 CDC（consumer-driven contract）流水线——**本 ADR 归为 docs/21 后续 D 组 D1
   实现项**，此处只登记纪律，不建流水线。

## 收编范围与延后

- **本轮零代码**：只采纳策略、锁定实现时点，不落 Envelope 字段、不改任何契约/DTO/端口、不建 CDC 流水线。
  与 A1 同为「封存」性质——把 docs/21 §8 从「设计」抬升为「已采纳决策 + 明确 gating」。
- **实现明确归 Phase 1+**：Envelope 与版本化发布契约随 [[ADR 0001]] `RemoteLlmAdapter` 落地（docs/21 §11、
  §14 灰度路由 1%→10%→50%→100% + 快速回退）；知识/专家 Remote adapter 随 Phase 1/2 各自落地时套用同一策略。
- **CDC 契约测试流水线归 D1**：不在 A 组本轮，避免在无远端消费者时空建流水线（YAGNI）。
- **Internal JWT（§9）不在本 ADR**：属工程底座 C 组 C1（docs/21 §9「第一远程服务前落地非对称短期 Internal
  JWT」），与契约治理正交，另行立项。

## 后果

- 正向：A 组契约治理策略从散落设计固化为单一已采纳决策，Phase 1 远端化有明确 Envelope/SemVer/CDC 纪律清单，
  且与 A1 的「不提前落字段」结论无矛盾——实现时点清晰、无过早脚手架。
- 债务：策略与实现分离，真正生效依赖 Phase 1 首个 Remote adapter；在此之前跨 Context 仍走进程内端口，
  契约兼容性靠 A1 seam 索引 + 现有进程内守卫兜底。

## 守卫

- 无新增可执行守卫——本 ADR 是策略决策而非代码接缝。策略生效点在 Phase 1 Remote adapter 的发布契约与
  D1 CDC 流水线，届时由各自 ADR 补守卫。
- `docs/adr/README.md` 登记本 ADR（`tests/test_adr_index.py` 核对编号一一对应，防漏登）。

自证：本 ADR 与 A1 索引「契约版本治理 · 策略指针」段互引且不矛盾——A1 记「不落字段、指向 §8」，0009 记
「采纳 §8、实现归 Phase 1」，两者共同构成 A 组「策略已定、实现待远端化」的完整封存。
