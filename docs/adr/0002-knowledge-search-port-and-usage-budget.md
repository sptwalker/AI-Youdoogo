# ADR 0002：知识检索端口 + 用量记账接缝（Knowledge Search Port / Usage Budget Public）

- 状态：已采纳（Accepted）
- 日期：2026-07-27
- 相关：docs/21-通用AI平台拆分架构与落地方案（Phase 0）、docs/15-混合检索与语义层设计、[[ADR 0001]] LLM 完成统一端口

## 背景

docs/21 §13 Phase 0 backlog 尚余两笔债务，均属「先抽象，再绞杀」的接缝收敛：

1. **知识检索接缝（A1）**：`ai-knowledge-service` 逻辑平台的第一刀是「先切只读 Search」（§11）。
   现状 `agent_execution` 跨 Context 直调 `knowledge_retrieval.entrypoints.operations.search_knowledge`
   （会话级函数）。该 entrypoint 是会话耦合、无法远端替换的调用形态；要 Phase 2 换 `RemoteKnowledgeAdapter`，
   须先让跨 Context 消费方经**同一个可远端替换的端口**。
2. **用量记账债务（A2）**：ADR 0001 把 LLM「完成」语义收进 model_gateway，但**用量记录**（token 记账/预算）
   显式挂账未迁——4 个 Context（`agent_execution`/`ai_quality`/`organizational_memory`/`knowledge_retrieval`）
   与 `model_gateway.public` 仍直连 legacy 兼容层 `app.llm.usage`。实测该层已是 `usage_budget` Context 的
   facade，只差一个可被 Context 合法引用的 `public` 接缝。

## 决策

### A1 · KnowledgeSearchPort

1. 在 `knowledge_retrieval/contracts.py` 新增 `KnowledgeSearchPort(Protocol)`——**会话无关**签名
   `async search(query) -> SearchKnowledgeResult`（契约层跨 Context 可引，与 model_gateway 同规则）。
2. `knowledge_retrieval/infrastructure/local_adapter.py` 新增 `LocalKnowledgeSearchAdapter(session)`：
   构造期绑定调用方 session（保留事务/数据可见性），委托既有 `KnowledgeRetrieval` use-case →
   `SqlAlchemyKnowledgeRetrievalGateway` → 模块级 `sqlalchemy_retrieval.search`（既有 monkeypatch 点不变）。
3. `knowledge_retrieval/public.py` 暴露 `build_local_knowledge_search_port(session) -> KnowledgeSearchPort`
   ——**Phase 2 换 `RemoteKnowledgeAdapter` 的唯一切换点**——并再导出 `KnowledgeSearchPort`。
4. `agent_execution/infrastructure/current_adapters.py`（唯一 `app/contexts` 内跨 Context 消费者）改经端口。

### A2 · usage_budget.public

1. 新增 `usage_budget/public.py`——正典暴露 `record_usage` / `extract_usage` / `budget_exceeded`
   （逻辑自 `app.llm.usage` 平移；`extract_usage` 改鸭子类型只读 `usage_metadata`，**不引 langchain**，
   故该 public 对「完成」语义零依赖）。
2. 4 个 Context 调用点 + `model_gateway.public`（`extract_usage`）改指 `usage_budget.public`。
3. `app.llm.usage` 降为薄再导出 shim，仅供 `app/agents`、`app/services` 等迁移期 legacy facade（`test_llm_usage`/
   `test_budget` 的旧导入路径保持可用）。死代码 `BudgetExceededError`（定义未抛/未引）、`_check_daily_budget`
   （私有未用）随迁移删除。

## 收编范围与延后

- **A1 只切 Search，`KnowledgeIndexPort` 延后**：索引写入的全部消费方（`assistant_conversations`/
  `group_messaging` 归档、`environment_projection` outbox）均**事务耦合**且一致性关键；docs §11 亦将
  index 远端化排在 Search 之后并要求 outbox 同步。此刻造一个会话无关的 IndexPort = 过早脚手架（YAGNI），
  待 Phase 2 index 远端化立项时再切。**（更新：写侧接缝已由 [[ADR 0006]] 收编，index 远端 adapter 本体仍属 Phase 2。）**
- **A1 端口只含 `search`**：`app/contexts` 内当前唯一跨 Context 知识消费者只用 search；`answer_knowledge`
  的消费方在 `app/api`（扫描面外）。future 跨 Context `answer` 消费者出现时再补端口方法。

## 后果

- 正向：知识检索有了单一可远端替换接缝；用量记账收归 `usage_budget` 单一 owner；两处新增直连均被守卫阻断。
- 债务：`app/agents`、`app/services` 的 legacy facade 仍引 `app.llm.usage` shim 与 `search_knowledge`
  entrypoint——属迁移期兼容面，随 legacy 绞杀递减，不在本轮扫描门禁内。

## 守卫

`tests/test_architecture_boundaries.py`：
- `test_knowledge_search_flows_through_port_seam`：AST 扫描 `app/contexts`，除 `knowledge_retrieval` 自身外，
  任何文件直引会话级 `search_knowledge`/`answer_knowledge`/`diagnose_retrieval_arms` 即判越界（应经端口）。
- `test_usage_recording_flows_through_usage_budget_public`：`app/contexts` 下禁止 import `app.llm.usage`。

自证：`tests/test_knowledge_search_port.py` 证 `build_local_knowledge_search_port(session).search()`
确经 use-case + gateway 路由至 `sqlalchemy_retrieval.search`，并对空查询短路。
