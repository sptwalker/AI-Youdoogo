"""Canonical operational report, anomaly, and proposal use cases."""

from __future__ import annotations

import uuid
from datetime import date, timedelta

from app.contexts.business.operational_analytics.agent_contracts import (
    AnomalyAlertCommand,
    AnomalyCheckCommand,
    AnomalyCheckResult,
    DailyReportCommand,
    MetricRowInput,
    OperationalProposalCommand,
)
from app.contexts.business.operational_analytics.application.agent_ports import (
    OperationalAgentPort,
    OperationalExpertPort,
    OperationalMetricHistoryPort,
    OperationalNotificationPort,
)
from app.contexts.business.operational_analytics.domain.anomaly import (
    detect_metric_anomalies,
)
from app.contexts.foundations.execution.agent_execution.contracts.execution import (
    AgentExecutionRequest,
)
from app.contexts.foundations.execution.agent_execution.contracts.records import (
    AgentExecutionRecordView,
)
from app.contexts.shared_kernel import RuleViolation

OPS_DIRECTOR_CODE = "dir_platform_ops"

_HEADERS = ("日期", "产品", "日活", "新增", "次留%")


def format_metrics(rows: tuple[MetricRowInput, ...]) -> str:
    header = " | ".join(_HEADERS)
    lines = [header, " | ".join("---" for _ in _HEADERS)]
    lines.extend(" | ".join(str(value) for value in row.prompt_values()) for row in rows)
    return "\n".join(lines)


class OperationalAgentAnalytics:
    def __init__(
        self,
        *,
        metrics: OperationalMetricHistoryPort,
        experts: OperationalExpertPort,
        agents: OperationalAgentPort,
        notifications: OperationalNotificationPort,
    ) -> None:
        self._metrics = metrics
        self._experts = experts
        self._agents = agents
        self._notifications = notifications

    async def daily_report(self, command: DailyReportCommand) -> AgentExecutionRecordView:
        rows = command.rows
        if rows is None:
            stat_date = self._date(command.stat_date, with_rows_hint=True)
            rows = await self._metrics.list_for_date(stat_date)
        if not rows:
            raise RuleViolation("运营数据为空，无法生成日报")
        record = await self._execute(
            task_type="daily_report",
            input_summary=f"{command.stat_date} 运营日报，共 {len(rows)} 条数据",
            user_message=(
                f"以下是 {command.stat_date} 的平台运营数据，请据此生成当日运营日报：\n\n"
                f"{format_metrics(rows)}"
            ),
            operator_id=command.operator_id,
        )
        if record.status == "success" and record.output_content:
            await self._notifications.push(
                f"【运营日报 {command.stat_date}】\n{record.output_content}"
            )
        return record

    async def anomaly_check(self, command: AnomalyCheckCommand) -> AnomalyCheckResult:
        stat_date = self._date(command.stat_date)
        today = await self._metrics.list_for_date(stat_date)
        if not today:
            raise RuleViolation("该日无运营数据，请先上传")
        previous = await self._metrics.list_for_date(stat_date - timedelta(days=1))
        alerts = detect_metric_anomalies(today, previous)
        if not alerts:
            return AnomalyCheckResult(alerts=())
        record = await self.anomaly_alert(
            AnomalyAlertCommand(
                stat_date=command.stat_date,
                alerts=alerts,
                operator_id=command.operator_id,
            )
        )
        return AnomalyCheckResult(alerts=alerts, record=record)

    async def anomaly_alert(
        self, command: AnomalyAlertCommand
    ) -> AgentExecutionRecordView:
        if not command.alerts:
            raise RuleViolation("无异常项，无需生成告警")
        detail = "\n".join(
            f"- [{alert.severity}] {alert.product} {alert.metric}：{alert.message}"
            for alert in command.alerts
        )
        record = await self._execute(
            task_type="anomaly_alert",
            input_summary=f"{command.stat_date} 异常 {len(command.alerts)} 项",
            user_message=(
                f"{command.stat_date} 运营指标检测到以下异常，请生成一段面向管理层的运营告警播报，"
                f"点明风险与建议优先级：\n\n{detail}"
            ),
            operator_id=command.operator_id,
        )
        if record.status == "success" and record.output_content:
            await self._notifications.push(
                f"【运营告警 {command.stat_date}】\n{record.output_content}"
            )
        return record

    async def proposal(
        self, command: OperationalProposalCommand
    ) -> AgentExecutionRecordView:
        context = f"\n\n参考信息：\n{command.context}" if command.context.strip() else ""
        return await self._execute(
            task_type="proposal",
            input_summary=f"运营提案：{command.topic[:40]}",
            user_message=(
                "请就以下运营议题输出一份运营优化提案，固定包含"
                "【背景与问题】【优化目标】【具体方案】【预期收益与风险】【优先级建议】五部分。"
                "提案仅供管理层参考，不构成最终决策。"
                f"\n\n议题：{command.topic}{context}"
            ),
            operator_id=command.operator_id,
        )

    async def _execute(
        self,
        *,
        task_type: str,
        input_summary: str,
        user_message: str,
        operator_id: uuid.UUID | None,
    ) -> AgentExecutionRecordView:
        expert = await self._experts.get_by_code(OPS_DIRECTOR_CODE)
        if expert is None:
            raise RuleViolation("未配置平台运营部总监助理，请先在组织架构一键初始化骨架")
        return await self._agents.execute(
            AgentExecutionRequest(
                expert=expert,
                task_type=task_type,
                input_summary=input_summary,
                user_message=user_message,
                user_id=operator_id,
            )
        )

    @staticmethod
    def _date(value: str, *, with_rows_hint: bool = False) -> date:
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            message = "stat_date 需为 YYYY-MM-DD"
            if with_rows_hint:
                message += "，或直接在 rows 传入数据"
            raise RuleViolation(message) from exc
