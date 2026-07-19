"""LLM 用量入库 + 日预算告警（docs/09 §5，阶段1）。

调用方在每次 LLM 调用后调 record_usage 落一行 llm_call_log；当日累计 token
超过 settings.llm_daily_token_budget（>0 时生效）则 warning 告警（首版记日志，
飞书推送后续增量）。token 数取 langchain 标准 usage_metadata。
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from langchain_core.messages import BaseMessage
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.llm_log import LlmCallLog

logger = logging.getLogger(__name__)


class BudgetExceededError(RuntimeError):
    """当日 LLM token 预算已耗尽且开启硬闸，拒绝新调用（H2.2）。"""


def budget_exceeded() -> bool:
    """当日累计是否已超预算（硬闸判据，读 Redis 原子计数，跨 worker 一致）。

    仅在 llm_daily_token_budget>0 且 llm_budget_hard_limit=True 时生效;否则恒 False。
    """
    s = get_settings()
    if s.llm_daily_token_budget <= 0 or not s.llm_budget_hard_limit:
        return False
    from datetime import UTC, datetime

    from app.core import shared_state

    day = datetime.now(UTC).strftime("%Y-%m-%d")
    return shared_state.budget_add(day, 0) >= s.llm_daily_token_budget


def extract_usage(reply: BaseMessage) -> tuple[int, int, int]:
    """从模型返回的 usage_metadata 取 (prompt, completion, total) token；缺失返回 0。"""
    meta: dict[str, Any] = getattr(reply, "usage_metadata", None) or {}
    prompt = int(meta.get("input_tokens", 0) or 0)
    completion = int(meta.get("output_tokens", 0) or 0)
    total = int(meta.get("total_tokens", 0) or 0) or (prompt + completion)
    return prompt, completion, total


async def record_usage(
    db: AsyncSession,
    *,
    role: str,
    model: str | None,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    total_tokens: int = 0,
    duration_ms: int | None = None,
    status: str = "success",
    user_id: uuid.UUID | None = None,
    task_id: uuid.UUID | None = None,
    department_id: uuid.UUID | None = None,
) -> None:
    """落一行用量记录并做日预算告警。异常吞掉（用量留痕绝不影响主链路）。"""
    try:
        db.add(
            LlmCallLog(
                role=role, model=model,
                prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
                total_tokens=total_tokens, duration_ms=duration_ms, status=status,
                user_id=user_id, task_id=task_id, department_id=department_id,
            )
        )
        await db.commit()
        await _check_daily_budget(db, total_tokens)
    except Exception:  # noqa: BLE001 - 用量记录失败不得影响业务
        logger.exception("记录 LLM 用量失败 role=%s model=%s", role, model)


async def _check_daily_budget(db: AsyncSession, tokens: int) -> None:
    """当日累计 token 超预算则告警。用 Redis 原子计数（跨 worker 一致，H1.4）。

    原子 INCRBY 累加 + 判超限，消除多 worker 各自 DB 求和的竞态;Redis 不可用时
    shared_state 自动降级本地计数（单 worker 仍准）。仅在"刚越过阈值"那一刻告警一次。
    """
    budget = get_settings().llm_daily_token_budget
    if budget <= 0:
        return
    from datetime import UTC, datetime

    from app.core import shared_state

    day = datetime.now(UTC).strftime("%Y-%m-%d")
    before = shared_state.budget_add(day, 0)  # 当前累计（未加本次）
    after = shared_state.budget_add(day, max(0, tokens))
    if before <= budget < after:  # 恰好本次越过阈值 → 只告警一次
        msg = f"LLM 日用量告警：当日累计 {after} tokens 已超预算 {budget}，请关注成本。"
        logger.warning(msg)
        from app.integrations.feishu import notify

        await notify.push_ops_message(f"【成本告警】{msg}")
