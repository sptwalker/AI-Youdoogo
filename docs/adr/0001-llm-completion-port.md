# ADR 0001：LLM 完成统一端口（model_gateway 接缝）

- 状态：已采纳（Accepted）
- 日期：2026-07-27
- 相关：docs/21-通用AI平台拆分架构与落地方案（Phase 0）、docs/09-模型网关设计、docs/20-DDD领域边界与分层架构规范

## 背景

docs/21 的北极星是把单体绞杀成 4 个逻辑平台，其中 `ai-model-gateway`（LLM）可行性最高（8/10）。
Phase 1 的目标是给模型调用加 `RemoteLlmAdapter`，让完成请求可切到远端网关服务；要能「一处切换、全量改道」，
前提是**所有 LLM 完成调用都经由同一个可远端替换的端口**。

现状核查（Phase 0 本轮实测）：
- DDD 应用层已 100% 干净，`agent_execution` 已有 remote-ready 的端口 + 纯契约（无 langchain）。
- 但端口 Protocol 位于 `agent_execution/application/ports.py`，跨 Context 不可引用
  （`test_context_dependencies_point_inward` 禁止跨 Context 引 `application` 层），无法被其他 Context 复用。
- 真正直连 LLM 完成的 infra 共 **6 个适配器家族**：`agent_execution`（规范适配器）、`ai_quality`（评分/建议/legacy）、
  `work_planning`、`organizational_memory`（蒸馏，被 assistant_conversations/group_messaging 转交）、
  `knowledge_retrieval`（问答 answer）、`connectivity`（连通探测 probe）。

## 决策

1. **新增极小 foundation Context `app/contexts/foundations/model_gateway/`**，只含
   `contracts/` + `infrastructure/` + `public.py`（不建 application/domain/entrypoints，够用即可）。
2. 正典契约与端口落在 `model_gateway/contracts/completion.py`：`LlmCompletionRequest/Response/StreamChunk/TokenUsage`
   + `LlmCompletionPort`(Protocol)。**由 `agent_execution` 平移而来**，旧位置改**别名再导出**（保持对象同一性，
   `LlmExecutionRequest is LlmCompletionRequest`），使 `agent_execution` 现有代码/测试零改动。
3. 本地实现 `LocalLlmAdapter`（`model_gateway/infrastructure/local_adapter.py`）把 langchain 消息类型隔离在文件内；
   Phase 1 的 `RemoteLlmAdapter` 将实现同一 `LlmCompletionPort`。
4. `model_gateway/public.py` 暴露 `build_local_llm_completion_port() -> LlmCompletionPort`——**这是 Phase 1
   换 `RemoteLlmAdapter` 的唯一切换点**。消费方一律经 `public` 工厂拿端口，绝不直连 `model_gateway.infrastructure`。
5. **跨层规则复用**：`contracts` 与 `public` 均不在 `internal_layers`，故其他 Context 引用
   `model_gateway.contracts` / `model_gateway.public` 合法；而 infra→infra 跨 Context 非法，天然约束消费路径。

采用 **branch-by-abstraction（先抽象，再绞杀）**：Local 与后续 Remote 适配器共存于同一端口，`public` 处二选一。

## 收编范围（Phase 0 本模块）

- **自证接缝**：`agent_execution` 组合根（`infrastructure/composition.py`）与 legacy facade（`app/agents/base.py`）
  改用 `build_local_llm_completion_port()`。
- **收编 2 处最简 B 类**：`knowledge_retrieval.answer()`（新增可注入 `port`，默认本地端口）、
  `connectivity` 的 `LLMConnectivityProbe.probe()`（空 `system_prompt` 时不前置 SystemMessage，wire 行为与旧
  `[HumanMessage("ping")]` 一致）。

## 后果

- 正向：LLM 完成有了单一可远端替换接缝；新增直连被架构守卫阻断；Phase 1 只改 `public` 即可全量改道。
- 代价/边界：
  - **usage 记录暂不迁**——仍由消费方调用 `app.llm.usage`（`record_usage`/`extract_usage`/`budget_exceeded`）。
    该口径独立于「完成」语义，列为后续债务。
  - **待迁移债务清单**：Phase 0 已全部收编，白名单清空（`_LLM_COMPLETION_MIGRATION_DEBT == set()`）。
    自此 `app/contexts` 下任何新增 LLM 完成直连都会被守卫直接判为越界，只能经 `model_gateway.public`。
  - **已收编家族**（脱离直连，经 `model_gateway.public`）：
    - `knowledge_retrieval.answer()`、`connectivity` probe、`agent_execution` composition/gateway
    - `governance/ai_quality`（评分 `CompletionEvaluationJudge` + 建议 `CompletionPromptSuggestion`，
      含 `composition.py` 与 `legacy_execution.py`；构造点 `feedback_service`/`eval_service` 同步改道）
    - `execution/work_planning`（`CompletionPlanningModelAdapter`，`workflow_planning.plan` 内建端口，
      `orchestration_service.plan` 去掉 `llm_factory` 注入）
    - `knowledge/organizational_memory`（`LlmMemoryDistillation` 收端口，`operations.distill_conversation`
      内建端口；连带清除转交方 `assistant_conversations` / `group_messaging` adapter 的 `llm_factory=get_llm_for_role`
      与 `memory_service` facade 的注入）

## 守卫

`tests/test_architecture_boundaries.py::test_llm_completion_flows_through_model_gateway_seam`：
AST 扫描 `app/contexts`，凡触碰 LLM 完成信号（import `langchain*` 或引入 `get_llm_for_role`/`create_llm`/`BaseChatModel`）
的文件，必须位于 `model_gateway` 接缝内，否则须在显式 `_LLM_COMPLETION_MIGRATION_DEBT` 白名单中；
并断言已迁移的家族不再触碰完成信号、白名单精确无冗余。
