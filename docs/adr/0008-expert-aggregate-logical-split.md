# ADR 0008：专家聚合逻辑拆分（OrgExpertMember / ExpertExecutionDefinition，单表）

- 状态：已采纳（Accepted）
- 日期：2026-07-28
- 相关：docs/21-通用AI平台拆分架构与落地方案 §5「专家模型如何拆」/ §13-B②、[[ADR 0004]] 专家写侧端口
  （其「此刻拆表 = 跨 6 层高风险纵切，待立项」由本 ADR 部分兑现——只做逻辑拆，物理拆表仍留 Phase 3）、
  [[ADR 0003]] 专家目录只读端口

## 背景

绞杀链 [[ADR 0001]]→[[ADR 0007]] 已把跨 Context 依赖（LLM／知识读写／Expert 读写／Runtime 事件与类型）
全部收进端口与不透明契约，§13-B 代码解耦 DoD 达成。B 组只剩最后一条：**§13-B② 把 `agent_role` 单聚合拆成两个
聚合边界**。

`agent_role` 一行同时承载两个不同关注点，且在每一层都被当成**一个统一聚合**读写（domain `ExpertProfile`
扁平 17 字段、`update()`/`apply_seed()` 单一变更面、repo `_to_domain/_from_domain/save`、三条命令、
`app/agents` legacy、`ai_quality` 都读整行）：

- **「这个人属于哪个部门」**——组织归属／身份／生命周期：code/name/title/tier/department_id/report_to_id/
  owner_user_id/is_seed/is_active；
- **「这次执行用哪个 Prompt/模型/工具」**——执行定义：prompt_template/model_role/permission_scope/tools/duty。

docs/21 §5 原则：**二者不是同一聚合，不应共用同一变更面、不应在同一事务里被改。**

## 决策 · 单表下逻辑拆两聚合

选定**逻辑拆聚合（单表）**档（另两档：物理拆两表、完整版本化 release——均更高风险，见「延后」）。

1. **Domain 拆两子聚合 + 组合根**（`domain/models.py`）：
   - `OrgExpertMember`：org 字段 + 变更面 `revise`（部分更新，每字段可空）/`apply_seed`/`delete`，`tier` 校验归此聚合。
   - `ExpertExecutionDefinition`：exec 字段（含 `duty`，docs/21 §5 归执行侧）+ `revise`（空 prompt 保留现有）/
     `apply_seed`，`model_role` 校验归此聚合。
   - `ExpertProfile` 降为**组合根**：只持 `id/version/create_time + member + execution`；`is_deleted` 委派
     `member`。**聚合边界即变更面**——org 变更不触碰 exec，反之亦然（本 ADR 唯一实质结构，Phase 3 物理拆表即机械提升）。
2. **命令保持扁平，拆分在 use_cases 内分发**（plan §2 之 B 案，非引入分组 dataclass）：`CreateExpertCommand`/
   `SeedExpertCommand`/`UpdateExpertCommand` **零改**——它们是本 Context 内部 DTO，分组只会徒增两套
   fields/patch dataclass。`use_cases` 把命令入参切成 org/exec 两段，分别构造/分发给两子聚合。ponytail：命令
   分组不产生跨 Context 价值，聚合边界已由 domain 承载，故取更小 diff。
3. **Repository 单行 ↔ 两子聚合**（`sqlalchemy_repository.py`）：`_to_domain` 从一行 `AgentRole` 重建两子聚合，
   `_from_domain`/`save` 从 `expert.member.*`+`expert.execution.*` 写回同一行。列映射、`_dump`/`_load_*` 不变。
4. **Seed 幂等比对键**抽 `_seed_fingerprint(expert)`（9 字段跨两子聚合读取），前后对照逻辑字节不变。

## 收编范围与延后

- **不改 DB、不动快照契约、不碰跨 Context**：`agent_role` 表、`ExpertRosterSnapshot`/`ExpertExecutionSnapshot`
  两快照、`sqlalchemy_query.snapshot_from_role`/`roster_snapshot_from_role`（直接读 ORM 行）、
  `ExpertDirectoryPort`/`ExpertProvisioningPort`（kwargs 签名不变）、`ai_quality` 的 `SQLAlchemyEvaluationSubject`、
  `app/agents` legacy、workflow_runtime——**全部零改**。这是「逻辑拆（单表）」相对物理拆表的核心风险收敛点。
- **单事务是单表之果，非遗漏**：本轮两子聚合仍在同一 UoW 落同一行。docs/21 §5「不应同一事务里改」的**独立
  事务**属性随 **Phase 3 物理拆表**到位（含版本化不可变 `ExpertRelease` + `expert_release_id` 映射）；repo
  `_to_domain` 处 `# ponytail:` 注明上限与升级路径，不在单表下强行拆两事务（会引入本轮未选的部分失败语义）。
- [[ADR 0004]] 标注的「跨 6 层高风险纵切」= 物理拆表 + 独立事务 + release 版本化，明确留 Phase 3，不在本轮。

## 后果

- 正向：org 与 exec 各有独立聚合与自校验变更面，§13-B② 逻辑边界闭合；Phase 3 物理拆表只需把两子聚合各自落表、
  变更面已就位。跨 Context 消费端与快照零改，无迁移、无行为漂移。
- 债务：单表单事务仍是过渡态（Phase 3 补独立事务/版本化）；repo 承担一行 ↔ 两聚合的重建/写回映射（约 15 行，
  接缝成本）。

## 守卫

- `tests/test_expert_roster_application.py` 新增域层聚合边界自证：
  - `test_aggregate_boundary_org_change_does_not_touch_execution`：org `revise` 后 exec 字段恒等；
  - `test_aggregate_boundary_execution_change_does_not_touch_org`：exec `revise`（空 prompt 保留）后 org 恒等；
  - `test_each_aggregate_validates_its_own_enum`：非法 tier 由 org 拒、非法 model_role 由 exec 拒——两聚合各守
    信任边界（遵 ponytail「NOT be lazy」，校验迁移前后字节不变）。
- 既有 create/seed 幂等/部分 update/personal owner/唯一冲突用例行为断言不变，兜底行为字节等价。

自证：`test_seed_is_idempotent_and_preserves_existing_prompt` 经两子聚合 `apply_seed` 后，管理员改写的 prompt
仍保留、`_seed_fingerprint` 前后对照仍判「未变→不重复 publish」，幂等语义不回归。
