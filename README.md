# 创想悦动AI智能公司管理和决策辅助系统

企业AI决策大脑：多AI智能体业务处理 + 辅助决策管理系统。
**AI仅有建议权，核心决议由真人管理层确认生效。**

## 从零启动

```powershell
# 1. 基础设施（需 Docker Desktop，首次拉镜像较慢）
docker compose up -d

# 2. 依赖（需 uv：irm https://astral.sh/uv/install.ps1 | iex）
uv sync

# 3. 配置：复制 .env.example 为 .env，填入各 API Key
copy .env.example .env

# 4. 数据库迁移
uv run alembic upgrade head

# 5. 启动
uv run uvicorn app.main:app --reload
# 自检：http://127.0.0.1:8000/api/v1/health/deps （PG/Redis/MinIO 应全为 ok）
```

## Durable Agent Runtime

复合任务由 PostgreSQL 持久化为 `WorkflowRun/WorkflowStep`，HTTP/SSE 只提交计划并立即返回
`queued/running` 进度；应用 lifespan 中的 outbox worker 负责租约抢占、执行、重试和真人停点恢复。
`TaskCard` 只作为 UI/验收镜像，文件交付与协作请求通过 `ToolExecution` 幂等去重。

后续接入 LangGraph 时，实现 [workflow_engine.py](app/agents/workflow_engine.py) 的
`WorkflowEngine` adapter 即可；LangGraph 不接管数据库真相源、工具副作用或人工审批。

## Graphify 项目知识图谱

本项目使用 [Graphify](https://github.com/Graphify-Labs/graphify) 生成本地代码与文档知识图谱，产物写入被 Git 忽略的 `graphify-out/`，不会进入版本库。

```bash
# 首次安装；已安装可跳过
uv tool install --upgrade graphifyy
graphify install --platform codex

# 首次或完整重建（默认同时生成交互式 HTML）
graphify .

# 日常增量更新并刷新 HTML
graphify . --update

# 查询项目结构、调用关系和模块影响范围
graphify query "知识库检索链路如何进入任务编排"
graphify path "app/knowledge" "app/agents"
```

`graphify-out/graph.html` 是默认生成的交互式可视化，`graphify-out/graph.json` 是可复用的查询索引。代码变更后运行 `graphify . --update`，完整重建运行 `graphify .`；明确不需要 HTML 时追加 `--no-viz`。

## 质量门（提交前必须全绿）

```powershell
uv run ruff check .
uv run mypy app
uv run pytest -q
```

## 文档

- 开发规则与技术栈：[CLAUDE.md](CLAUDE.md)（唯一事实源）
- 设计文档：[docs/](docs/)（01~14 篇）
- 原始前置文档存档：[docs/archive/](docs/archive/)
