"""Database-backed operational metrics and readiness adapters."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import AgentTaskRecord
from app.models.ai_provider import AiProvider
from app.models.llm_log import LlmCallLog
from app.platform import outbox

logger = logging.getLogger(__name__)


def _line(name: str, value: float, labels: dict[str, str] | None = None) -> str:
    if labels:
        rendered = ",".join(f'{key}="{label}"' for key, label in labels.items())
        return f"{name}{{{rendered}}} {value}"
    return f"{name} {value}"


async def _counts_by_status(db: AsyncSession, model: Any) -> dict[str, int]:
    rows = (
        await db.execute(select(model.status, func.count()).group_by(model.status))
    ).all()
    return {str(status): int(count) for status, count in rows}


async def render_metrics(db: AsyncSession) -> str:
    """Render persistent metrics without failing the scrape on partial errors."""
    output: list[str] = []
    try:
        llm_by_status = await _counts_by_status(db, LlmCallLog)
        output.append("# HELP youdoo_llm_calls_total Total LLM calls by status")
        output.append("# TYPE youdoo_llm_calls_total counter")
        for status, count in sorted(llm_by_status.items()):
            output.append(_line("youdoo_llm_calls_total", count, {"status": status}))

        total_tokens = int(
            (
                await db.execute(
                    select(func.coalesce(func.sum(LlmCallLog.total_tokens), 0))
                )
            ).scalar_one()
        )
        output.append("# HELP youdoo_llm_tokens_total Total LLM tokens consumed")
        output.append("# TYPE youdoo_llm_tokens_total counter")
        output.append(_line("youdoo_llm_tokens_total", total_tokens))

        from app.core import shared_state

        today = shared_state.budget_add(datetime.now(UTC).strftime("%Y-%m-%d"), 0)
        output.append("# HELP youdoo_llm_tokens_today Today's LLM tokens (redis atomic)")
        output.append("# TYPE youdoo_llm_tokens_today gauge")
        output.append(_line("youdoo_llm_tokens_today", today))

        task_by_status = await _counts_by_status(db, AgentTaskRecord)
        output.append("# HELP youdoo_agent_tasks_total Total agent task records by status")
        output.append("# TYPE youdoo_agent_tasks_total counter")
        for status, count in sorted(task_by_status.items()):
            output.append(_line("youdoo_agent_tasks_total", count, {"status": status}))

        # ponytail: 只暴露 backlog gauge；告警阈值归 Prometheus 规则，不在 app 内建告警器。
        outbox_by_status = await outbox.backlog_counts(db)
        output.append("# HELP youdoo_outbox_events_total Outbox events by status; failed=DLQ")
        output.append("# TYPE youdoo_outbox_events_total gauge")
        for status, count in sorted(outbox_by_status.items()):
            output.append(_line("youdoo_outbox_events_total", count, {"status": status}))
    except Exception:  # noqa: BLE001 - one metric must not fail the scrape
        logger.warning("渲染指标部分失败", exc_info=True)
    output.append("# HELP youdoo_up Service up")
    output.append("# TYPE youdoo_up gauge")
    output.append(_line("youdoo_up", 1))
    return "\n".join(output) + "\n"


async def readiness(db: AsyncSession) -> tuple[bool, dict[str, Any]]:
    """Report database reachability and active AI provider availability."""
    detail: dict[str, Any] = {}
    ready = True
    try:
        cards = int(
            (
                await db.execute(
                    select(func.count())
                    .select_from(AiProvider)
                    .where(
                        AiProvider.is_active.is_(True),
                        AiProvider.is_delete.is_(False),
                    )
                )
            ).scalar_one()
        )
        detail["ai_cards_active"] = cards
        detail["db"] = "ok"
        if cards == 0:
            ready = False
            detail["reason"] = "无 active AI 卡片，AI 不可用"
    except Exception as exc:  # noqa: BLE001 - DB failure means not ready
        ready = False
        detail["db"] = "error"
        detail["reason"] = str(exc)[:120]
    return ready, detail


__all__ = ["readiness", "render_metrics"]
