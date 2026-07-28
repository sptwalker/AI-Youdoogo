# ADR 0004：专家写侧端口（Expert Provisioning Port）

- 状态：已采纳（Accepted）
- 日期：2026-07-27
- 相关：docs/21-通用AI平台拆分架构与落地方案（Phase 0）§13-B ①、[[ADR 0001]] LLM 完成统一端口、
  [[ADR 0002]] 知识检索端口 + 用量记账接缝、[[ADR 0003]] 专家目录只读端口

## 背景

通用AI平台拆分绞杀顺序 LLM✓（[[ADR 0001]]）→ 知识✓（[[ADR 0002]] · A1）→ Expert 读✓（[[ADR 0003]]）
→ **Expert 写（本 ADR）** → Runtime。

docs/21 §13-B ①「让 Expert public API 不再接收 AsyncSession」的读侧已由 [[ADR 0003]] 收编。写侧四个
会话级函数 `create_expert`/`update_expert`/`delete_expert`/`seed_expert` 仍被跨 Context 消费者直接
`import` 并传 session——[[ADR 0003]] 已把这 4 处列为「写消费者债务」。这是 Phase 1 换 `RemoteExpertAdapter`
时无法一处改道的最后一类调用形态。

## 决策 · ExpertProvisioningPort

1. `expert_management/contracts/provisioning.py` 新增 `ExpertProvisioningPort(Protocol)`——**会话无关**签名，
   覆盖 4 个跨 Context 写方法（`create`/`update`/`delete`/`seed`）。`permission_scope`/`tools` 仍收 `dict`/
   `list`，JSON 序列化在适配器内完成（与既有会话级写函数对齐）。复用既有契约 `ExpertRosterSnapshot`。
2. `expert_management/infrastructure/provisioning_adapter.py` 新增 `LocalExpertProvisioningAdapter(session)`：
   构造期绑定调用方 session，转调 Context 内既有装配 `build_expert_management_application(session)`
   （composition.py）的 `create/update/delete/seed(Command)`，命令映射与 `_json` 序列化平移复刻
   `entrypoints/operations.py`，行为字节级不变。**不引 entrypoints（避免 infra→entrypoints 反向），也不引
   public（避免 public↔adapter import 环）**——与 [[ADR 0003]] 读侧适配器同一规避思路。
3. `expert_management/public.py` 暴露 `build_local_expert_provisioning_port(session) -> ExpertProvisioningPort`
   ——**Phase 1 换 `RemoteExpertProvisioningAdapter` 的唯一切换点**——并再导出 `ExpertProvisioningPort`；
   既有会话级写函数原样保留（不破坏 `app/api` 与本 Context 自身，均在扫描面外或本 Context 内）。
4. 4 处 `app/contexts` 内跨 Context 写消费者改经端口：`organization_structure` 的 `entrypoints/operations`
   （create/update/delete）、`organization_structure` 的 `infrastructure/adapters`（seed）、
   `environment_projection` 的 `infrastructure/archivist`（seed）、`assistant_conversations` 的
   `infrastructure/adapters`（create，唯一传 `owner_user_id` 的写者）。

## 收编范围与延后

- **只造写侧端口接缝，不拆物理表**：`agent_role` 单表不动，不做 OrgExpertMember/ExpertExecutionDefinition
  物理拆分，也不做 Release 版本化。此刻拆表 = 跨 6 层的高风险纵切，属 docs/21 §13-B ② 更深增量，待其立项。
- 本 ADR 完成后 docs/21 §13-B ①「Expert public API 不再接收 AsyncSession」**读写两侧闭合**；② 物理拆分仍未动。

## 后果

- 正向：专家写侧有了单一可远端替换接缝；[[ADR 0003]] 记录的 4 处写消费者债务全部消除；跨 Context 写消费者
  一律经工厂拿端口，新增直连被守卫阻断。
- 债务：`provisioning_adapter._json` 与命令映射（≈40 行）与 `entrypoints/operations.py` 重复——接缝成本，
  ② 拆模型时随命令映射归并；`app/api`、Context 自身仍用会话级写函数，属迁移期兼容面。

## 守卫

`tests/test_architecture_boundaries.py`：
- `test_expert_provisioning_flows_through_port_seam`：AST 扫描 `app/contexts`，除 `expert_management` 自身外，
  任何文件直引会话级 `create_expert`/`update_expert`/`delete_expert`/`seed_expert` 即判越界（应经端口工厂）。

自证：`tests/test_expert_provisioning_port.py` 证 `build_local_expert_provisioning_port(session)` 构造的端口把
`create`/`seed`/`delete` 路由至 `build_expert_management_application` 装配的 application，且 `permission_scope`/
`owner_user_id` 经命令正确透传，无需真实 DB。
