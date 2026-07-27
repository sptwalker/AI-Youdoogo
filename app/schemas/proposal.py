"""提案卡请求/响应模型。"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ProposalCreate(BaseModel):
    """创建提案。"""

    title: str = Field(min_length=1, max_length=200)
    background: str = Field(min_length=1)
    plan: str = Field(min_length=1)
    benefit_risk: str | None = None
    priority: str = Field(default="normal", max_length=16)
    department_id: uuid.UUID | None = None


class HumanReviewRequest(BaseModel):
    """真人评审（红线：决议须真人确认）。"""

    decision: str = Field(pattern="^(approve|reject)$")
    conclusion: str = Field(min_length=1)


class ProposalEdit(BaseModel):
    """编辑草稿提案（仅草稿可改，P3-7）。"""

    title: str = Field(min_length=1, max_length=200)
    background: str = Field(min_length=1)
    plan: str = Field(min_length=1)
    benefit_risk: str | None = None
    priority: str = Field(default="normal", max_length=16)


class ConvertRequest(BaseModel):
    """提案转任务卡。"""

    assignee_agent_id: uuid.UUID | None = None


class ProposalOut(BaseModel):
    """提案卡。"""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    title: str
    department_id: uuid.UUID | None
    background: str
    plan: str
    benefit_risk: str | None
    priority: str
    status: str
    creator_id: uuid.UUID
    converted_task_id: uuid.UUID | None
    create_time: datetime


class ReviewOut(BaseModel):
    """评审记录。"""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    review_type: str
    conclusion: str
    reviewer_id: uuid.UUID | None
    decision: str | None
    create_time: datetime
