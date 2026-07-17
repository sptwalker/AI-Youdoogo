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
| 智能体编排 | **自研状态机**（`app/services/task_flow.py` + `app/agents/scheduler.py`）；LangGraph 1.x 暂缓——2026-07-12 阶段3决策：先自研轻量状态机跑通任务卡闭环，确有编排复杂度再引入并做 POC |
| 飞书 | 自研异步 httpx 客户端 `app/integrations/feishu/`（不用 lark-oapi） |
| 前端 | React + Ant Design Pro（**阶段2才初始化**） |
| 质量 | Ruff + Mypy + Pytest（提交前三件套必须全绿） |

## 目录规则

```
app/
├── api/v1/          # 接口层（薄，只做路由+校验+调service）
├── core/            # config/logging/database/exceptions
├── models/          # ORM（base.py 通用字段Mixin：id/create_time/update_time/is_delete）
├── schemas/         # Pydantic 请求响应模型
├── services/        # 业务逻辑层
├── agents/          # 智能体核心逻辑（阶段2起）
├── knowledge/       # 知识库模块（阶段1起）
├── llm/             # 多模型网关（factory/fallback/health/validate/roles）
├── integrations/    # 外部平台（feishu/ ...）
└── utils/           # 通用工具
```

**目录/表/服务只在当前阶段用到时创建，禁止为未来阶段预建空壳。** 新增一级目录须先修订 docs/05。

## 开发铁律

1. **文档优先**：无 docs 设计文档不开发业务代码；文档过时先改文档
2. **单模块增量**：一次只开发一个独立模块，先确认思路再编码，完成验收再继续
3. **全类型注解 + docstring**：mypy 无类型缺失；核心逻辑注释说明设计思路与边界
4. **密钥禁止硬编码**：可存 `.env`（`app/core/config.py`）或 `sys_config`（系统配置页 UI 填写，`is_secret=true`）；app 经 `app/core/runtime_config.py` 覆盖层读取（sys_config 覆盖 .env）；list 接口对密钥脱敏、审计 detail 打码。**LLM 模型密钥走 `ai_provider` 卡片（「AI 配置」页填，list 只回 hint 末4位）**；embedding/飞书/TD 仍走 sys_config/.env
5. **接口双校验**：所有接口必须有权限校验 + 参数校验；统一返回 `{code, msg, data}`
6. **人工兜底**：权限、数据修改、核心决策代码必须人工审核；所有AI输出可编辑/驳回/终止
7. **提交前**：`uv run ruff check .` + `uv run mypy app` + `uv run pytest` 全绿

## 常用命令

```powershell
docker compose up -d                      # PG/Redis/MinIO（三容器需 healthy）
uv sync                                   # 装依赖
uv run alembic upgrade head               # 迁移
uv run uvicorn app.main:app --reload      # 启动（/api/v1/health/deps 自检依赖）
uv run pytest -q                          # 测试
uv run ruff check . ; uv run mypy app     # 质量门
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
