# ADR 0006：知识写侧端口收编（KnowledgeIndexPort）

- 状态：已采纳（Accepted）
- 日期：2026-07-28
- 相关：docs/21-通用AI平台拆分架构与落地方案 §11「知识逻辑平台」、[[ADR 0002]]（读侧 Search 端口 +
  IndexPort 延后声明）、[[ADR 0005]]（Runtime 事件 opaque）

## 背景

绞杀顺序 LLM✓（[[ADR 0001]]）→ 知识读✓（[[ADR 0002]] · A1）→ Expert 读✓（[[ADR 0003]]）→ Expert 写✓
（[[ADR 0004]]）→ Runtime 事件 opaque✓（[[ADR 0005]]）→ **知识写（本 ADR）**。

[[ADR 0002]] §「收编范围与延后」显式把 `KnowledgeIndexPort` 延后：索引写入的全部消费方
（`assistant_conversations`/`group_messaging` 归档、`environment_projection` outbox）事务耦合且一致性关键，
当时判「此刻造会话无关 IndexPort = 过早脚手架（YAGNI），待 Phase 2 index 远端化立项再切」。本 ADR 即立项收编
**写侧接缝**——与读侧 `KnowledgeSearchPort` 同构。

现状缺陷：知识写侧活在独立 Context `knowledge_indexing`，其 `public.py` 只是 6 个会话级 entrypoint 函数的
**扁平再导出**——无 Protocol 端口、无本地适配器、无 `build_local_*_port` 工厂。3 个跨 Context 消费方直接
`import` 这些函数并传自己的 `session`，正是 [[ADR 0002]] 描述的「会话耦合、Phase 2 无法一处切到
`RemoteKnowledgeAdapter`」的调用形态。

## 决策 · KnowledgeIndexPort

1. `knowledge_indexing/contracts.py` 追加 `KnowledgeIndexPort(Protocol)`——**会话无关**签名，复用同文件既有
   命令/结果类型 `IndexTextCommand`/`IndexedDocument`。端口只含跨 Context **实测消费**的 3 个方法：
   `index_text` / `remove_document_index` / `list_documents`。
2. `knowledge_indexing/infrastructure/local_adapter.py` 新增 `LocalKnowledgeIndexAdapter(session)`：构造期绑定
   调用方 session（保留事务/数据可见性），委托既有 `KnowledgeIndexing` use-case →
   `SqlAlchemyDocumentIndexGateway` → 模块级 `sqlalchemy_index.*`（既有 monkeypatch 点不变）。加 `_assert_protocol()`
   编译期符合性断言。直连 use-case+gateway（不引 entrypoints/public），规避 infra→entrypoints 反向与 public↔adapter 环。
3. `knowledge_indexing/public.py` 暴露 `build_local_knowledge_index_port(session) -> KnowledgeIndexPort`
   ——**Phase 2 换 `RemoteKnowledgeIndexAdapter` 的唯一切换点**——并再导出 `KnowledgeIndexPort`。
4. 3 个跨 Context 写消费者改经端口：`assistant_conversations` `PublishedConversationArchiveAdapter`、
   `group_messaging` `OrganizationalMemoryArchiveAdapter`（构造期 `self._index = build_local_knowledge_index_port(session)`）、
   `environment_projection` `projection_store` 模块级 `replace_archived_snapshot`/`_all_documents`（函数内取端口）。

## 收编范围与延后

- **只造接缝，不做 Remote 本体**：不引入 `RemoteKnowledgeIndexAdapter` 与 outbox 远端同步——那是 Phase 2。
- **端口只含 3 方法**：`index_file`/`index_feishu_document`/`move_document` 仅 `app/api` 消费（扫描面外），
  原样保留为会话级函数不入端口（遵 YAGNI + [[ADR 0002]] A1「端口只含 search」先例）。future 跨 Context 写消费者
  出现时再补端口方法。
- `LegacyConversationArchiveAdapter` 走注入的 `self._ingest` callable（monkeypatch 兼容面），不动。

## 后果

- 正向：知识写侧有了单一可远端替换接缝；[[ADR 0002]]「IndexPort 延后」债务消除；读写两侧接缝闭合
  （docs/21 §11 知识逻辑平台第一刀）。新增直连会话级写 entrypoint 被守卫阻断。
- 事务/一致性（[[ADR 0002]] 当初延后的核心顾虑）：适配器绑**调用方 session**，不自建 session/不 commit，
  与 3 处现状同一事务边界；outbox 驱动的 `group_messaging`/`environment_projection` 归档仍在 worker 租约 session 内落库。
  `publish_events=False` 作 `IndexTextCommand` 字段原样透传——行为字节级不变。
- 债务：index 远端 adapter 本体 + outbox 远端同步仍属 Phase 2。

## 守卫

`tests/test_architecture_boundaries.py`：
- `test_knowledge_index_flows_through_port_seam`：AST 扫描 `app/contexts`，除 `knowledge_indexing` 自身外，
  任何文件直引会话级 `index_text`/`remove_document_index`/`list_documents` 即判越界（应经端口）。

自证：`tests/test_knowledge_index_port.py` 证 `build_local_knowledge_index_port(session)` 的 3 方法确经
use-case + gateway 路由至底层写函数，`index_text` 透传 `publish_events`、`list_documents` 透传 `limit`，无需真实 DB。
