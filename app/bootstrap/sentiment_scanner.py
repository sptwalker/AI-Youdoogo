"""营销舆情事件驱动触发中枢（docs/26 P2 拱心石）——检测命中→发事件→展开模板→系统发起 workflow。

三段薄逻辑，红线不旁路：
  1. 检测（纯函数，marketing_sentiment 域）命中 → 发 OutboxEvent(sentiment.anomaly.detected)。
  2. worker 领事件 → 注册的 handler：解析 payload → 按名展开种子模板 → 系统发起 workflow。
  3. start 复用 P1 报表调度同一入口（plan_work→start_workflow）、同一 is_red_line 逐步判定；
     对外步骤前必停 waiting_human。

阈值走 runtime_config（sys_config 覆盖 .env），不在本模块硬编码。emit→handle→start 全链可单测。

# ponytail: handler 调自提交的 start = at-least-once（start 提交 run 与 outbox complete 提交之间
#   有窄崩溃窗，与 report_scheduler 已接受的口径一致）。每次重放都是全新、仍停 waiting_human 的红线
#   安全 run；重复可见可撤，故按红线安全接受此上限，不再建 event→run 关联去重。
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.bootstrap import workflow_events
from app.bootstrap.report_scheduler import _start_workflow, _template_plan_steps
from app.contexts.business.marketing_sentiment.public import (
    SentimentAlert,
    SentimentSignal,
    SentimentThresholds,
    detect_sentiment_anomalies,
)
from app.contexts.foundations.execution.work_planning import public as work_planning
from app.contexts.foundations.execution.workflow_templating import public as workflow_templating
from app.core import runtime_config
from app.core.config import get_settings
from app.models.workflow import OutboxEvent
from app.platform.outbox import repository as outbox

logger = logging.getLogger(__name__)

SENTIMENT_ANOMALY_EVENT = "sentiment.anomaly.detected"
SENTIMENT_TEMPLATE_NAME = "营销舆情应急响应"

# start 的最小签名别名，便于测试注入假发起器（默认走真实编排入口）。
StartFn = Callable[..., Awaitable[dict[str, Any] | None]]
EmitFn = Callable[..., Awaitable[OutboxEvent]]


def _as_float(value: Any, default: float) -> float:
    """runtime_config 值可能是字符串/None；无法解析即回落 default（校准旋钮非业务真值）。"""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_bool(value: Any, default: bool) -> bool:
    """兼容 sys_config 存的 "true"/"1"/bool；无法识别即回落 default。"""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return default


def _load_thresholds() -> SentimentThresholds:
    """从 runtime_config 读检测阈值（sys_config 覆盖 .env），未配置回落域默认——不硬编码。"""
    d = SentimentThresholds()
    return SentimentThresholds(
        negative_ratio_jump=_as_float(
            runtime_config.effective("sentiment_negative_ratio_jump", None), d.negative_ratio_jump
        ),
        negative_ratio_floor=_as_float(
            runtime_config.effective("sentiment_negative_ratio_floor", None), d.negative_ratio_floor
        ),
        competitor_major=_as_bool(
            runtime_config.effective("sentiment_alert_competitor_major", None), d.competitor_major
        ),
        policy_change=_as_bool(
            runtime_config.effective("sentiment_alert_policy_change", None), d.policy_change
        ),
    )


async def emit_anomaly(
    session: AsyncSession,
    *,
    alerts: Sequence[SentimentAlert],
    creator_id: uuid.UUID,
    window_key: str,
    assignee_agent_id: uuid.UUID | None = None,
) -> OutboxEvent:
    """把一批命中告警写成一条 outbox 事件（同 window_key 幂等：dedupe_key 命中则复用旧行）。"""
    request_text = "检测到营销舆情异常：" + "；".join(a.message for a in alerts)
    payload: dict[str, Any] = {
        "creator_id": str(creator_id),
        "assignee_agent_id": str(assignee_agent_id) if assignee_agent_id else None,
        "title": SENTIMENT_TEMPLATE_NAME,
        "request_text": request_text,
        "alerts": [a.to_dict() for a in alerts],
    }
    return await outbox.enqueue(
        session,
        aggregate_type="marketing_sentiment",
        aggregate_id=uuid.uuid5(uuid.NAMESPACE_URL, f"sentiment:{window_key}"),
        event_type=SENTIMENT_ANOMALY_EVENT,
        dedupe_key=f"sentiment-anomaly:{window_key}",
        payload=payload,
    )


async def _seed_template_steps(
    session: AsyncSession,
) -> list[work_planning.WorkflowPlanStep] | None:
    """按名找到营销舆情种子模板并展开成钉死步骤（无 get-by-name，遍历 enabled 列表）。

    # ponytail: 线性扫 enabled 模板匹配名字；模板量小，命中即返。量大了再加 by-name 查询。
    """
    for view in await workflow_templating.list_enabled(session):
        if view.name == SENTIMENT_TEMPLATE_NAME:
            return await _template_plan_steps(session, view.id)
    return None


async def handle_sentiment_anomaly(
    session: AsyncSession,
    event: OutboxEvent,
    *,
    start: StartFn = _start_workflow,
) -> None:
    """worker 领到舆情异常事件 → 展开种子模板 → 系统发起 workflow（operator_id=None，红线不旁路）。

    creator_id 缺失 = 畸形事件（红线审核人无从落，重试也无用）→ 记日志跳过（handle_event 标 DONE）。
    模板缺失 / start 返 None = 可恢复或需人工介入 → raise 让 outbox 重试到 terminal，暴露给运维。
    """
    payload = event.payload or {}
    raw_creator = payload.get("creator_id")
    if not raw_creator:
        logger.warning("舆情异常事件缺 creator_id，跳过 event=%s", event.id)
        return
    creator_id = uuid.UUID(str(raw_creator))
    raw_assignee = payload.get("assignee_agent_id")
    assignee_agent_id = uuid.UUID(str(raw_assignee)) if raw_assignee else None
    request_text = str(payload.get("request_text") or "")

    steps = await _seed_template_steps(session)
    if steps is None:
        raise RuntimeError(f"营销舆情种子模板缺失/停用，无法发起 event={event.id}")

    result = await start(
        session,
        request_text,
        creator_id=creator_id,
        assignee_agent_id=assignee_agent_id,
        operator_id=None,
        title=str(payload.get("title") or SENTIMENT_TEMPLATE_NAME),
        steps=steps,
    )
    if result is None:
        raise RuntimeError(f"营销舆情 workflow 发起失败 event={event.id}")


async def scan_sentiment_once(
    session: AsyncSession,
    *,
    signals: Sequence[SentimentSignal],
    creator_id: uuid.UUID,
    window_key: str,
    thresholds: SentimentThresholds | None = None,
    assignee_agent_id: uuid.UUID | None = None,
    emit: EmitFn = emit_anomaly,
) -> int:
    """检测一批信号 → 命中即发一条事件（阈值缺省从 runtime_config 载）。返回命中告警数。

    # ponytail: 本阶段无实时舆情源 + record→SentimentSignal 映射（docs/26 P1 诚实边界），signals 由
    #   调用方喂入、未接 worker 时钟闸。P2 交付「检测→发事件→展开模板→start」机制并单测；接实时源的
    #   最后一公里推迟——那需真实外部 API 拉取与归一，缺则会臆造数据。
    """
    alerts = detect_sentiment_anomalies(signals, thresholds or _load_thresholds())
    if not alerts:
        return 0
    await emit(
        session,
        alerts=alerts,
        creator_id=creator_id,
        window_key=window_key,
        assignee_agent_id=assignee_agent_id,
    )
    return len(alerts)


def register_sentiment_response() -> bool:
    """装配期把舆情异常 handler 注册进 workflow 事件路由；由 sentiment_response_enabled 自门控。"""
    if not get_settings().sentiment_response_enabled:
        return False
    workflow_events.register_event_handler(SENTIMENT_ANOMALY_EVENT, handle_sentiment_anomaly)
    return True
