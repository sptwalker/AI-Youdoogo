# ADR 0003：专家目录只读端口（Expert Directory Port）

- 状态：已采纳（Accepted）
- 日期：2026-07-27
- 相关：docs/21-通用AI平台拆分架构与落地方案（Phase 0）§13-B、[[ADR 0001]] LLM 完成统一端口、[[ADR 0002]] 知识检索端口 + 用量记账接缝

## 背景

通用AI平台拆分绞杀顺序 LLM✓（[[ADR 0001]]）→ 知识✓（[[ADR 0002]] · A1）→ **Expert** → Runtime。
`ai-expert-platform` 的第一刀。docs/21 §13-B 列了两条解耦项：

1. **①「让 Expert public API 不再接收 AsyncSession」**——`expert_management/public.py` 的公开函数全部
   首参 `AsyncSession`，跨 Context 消费者直接 `import` 这些会话级函数并传 session，是会话耦合、无法
   远端替换的调用形态。要 Phase 1 换 `RemoteExpertAdapter`，须先让跨 Context 消费方经**同一个可远端
   替换的端口**。
2. **②「把 OrgExpertMember 与 ExpertExecutionDefinition 分开」**——写侧（create/update/delete/seed）
   与「组织成员/发布资产」强耦合。

本 ADR **只做 ①的读侧**，与 [[ADR 0002]] A1（KnowledgeSearchPort，只切只读 search）完全同构。

## 决策 · ExpertDirectoryPort

1. `expert_management/contracts/directory.py` 新增 `ExpertDirectoryPort(Protocol)`——**会话无关**签名，
   覆盖 5 个跨 Context 读方法（`get_execution`/`get_roster`/`list_roster`/`list_department_roster`/
   `count_by_department`），复用既有契约类型 `ExpertExecutionSnapshot`/`ExpertRosterSnapshot`/
   `DepartmentExpertCount`（契约层跨 Context 可引，与 model_gateway/knowledge 同规则）。
2. `expert_management/infrastructure/directory_adapter.py` 新增 `LocalExpertDirectoryAdapter(session)`：
   构造期绑定调用方 session（保留事务/数据可见性），柯里化后转调 Context 内既有查询装配
   `SQLAlchemyExpertSnapshotQuery`/`SQLAlchemyExpertRosterQuery`（infra→infra，不引 entrypoints，
   行为字节级不变）。
3. `expert_management/public.py` 暴露 `build_local_expert_directory_port(session) -> ExpertDirectoryPort`
   ——**Phase 1 换 `RemoteExpertAdapter` 的唯一切换点**——并再导出 `ExpertDirectoryPort`；既有 11 个
   会话级函数原样保留（不破坏 `app/api` 与本 Context 自身，均在扫描面外或本 Context 内）。
4. 7 个 `app/contexts` 内跨 Context 读消费者改经端口：`agent_execution` 的 `expert_snapshot_adapter`、
   `operational_analytics` 的 `agent_adapters`、`task_management` 的 `adapters`/`legacy_workflow`、
   `connector_management` 的 `adapters`、`assistant_conversations` 的 `adapters`（仅 `list_roster` 读调用）、
   `environment_projection` 的 `published_sources`、`organization_structure` 的 `adapters`（`list_department`/
   `count`）。

## 收编范围与延后

- **只切读侧，写侧（②）延后**：`create/update/delete/seed` 与组织成员/发布资产强耦合，属 docs/21 §13-B ②
   「拆 OrgExpertMember 与 ExpertExecutionDefinition」。此刻为写侧造会话无关端口 = 过早脚手架（YAGNI），
   待 ② 立项时再切。
- **写消费者债务清单（本轮不动、读侧守卫不纳入）——已由 [[ADR 0004]] 写侧端口收编**：
  - `organization_structure/entrypoints/operations.py`（create/update/delete）
  - `organization_structure/infrastructure/adapters.py`（seed）
  - `environment_projection/infrastructure/archivist.py`（seed）
  - `assistant_conversations/infrastructure/adapters.py`（create）

## 后果

- 正向：专家目录读侧有了单一可远端替换接缝；跨 Context 读消费者一律经工厂拿端口，新增直连被守卫阻断。
- 债务：写侧 4 处消费者仍直引会话级函数——属 ② 待办面，不在本轮读侧守卫内；`app/api`、Context 自身仍用
   会话级函数，属迁移期兼容面。

## 守卫

`tests/test_architecture_boundaries.py`：
- `test_expert_directory_flows_through_port_seam`：AST 扫描 `app/contexts`，除 `expert_management` 自身外，
  任何文件直引会话级 `get_expert_execution`/`get_expert_roster`/`list_expert_roster`/
  `list_department_roster`/`count_by_department` 即判越界（应经端口工厂）。**写函数名不纳入**（② 再收）。

自证：`tests/test_expert_directory_port.py` 证 `build_local_expert_directory_port(session)` 构造的端口把
`get_execution`/`list_roster` 路由至既有 `SQLAlchemyExpert*Query`，无需真实 DB。
