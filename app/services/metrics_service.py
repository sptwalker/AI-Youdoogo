"""可观测:Prometheus 指标 + readiness 探针（H2.4，docs/16 P1）。

轻量、不引重依赖:指标直接从 DB 聚合渲染 Prometheus 文本格式——无进程内计数器，
故多 worker 下天然一致（不像每-worker 内存计数会分裂）。scrape 时几条 cheap COUNT/SUM。

- render_metrics:Prometheus text exposition format（/api/v1/metrics）。
- readiness:就绪探针（DB 可达 + 至少一张 active AI 卡片），区别于 /health（存活）。
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import AgentTaskRecord
from app.models.ai_provider import AiProvider
from app.models.llm_log import LlmCallLog

logger = logging.getLogger(__name__)


def _line(name: str, value: float, labels: dict[str, str] | None = None) -> str:
    if labels:
        lbl = ",".join(f'{k}="{v}"' for k, v in labels.items())
        return f"{name}{{{lbl}}} {value}"
    return f"{name} {value}"


async def _counts_by_status(db: AsyncSession, model: Any) -> dict[str, int]:
    """按 status 分组计数（LLM 调用 / agent 任务）。"""
    rows = (
        await db.execute(select(model.status, func.count()).group_by(model.status))
    ).all()
    return {str(s): int(c) for s, c in rows}


async def render_metrics(db: AsyncSession) -> str:
    """渲染 Prometheus 文本格式指标。异常降级为最小可用集，不抛。"""
    out: list[str] = []
    try:
        llm_by_status = await _counts_by_status(db, LlmCallLog)
        out.append("# HELP youdoo_llm_calls_total Total LLM calls by status")
        out.append("# TYPE youdoo_llm_calls_total counter")
        for status, n in sorted(llm_by_status.items()):
            out.append(_line("youdoo_llm_calls_total", n, {"status": status}))

        total_tokens = int(
            (await db.execute(
                select(func.coalesce(func.sum(LlmCallLog.total_tokens), 0))
            )).scalar_one()
        )
        out.append("# HELP youdoo_llm_tokens_total Total LLM tokens consumed")
        out.append("# TYPE youdoo_llm_tokens_total counter")
        out.append(_line("youdoo_llm_tokens_total", total_tokens))

        # 当日 token（跨 worker 一致，读 Redis 原子计数）
        from app.core import shared_state

        today = shared_state.budget_add(datetime.now(UTC).strftime("%Y-%m-%d"), 0)
        out.append("# HELP youdoo_llm_tokens_today Today's LLM tokens (redis atomic)")
        out.append("# TYPE youdoo_llm_tokens_today gauge")
        out.append(_line("youdoo_llm_tokens_today", today))

        task_by_status = await _counts_by_status(db, AgentTaskRecord)
        out.append("# HELP youdoo_agent_tasks_total Total agent task records by status")
        out.append("# TYPE youdoo_agent_tasks_total counter")
        for status, n in sorted(task_by_status.items()):
            out.append(_line("youdoo_agent_tasks_total", n, {"status": status}))
    except Exception:  # noqa: BLE001 - 指标端点不得因单项失败整体 500
        logger.warning("渲染指标部分失败", exc_info=True)
    out.append("# HELP youdoo_up Service up")
    out.append("# TYPE youdoo_up gauge")
    out.append(_line("youdoo_up", 1))
    return "\n".join(out) + "\n"


async def readiness(db: AsyncSession) -> tuple[bool, dict[str, Any]]:
    """就绪探针:DB 可达 + 至少一张 active AI 卡片（无卡 AI 不可用）。

    返回 (ready, detail)。区别于 /health（存活探针）——ready=False 时编排器应停止导流。
    """
    detail: dict[str, Any] = {}
    ok = True
    try:
        cards = int(
            (await db.execute(
                select(func.count()).select_from(AiProvider).where(
                    AiProvider.is_active.is_(True), AiProvider.is_delete.is_(False)
                )
            )).scalar_one()
        )
        detail["ai_cards_active"] = cards
        detail["db"] = "ok"
        if cards == 0:
            ok = False
            detail["reason"] = "无 active AI 卡片，AI 不可用"
    except Exception as exc:  # noqa: BLE001 - DB 不可达即未就绪
        ok = False
        detail["db"] = "error"
        detail["reason"] = str(exc)[:120]
    return ok, detail
