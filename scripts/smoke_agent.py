"""真实冒烟：用 .env 的 DeepSeek 密钥跑一遍运营日报智能体（内存 SQLite，无需 Docker）。

用法：uv run python scripts/smoke_agent.py
验证：真实模型能按运营总监提示词产出结构化日报；成功/失败都落留痕记录。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # 允许以脚本方式直跑
sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]  # Windows GBK 控制台兼容

from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from app.contexts.business.operational_analytics.entrypoints import (  # noqa: E402
    agent_operations as ops,
)
from app.core.config import get_settings  # noqa: E402
from app.models import Base  # noqa: E402
from app.models.agent import AgentRole  # noqa: E402
from app.models.llm_log import LlmCallLog  # noqa: E402

_ROWS = [
    {
        "stat_date": "2026-07-11", "product": "产品A",
        "dau": 1234, "new_users": 56, "retention_d1": 42.5,
    },
    {
        "stat_date": "2026-07-11", "product": "产品B",
        "dau": 2000, "new_users": 88, "retention_d1": 38.0,
    },
]


async def _run() -> int:
    if not get_settings().deepseek_api_key:
        print("未配置 DEEPSEEK_API_KEY（请在 .env 中填入），冒烟跳过。")
        return 1

    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db:
        db.add(
            AgentRole(
                name="平台运营部总监助理",
                code=ops.OPS_DIRECTOR_CODE,
                prompt_template=(
                    "你是创想悦动平台运营部的AI运营总监。只依据数据分析，禁止臆造。"
                    "日报固定包含【核心指标概览】【异常与关注点】【运营建议】三部分。"
                ),
                model_role="daily",
            )
        )
        await db.commit()
        import uuid as _uuid

        operator = _uuid.uuid4()
        record = await ops.create_daily_report(
            db,
            stat_date="2026-07-11",
            rows=_ROWS,
            operator_id=operator,
            notify=False,
        )
        log = (await db.execute(select(LlmCallLog))).scalar_one_or_none()

    print(f"status={record.status} model={record.model_used} 耗时={record.duration_ms}ms")
    if log is not None:
        print(
            f"llm_call_log: user_id={log.user_id} task_id={log.task_id} "
            f"tokens={log.total_tokens} （期望 user_id==operator={log.user_id == operator}）"
        )
    print("\n---- 日报正文 ----")
    print(record.output_content or record.error_msg)
    await engine.dispose()
    return 0 if record.status == "success" else 2


if __name__ == "__main__":
    sys.exit(asyncio.run(_run()))
