# CLAUDE.md — 创想悦动AI决策大脑系统开发规则

## 项目定位

创想悦动AI智能公司管理和决策辅助系统：多AI智能体企业办公协同 + 管理决策辅助。
**红线：AI仅有建议权、分析权、辅助执行权；涉及业务调整、资金、项目、人事的决议必须真人确认生效。**

## 技术栈（唯一事实源 — 改栈先改这里，再改代码和 docs）

| 层 | 选型 |
|---|---|
| 语言/工具链 | Python 3.12 + **uv**（`uv sync` / `uv run`） |
| Web | FastAPI + Uvicorn |
| ORM | SQLAlchemy 2.0 **async** + asyncpg + Alembic |
| 校验/配置 | Pydantic v2 + pydantic-settings（`app/core/config.py` 唯一配置入口） |
| 数据库 | PostgreSQL 16（`timescale/timescaledb-ha:pg16` 镜像，内置 TimescaleDB + pgvector） |
| 缓存/文件 | Redis / MinIO |
| 大模型 | **卡片化多 Provider**（`ai_provider` 表 + 「AI 配置」页动态管理）：卡片分 daily/reasoning 档，对接 `agent_role.model_role`；档内 `is_primary` 主用 + 同档 active 作 failover；**必须建卡片，无卡片 AI 不可用（不回退 .env）**。网关在 `app/llm/`（langchain-core + langchain-openai） |
| 智能体编排 | **PostgreSQL durable runtime**（`WorkflowRun/WorkflowStep` + transactional outbox + 租约 worker）；普通单卡仍用 `task_flow.py`。LangGraph 后续只能实现 `WorkflowEngine` adapter，不得绕过持久化、幂等与真人停点 |
| 飞书 | 自研异步 httpx 客户端 `app/integrations/feishu/`（不用 lark-oapi） |
| 前端 | React + Ant Design Pro（**阶段2才初始化**） |
| 质量 | Ruff + Mypy + Pytest（提交前三件套必须全绿） |

## 目录规则

```text
app/
├── bootstrap/       # 唯一组合根：app/lifecycle/wiring、route/handler/worker 装配
├── contexts/        # 限界上下文；按 foundations 与 business 分组，叶子 Context 才拥有模型
│   ├── shared_kernel/ # 极小跨 Context 契约；当前仅稳定、与传输无关的应用错误语义
│   ├── foundations/ # Wiki/Expert/Capability/Workflow/Identity 等复用业务能力
│   └── business/    # Proposal/Meeting/Operational Analytics 等业务场景
├── platform/        # 无业务语义的技术机制：database/outbox/http/llm/cache/realtime 等
├── api/             # 迁移期 HTTP 兼容入口；新入口逐步进入各 Context/entrypoints
├── core/            # 迁移期配置、安全等兼容入口；旧异常 facade 已删除
├── models/          # 迁移期 ORM 兼容入口
├── schemas/         # 迁移期 HTTP DTO 兼容入口
├── agents/          # 迁移期 Agent runtime 兼容入口
├── llm/             # 迁移期 LLM gateway 兼容入口
└── integrations/    # 迁移期供应商 client 兼容入口
```

复杂 Context 内按需使用 `contracts/domain/application/entrypoints/infrastructure`；简单 Context 可保持少量文件，
但依赖方向必须是 Entrypoints → Application → Domain、Infrastructure → Application Ports/Domain。

**目录/表/服务只在当前阶段用到时创建，禁止预建空壳。** `app/services` 与 `app/knowledge` 已退出，禁止
恢复这两个横向 facade；新代码也禁止反向依赖 `app/models` 等迁移期实现。完整 Context Map、数据所有权和
迁移顺序以 docs/20 为准。

当前 OpenSpec 迁移的 P0～P4 已完成：Bootstrap/Database/Outbox/HTTP Runtime、Proposal、
Expert/Agent/Capability、Planning/Workflow/Task、Identity/Organization/Knowledge/Environment、
Communication/Meeting/Analytics/Governance 均已有 Context-owned 边界；HTTP route 已迁到 Context
entrypoint，route 对 ORM、旧 Service 和具体 Agent/LLM 的依赖已清除；`app/services`、`app/knowledge`、
旧 `agents/scheduler.py` 与 `agents/workflow_engine.py` 已删除。实施 ownership map、历史职责归属、退出证据
和不得回归规则见
`docs/20-DDD领域边界与分层架构规范.md` 第 11 节。

应用错误不携带 HTTP 元数据；HTTP status/code 只允许在 Bootstrap 或 Context entrypoint/HTTP adapter
中映射。旧 `AppError` 调用和 `app.core.exceptions` 兼容层已全部移除。最终门禁已通过 Ruff、Mypy、
全量非交付 Pytest、前端 test/lint/build、单一 migration head、app/worker smoke；架构门禁测试
（`test_architecture_boundaries` / `test_runtime_boundaries` / `test_governance_boundaries`）持续验证无
import cycle、无 Context→legacy 反向依赖、无重复持久化 writer，并显式阻止 `app/services`、
`app/knowledge` 与旧 `app.agents.scheduler` / `app.agents.workflow_engine` 回归。零调用门禁以 AST 真实
import 为准；架构测试中的历史路径字符串是负向样本，必须保留而不能为文本零命中删除。

## 开发铁律

1. **文档优先**：无 docs 设计文档不开发业务代码；文档过时先改文档
2. **单模块增量**：一次只开发一个独立模块，先确认思路再编码，完成验收再继续
3. **全类型注解 + docstring**：mypy 无类型缺失；核心逻辑注释说明设计思路与边界
4. **密钥禁止硬编码**：可存 `.env`（`app/core/config.py`）或 `sys_config`（系统配置页 UI 填写，`is_secret=true`）；app 经 `app/core/runtime_config.py` 覆盖层读取（sys_config 覆盖 .env）；list 接口对密钥脱敏、审计 detail 打码。**LLM 模型密钥走 `ai_provider` 卡片（「AI 配置」页填，list 只回 hint 末4位）**；embedding/飞书/TD 仍走 sys_config/.env
5. **接口双校验**：所有接口必须有权限校验 + 参数校验；统一返回 `{code, msg, data}`
6. **人工兜底**：权限、数据修改、核心决策代码必须人工审核；所有AI输出可编辑/驳回/终止
7. **提交前**：后端 `ruff + mypy + pytest -m "not delivery_contract"`、前端 `npm run test + lint + build` 全绿；兼容层退出后的基线为全量收集 707 项 Pytest；系统级部署契约由 CI 独立环境验证

## 常用命令

```powershell
docker compose up -d                      # PG/Redis/MinIO（三容器需 healthy）
uv sync                                   # 装依赖
uv run alembic upgrade head               # 迁移
uv run uvicorn app.main:app --reload      # 启动（/api/v1/health/deps 自检依赖）
uv run pytest -q -m "not delivery_contract" # 后端测试（部署契约由 CI 独立验证）
uv run ruff check . ; uv run mypy app     # 质量门
cd frontend ; npm run test ; npm run lint ; npm run build
```

## Git

- `main` 生产稳定分支（禁止直接提交）/ `dev` 开发主分支 / `feature/xxx` / `fix/xxx`
- Conventional Commits：`feat/fix/docs/refactor/test/chore: 描述`

## docs/ 索引

| 文档 | 内容 |
|---|---|
| 01-需求规格说明书 | 目标/范围/功能/非功能/权责边界 |
| 02-总体架构设计 | 七层架构/业务流转/技术栈 |
| 03-数据库设计 | 表设计（阶段1所需字段级DDL已细化） |
| 04-智能体角色规范 | 各部门Agent职责/任务卡规范 |
| 05-开发规范手册 | 目录/代码/Git/接口/安全规范 |
| 06-里程碑计划 | 压缩版14~16周（阶段0~6） |
| 07-提示词手册 | Claude Code 开发提示词模板 |
| 08-验收与运维规范 | 验收标准/部署/备份/监控 |
| 09-模型网关设计 | 复用移植方案/角色模型映射/failover链 |
| 10-飞书集成设计 | 已有能力/缺口backlog |
| 11-数据接入设计 | 三类数据源接入提纲/业务API盘点 |
| 12-生产部署与运维手册 | 阶段6：生产compose/Dockerfile/nginx/备份/监控/用户操作手册 |
| 13-公司管理框架设计与开发规划 | 生产开发阶段：组织树/AI员工/知识库范围/权限/协作空间/三层执行体系/管理员配置（F1~F5） |
| 14-任务编排层设计 | AI助理多步骤任务编排：产出管道（阶段A修取数→交付断链）+ DAG编排层（阶段B）/红线停点 |
| 15-混合检索与语义层设计 | 向量+关键词(pg_trgm)多路召回+RRF融合(+分期rerank)提检索质量；轻量指标/术语字典统一口径 |
| 16-架构评审与改进路线图 | 系统级评审(B+)+生产硬化路线H1~H4：密钥加密/行级隔离/注入防护/状态迁Redis(P0)→可靠性→评估驱动→智能深化 |
| 18-多人AI即时通讯群组设计 | 多人真人+多AI即时群聊：飞书组织同步/SSO登录/SSE广播+Redis pub/sub实时/群成员/未读/文件/入库（分期I1~I7） |
| 19-飞书登录配置与运维 | 应用本地飞书 OAuth、身份绑定、上线前置与回滚 |
| 20-DDD领域边界与分层架构规范 | Wiki/Expert/Tool/API/Workflow 等基础底座域、业务域、Platform、Context内分层及渐进迁移规则（已生效） |
| 21-通用AI平台拆分架构与落地方案 | 四平台拆分总方案/先立契约后绞杀/Go-No-Go门禁/物理独立部署主动推迟（§11） |
| 22-数据迁移对账与回滚设计 | 拆分期双写/对账指纹/一键回滚（local↔remote 灰度切换的数据安全底座） |
| 23-Expert平台拆分与网关灰度Runbook | 专家拆分线协议/内部JWT事件门禁/远端工具调用环（§6.8）+ LLM local→remote 灰度切换与回滚操作手册 |
| 24-Workflow-Runtime收口设计 | durable WorkflowRun/Step 七步逻辑收口/engine 创建期溯源戳/drain 闸 step6+7/物理独立仓推迟与升级路径 |

## 平台分拆收尾状态（docs/21～24，逻辑边界已收口）

按 docs/21「先立契约、后绞杀」把四个通用能力域从主仓抽出。主仓保留 `Remote*Adapter` 客户端 +
`*_mode`（local/remote）+ canary 灰度百分比，默认 `local`、canary=0，可一键回退；写侧（knowledge_index）
硬切不灰度（不双写）。

| 平台 | 卫星仓（相对路径 / 包名） | 主仓客户端 | 收口状态 |
|---|---|---|---|
| LLM 网关 | `../ai-model-gateway`（`gateway`） | `model_gateway` RemoteAdapter | chat 契约对等 + 服务端落地；embedding/rerank 端点已建、消费侧刻意留白（分期，非缺口） |
| 知识服务 | `../ai-knowledge-service`（`service`） | `knowledge_retrieval` / `knowledge_indexing` RemoteAdapter | search/index 契约对等 + 服务端落地 |
| 专家平台 | `../ai-expert-platform`（`expert`） | `agent_execution` Remote 执行 + 工具调用环 | execution 契约对等 + 服务端落地；远端工具环（文本协议）默认关可回滚 |
| 工作流运行时 | 主仓内 `execution/workflow_runtime` | durable WorkflowRun/Step + engine 溯源戳 | 逻辑边界收口；**物理独立仓按 docs/21 §11 主动推迟**（非未完成） |

- **安全红线**：三卫星仅持验证公钥（`internal_jwt_public_key`，留空即启动失败）；私钥只在主仓
  `mint_internal_token` 签发，ES256 锁定，强制校验 aud/iss/scope。**卫星服务端本身不签名。**
- **物理独立部署 = 主动推迟，不是没做完**：首期只落地逻辑边界 + 契约对等 + 服务端；按 §11 Go/No-Go，
  容量/门禁达标后再打独立 Deployment（升级路径见 docs/24）。三卫星当前为 walking-skeleton 级实现
  （echo/最小执行器、易失状态、单卡无 failover），承接线上流量前须按各自 `# ponytail:` 升级路径补实。
- **三卫星质量门**：各自 `ruff + mypy + pytest`（覆盖率地板 89/84/88，实际 91/86/90）+ 最小 GitLab CI
  （`dev`/MR 触发，runner tag=AI，python:3.12-slim）；均已托管 GitLab、`dev` 为开发主分支。
