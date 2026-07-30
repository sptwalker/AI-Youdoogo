# Architecture Decision Records — Seam Index

AI-Youdoogo 通用AI平台拆分绞杀链（Phase 0）已把全部跨 Context 依赖收进 session-free 端口与不透明契约。
本索引是 ADR 0001–0009 的**单一封存视图**——每个 seam 的 Port / 唯一切换点 / 守卫测试 / Phase-1+ Remote
目标一屏可扫，防边界在后续开发中被无意绕过或遗忘。ADR 0009 为跨服务契约治理策略（非 seam）。

---

## Cross-Context Seam 边界总览

| ADR | Seam / Port | 唯一切换点（工厂） | 守卫测试 | Phase & Remote 目标 |
|-----|-------------|-------------------|---------|---------------------|
| [0001](0001-llm-completion-port.md) | `LlmCompletionPort` | `model_gateway.public.build_local_llm_completion_port()` | `test_architecture_boundaries.py::test_llm_completion_flows_through_model_gateway_seam` | Phase 1: `RemoteLlmAdapter` |
| [0002](0002-knowledge-search-port-and-usage-budget.md) | `KnowledgeSearchPort` + usage budget public | `knowledge_retrieval.public.build_local_knowledge_search_port(session)` + `usage_budget.public` | `test_architecture_boundaries.py` (seam scan) | Phase 2: `RemoteKnowledgeAdapter` |
| [0003](0003-expert-directory-port.md) | `ExpertDirectoryPort` (read) | `expert_management.public.build_local_expert_directory_port(session)` | `test_architecture_boundaries.py::test_expert_directory_flows_through_port_seam` | Phase 1: `RemoteExpertDirectoryAdapter` |
| [0004](0004-expert-provisioning-port.md) | `ExpertProvisioningPort` (write) | `expert_management.public.build_local_expert_provisioning_port(session)` | `test_architecture_boundaries.py::test_expert_provisioning_flows_through_port_seam` | Phase 1: `RemoteExpertProvisioningAdapter` |
| [0005](0005-runtime-event-opaque-payload.md) | `WorkflowProgressedV1` (opaque event) | N/A (contract self-owns; ACL decode in `task_management`) | `test_planning_workflow_task_contracts.py::test_runtime_event_names_no_product_fields` | Phase 4: Runtime Contract v2 |
| [0006](0006-knowledge-index-port.md) | `KnowledgeIndexPort` (write) | `knowledge_indexing.public.build_local_knowledge_index_port(session)` | `test_architecture_boundaries.py::test_knowledge_index_flows_through_port_seam` | Phase 2: `RemoteKnowledgeIndexAdapter` |
| [0007](0007-runtime-contract-type-decoupling.md) | Runtime contract type-decoupling (DTO) | N/A (contract self-owns `WorkflowLaunchStep`; `expert: object`) | `test_planning_workflow_task_contracts.py::test_runtime_contract_imports_no_cross_context_types` | Phase 4: Runtime Contract v2 |
| [0008](0008-expert-aggregate-logical-split.md) | Domain aggregate split (`OrgExpertMember` / `ExpertExecutionDefinition`) | N/A (domain composition root `ExpertProfile`) | `test_expert_roster_application.py` (3 boundary tests) | Phase 3: physical table split + `ExpertRelease` versioning |
| [0010](0010-lodge-resource-server-foundation.md) | Lodge resource-server (`lodge_identity_v2`) | `service_from_settings(settings, http_client)` | `test_lodge_identity.py` | 默认关闭；Lodge browser target token + online status |

**注**：各 ADR 文件记录完整决策、收编范围、债务与延后项；本索引只汇总关键接缝事实。

---

## 契约版本治理 · 策略指针

当前（Phase 0）进程内 Protocol 端口（`LlmCompletionPort` / `ExpertDirectoryPort` / `ExpertProvisioningPort` /
`KnowledgeSearchPort` / `KnowledgeIndexPort`）**不携带** `schema_version` 字段——事实核查确认：现存 `*_V1`
只是 outbox 事件的消息类型判别串，`version` 字段是乐观锁行版本，都不是端口 schema 版本。

**`schema_version` Envelope + SemVer 兼容规则随首个 Remote adapter 落地时在发布契约（OpenAPI/AsyncAPI）上引入**：

- **docs/21 §8.1「公共 Envelope」**（L1372–1373）：所有跨服务请求/响应携带 `actor_id`、`caller_service`、
  **`schema_version`**——属远端传输层，非进程内 Protocol 签名。
- **docs/21 §8.2「发布与兼容策略」**（L1381）：同一主版本只做向后兼容的字段追加；删除、改名、语义变化必须升主版本
  （SemVer 规则，应用于发布的 OpenAPI/AsyncAPI）。
- **docs/21 §11 Phase 1**（L1545）：首个远端 adapter 是 `RemoteLlmAdapter`，`Local / Remote 使用相同应用 Port`，
  通过 `model_gateway.public.build_local_llm_completion_port()` 工厂切换，配合 §14 灰度路由（1%→10%→50%→100%）
  与快速回退。

**策略已由 [[0009](0009-contract-governance-policy.md)] 采纳为已决策**（Envelope 字段 / SemVer 兼容 / 事件
`<name>.vN` 判别符 / 消费者契约测试入 CI），实现明确归 Phase 1 首个 Remote adapter；CDC 契约测试流水线归 D 组 D1。

<!-- ponytail: 端口各仅一实现、无远端传输，此刻加版本字段=过早脚手架（YAGNI），故只记策略不落字段。 -->

---

## ADR 编号登记（by `tests/test_adr_index.py` 自动核对）

- 0001: LLM 完成统一端口（model_gateway 接缝）
- 0002: 知识检索端口 + 用量记账接缝
- 0003: 专家目录只读端口
- 0004: 专家写侧端口
- 0005: 运行时进度事件产品字段 opaque 化
- 0006: 知识写侧端口收编
- 0007: 运行时契约剔除跨 Context 产品类型
- 0008: 专家聚合逻辑拆分（单表）
- 0009: 跨服务契约治理策略（Envelope / SemVer / CDC，实现归 Phase 1）
- 0010: Lodge resource-server（target token、online status、fail-closed 缓存）
