"""定时报告调度器（docs/25 P1-1）——系统发起 workflow 入口，红线不旁路。

到点判定是纯函数（可单测）；发起复用 plan_work → start_workflow 同一入口、同一 is_red_line
逐步判定，对外/资金/人事/发布步骤前必停 waiting_human。本模块不新增红线代码路径，也不构造步骤。
"""

from __future__ import annotations

import calendar
import logging
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.business.task_management import public as task_management
from app.contexts.foundations.execution.report_scheduling import public as report_scheduling
from app.contexts.foundations.execution.work_planning import public as work_planning
from app.contexts.foundations.execution.workflow_runtime import public as workflow_runtime
from app.platform.database import async_session_factory

logger = logging.getLogger(__name__)

# start 的最小签名别名，便于测试注入假发起器（默认走真实编排入口）。
StartFn = Callable[..., Awaitable[dict[str, Any] | None]]


def current_period(now: datetime) -> str:
    """幂等期键「YYYY-MM」；同期只发起一次。"""
    return f"{now.year:04d}-{now.month:02d}"


def is_due(
    *,
    enabled: bool,
    day_of_month: int,
    hour: int,
    last_fired_period: str | None,
    now: datetime,
) -> bool:
    """月度到点判定：启用 + 本期未发起 + 已到（当月第 day 天 hour 点或之后）。

    day_of_month 超过当月天数时 clamp 到月末（31 号在 30 天月照样发，不静默漏发）。
    (day, hour) 用元组比较实现「到点即触发、宕机后仍可补发（只要仍在本月且未发过）」。
    """
    if not enabled:
        return False
    if last_fired_period == current_period(now):
        return False
    days_in_month = calendar.monthrange(now.year, now.month)[1]
    target_day = min(day_of_month, days_in_month)
    return (now.day, now.hour) >= (target_day, hour)


async def _start_workflow(
    session: AsyncSession,
    request: str,
    *,
    creator_id: uuid.UUID,
    assignee_agent_id: uuid.UUID | None,
    operator_id: uuid.UUID | None,
    title: str | None,
) -> dict[str, Any] | None:
    """系统发起 = plan_work → start_workflow（新架构双 Port，同一 is_red_line 入口）。

    operator_id 恒 None（红线：系统发起无真人代操作）——新架构 WorkIntent 已无 operator 字段，
    此参数仅为保留「系统发起无 operator」契约、供测试断言。规划非多步 / LLM 抖动 / 提交前异常
    → 返 None（内部已回滚），调用方不标记游标、下轮重试。
    """
    del operator_id
    try:
        planned = await work_planning.plan_work(
            work_planning.PlanWorkRequest(
                work_planning.WorkIntent(
                    request=request,
                    creator_id=creator_id,
                    title=title,
                    assignee_expert_id=assignee_agent_id,
                )
            )
        )
        if planned.plan is None:
            return None
        started = await task_management.start_workflow(
            session,
            workflow_runtime.planning_to_start_command(planned.plan),
        )
    except Exception:  # noqa: BLE001 - 发起失败退回，不标记游标下轮重试
        await session.rollback()
        logger.warning("定时报告发起异常，本轮不标记，下轮重试", exc_info=True)
        return None
    return {"parent_task_id": str(started.parent_task_id)}


async def scan_once(
    now: datetime,
    *,
    sessions: Callable[[], AsyncSession] = async_session_factory,
    start: StartFn = _start_workflow,
) -> int:
    """扫描一轮：对每条到点的调度经 start 发起系统 workflow，成功后标记本期已发起。

    幂等：start 内部原子提交 run 后，mark_fired 才提交游标。start 返回 None（规划非多步 / LLM 抖动 /
    提交前异常回滚）则不标记、下轮重试——「漏发月报比重复更糟」的取舍。creator_id 为空即跳过
    （红线审核人缺失，不产生系统级 run）。

    # ponytail: start 在 commit 之后若回读失败也返 None，此时 run 已持久化但游标未推进 → 下轮会
    #   再发一次（每次都是全新、仍停 waiting_human 的红线安全 run）。瞬时错误下次轮多半收敛；只有
    #   确定性错误才每轮重发、须人工介入。要严格「一次崩溃至多一份重复」须建 schedule→run 关联；
    #   本阶段按红线安全 + 重复可见可撤接受此上限。
    """
    fired = 0
    async with sessions() as session:
        for view in await report_scheduling.list_enabled(session):
            if view.creator_id is None:
                logger.warning("定时报告未配置负责人，跳过 schedule=%s", view.id)
                continue
            if not is_due(
                enabled=view.enabled,
                day_of_month=view.day_of_month,
                hour=view.hour,
                last_fired_period=view.last_fired_period,
                now=now,
            ):
                continue
            result = await start(
                session,
                view.request_text,
                creator_id=view.creator_id,
                assignee_agent_id=view.assignee_agent_id,
                operator_id=None,
                title=view.title,
            )
            if result is None:
                logger.warning("定时报告发起失败，本轮不标记，下轮重试 schedule=%s", view.id)
                continue
            await report_scheduling.mark_fired(session, view.id, current_period(now))
            await session.commit()
            fired += 1
    return fired
