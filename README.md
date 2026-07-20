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
