"""智能体请求/响应模型。"""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class MetricRow(BaseModel):
    """一行运营数据（结构同 excel_ingest ops_daily 解析产物，字段宽松）。"""

    model_config = ConfigDict(extra="allow")

    stat_date: str | None = None
    product: str | None = None
    dau: int | None = None
    new_users: int | None = None
    retention_d1: float | None = None


class DailyReportRequest(BaseModel):
    """生成运营日报。rows 省略时从已入库的 ops_daily_metric 按 stat_date 取数。"""

    stat_date: str = Field(min_length=1, max_length=32)
    rows: list[MetricRow] | None = None


class AnomalyCheckRequest(BaseModel):
    """指标异常检测（对比前一日），有异常时生成告警播报。"""

    stat_date: str = Field(min_length=1, max_length=32)


class ProposalRequest(BaseModel):
    """生成运营优化提案（AI 仅建议权，需真人确认）。"""

    topic: str = Field(min_length=1, max_length=200)
    context: str = Field(default="", max_length=4000)


class AgentRoleCreate(BaseModel):
    """新增智能体角色（新增部门智能体 = 建一行）。"""

    name: str = Field(min_length=1, max_length=64)
    prompt_template: str = Field(min_length=1)
    duty: str | None = Field(default=None, max_length=500)
    model_role: str = Field(default="daily")
    permission_scope: dict[str, Any] = Field(default_factory=dict)
    tools: list[Any] = Field(default_factory=list)


class AgentRoleUpdate(BaseModel):
    """更新智能体角色：未提供字段不变。"""

    prompt_template: str | None = None
    duty: str | None = Field(default=None, max_length=500)
    model_role: str | None = None
    is_active: bool | None = None
    permission_scope: dict[str, Any] | None = None
    tools: list[Any] | None = None


class FeedbackRequest(BaseModel):
    """对一条智能体执行记录评分。"""

    score: int = Field(ge=1, le=5)
    comment: str | None = Field(default=None, max_length=1000)


class TaskRecordOut(BaseModel):
    """智能体执行留痕。"""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    agent_role_id: uuid.UUID
    task_type: str
    input_summary: str | None
    output_content: str | None
    model_used: str | None
    status: str
    error_msg: str | None
    duration_ms: int | None
    create_time: datetime
    # 当前用户对该记录的已有评分（回显 + 提交后只读，P1-9）；未评为 None。
    my_score: int | None = None
    my_comment: str | None = None


class AgentRoleOut(BaseModel):
    """智能体角色配置（不回显 prompt_template 全文，避免泄露内部提示词）。"""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    duty: str | None
    model_role: str
    permission_scope: dict[str, Any]
    tools: list[Any]
    is_active: bool
