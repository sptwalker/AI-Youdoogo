"""定时报告调度记录（docs/25 P1-1）。

一条记录 = 一个「到点自动发起 workflow」的模板：cron 式的月度触发（day_of_month/hour）+ 交给
规划器的自然语言请求 + 负责人/承接 Agent + 幂等游标。系统发起仍走 plan_work → start_workflow 同一
入口、同一 is_red_line 判定，对外步骤前必停 waiting_human——本表不含任何红线旁路。
"""

import uuid

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.platform.database.model import Base, CommonMixin


class ReportSchedule(CommonMixin, Base):
    """定时报告调度模板；写者仅 report_scheduling Context（单持久化写者）。"""

    __tablename__ = "report_schedule"
    # 配置由管理员直接改库（暂无 CRUD 界面）——在信任边界加 CHECK，误配即写入失败而非静默错点触发。
    __table_args__ = (
        CheckConstraint("day_of_month BETWEEN 1 AND 31", name="ck_report_schedule_day"),
        CheckConstraint("hour BETWEEN 0 AND 23", name="ck_report_schedule_hour"),
    )

    name: Mapped[str] = mapped_column(String(100))
    request_text: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(String(200))
    # 负责人/审核人；为空即不发起（红线审核人缺失时安全回落，不产生系统级 run）。
    creator_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("sys_user.id"), nullable=True
    )
    assignee_agent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agent_role.id"), nullable=True
    )
    # 指向钉死的工作流模板（docs/25 P4）；非空即走确定性展开（跳过 LLM），空则 request_text→LLM。
    template_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("workflow_template.id"), nullable=True
    )
    day_of_month: Mapped[int] = mapped_column(Integer)
    hour: Mapped[int] = mapped_column(Integer, default=9, server_default="9")
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # 幂等游标「YYYY-MM」；本月已发起即不重发。首建为空表示从未发起。
    last_fired_period: Mapped[str | None] = mapped_column(String(7), nullable=True)
