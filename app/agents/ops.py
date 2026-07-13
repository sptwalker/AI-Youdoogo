"""平台运营部智能体（首个落地部门，阶段2）：运营日报生成。

数据来源本轮走内联 metrics 行（结构同 excel_ingest 的 ops_daily 解析产物）；
Excel 上传→报告、ThinkingData/飞书接入为后续增量。
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import get_agent_role_by_code, run_agent
from app.core.exceptions import AppError
from app.models.agent import AgentTaskRecord
from app.services.anomaly import Alert

OPS_DIRECTOR_CODE = "dir_platform_ops"  # 平台运营部总监助理（稳定种子键，不随显示名变）

_COLUMNS = (
    ("stat_date", "日期"),
    ("product", "产品"),
    ("dau", "日活"),
    ("new_users", "新增"),
    ("retention_d1", "次留%"),
)


def format_metrics(rows: list[dict[str, Any]]) -> str:
    """把运营数据行渲染成给模型看的表格文本（缺字段以 - 占位）。纯函数。"""
    header = " | ".join(label for _, label in _COLUMNS)
    lines = [header, " | ".join("---" for _ in _COLUMNS)]
    for r in rows:
        lines.append(" | ".join(str(r.get(key, "-")) for key, _ in _COLUMNS))
    return "\n".join(lines)


async def generate_daily_report(
    db: AsyncSession,
    *,
    stat_date: str,
    rows: list[dict[str, Any]],
    operator_id: uuid.UUID | None = None,
) -> AgentTaskRecord:
    """生成指定日期的运营日报，落一条留痕记录。

    Raises:
        AppError: 未配置运营智能体角色（迁移种子未执行）或数据为空。
    """
    if not rows:
        raise AppError("运营数据为空，无法生成日报")
    role = await get_agent_role_by_code(db, OPS_DIRECTOR_CODE)
    if role is None:
        raise AppError("未配置平台运营部总监助理，请先在组织架构一键初始化骨架")

    user_message = (
        f"以下是 {stat_date} 的平台运营数据，请据此生成当日运营日报：\n\n"
        f"{format_metrics(rows)}"
    )
    return await run_agent(
        db,
        role,
        task_type="daily_report",
        input_summary=f"{stat_date} 运营日报，共 {len(rows)} 条数据",
        user_message=user_message,
        user_id=operator_id,
    )


async def generate_anomaly_alert(
    db: AsyncSession,
    *,
    stat_date: str,
    alerts: list[Alert],
    operator_id: uuid.UUID | None = None,
) -> AgentTaskRecord:
    """把检测到的指标异常汇成一段可读的运营告警播报，落留痕记录。

    仅在有异常时调用（无异常不必花模型 token）。

    Raises:
        AppError: 未配置运营智能体角色或异常列表为空。
    """
    if not alerts:
        raise AppError("无异常项，无需生成告警")
    role = await get_agent_role_by_code(db, OPS_DIRECTOR_CODE)
    if role is None:
        raise AppError("未配置平台运营部总监助理，请先在组织架构一键初始化骨架")

    detail = "\n".join(f"- [{a.severity}] {a.product} {a.metric}：{a.message}" for a in alerts)
    user_message = (
        f"{stat_date} 运营指标检测到以下异常，请生成一段面向管理层的运营告警播报，"
        f"点明风险与建议优先级：\n\n{detail}"
    )
    return await run_agent(
        db,
        role,
        task_type="anomaly_alert",
        input_summary=f"{stat_date} 异常 {len(alerts)} 项",
        user_message=user_message,
        user_id=operator_id,
    )


async def generate_proposal(
    db: AsyncSession,
    *,
    topic: str,
    context: str = "",
    operator_id: uuid.UUID | None = None,
) -> AgentTaskRecord:
    """就运营议题输出一份结构化优化提案（AI 仅建议权，需真人确认，见 docs/04 红线）。

    Raises:
        AppError: 未配置运营智能体角色。
    """
    role = await get_agent_role_by_code(db, OPS_DIRECTOR_CODE)
    if role is None:
        raise AppError("未配置平台运营部总监助理，请先在组织架构一键初始化骨架")

    context_part = f"\n\n参考信息：\n{context}" if context.strip() else ""
    user_message = (
        f"请就以下运营议题输出一份运营优化提案，固定包含"
        f"【背景与问题】【优化目标】【具体方案】【预期收益与风险】【优先级建议】五部分。"
        f"提案仅供管理层参考，不构成最终决策。\n\n议题：{topic}{context_part}"
    )
    return await run_agent(
        db,
        role,
        task_type="proposal",
        input_summary=f"运营提案：{topic[:40]}",
        user_message=user_message,
        user_id=operator_id,
    )
