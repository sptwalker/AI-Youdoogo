"""智能体模块（阶段2）：核心执行外壳 + 各部门智能体。"""

from app.agents.base import get_agent_role, run_agent
from app.agents.ops import (
    format_metrics,
    generate_anomaly_alert,
    generate_daily_report,
    generate_proposal,
)
from app.agents.scheduler import run_task

__all__ = [
    "format_metrics",
    "generate_anomaly_alert",
    "generate_daily_report",
    "generate_proposal",
    "get_agent_role",
    "run_agent",
    "run_task",
]
