"""会议会商请求/响应模型。"""

import uuid
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class MeetingCreate(BaseModel):
    """创建会议。"""

    title: str = Field(min_length=1, max_length=200)
    meeting_type: str = Field(default="decision", max_length=32)
    participants: list[dict[str, Any]] = Field(default_factory=list)


class StatusRequest(BaseModel):
    to_status: str = Field(pattern="^(in_progress|closed)$")


class DiscussRequest(BaseModel):
    content: str = Field(min_length=1)


class AiSpeakRequest(BaseModel):
    topic: str = Field(min_length=1, max_length=500)


class VoteRequest(BaseModel):
    subject: str = Field(min_length=1, max_length=200)
    choice: str = Field(pattern="^(approve|reject|abstain)$")
    comment: str | None = None


class AiVoteRequest(BaseModel):
    subject: str = Field(min_length=1, max_length=200)


class ResolutionCreate(BaseModel):
    content: str = Field(min_length=1)
    owner_id: uuid.UUID | None = None
    due_date: date | None = None


class ConvertRequest(BaseModel):
    assignee_agent_id: uuid.UUID | None = None


class MeetingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    meeting_type: str
    status: str
    scheduled_at: datetime | None
    creator_id: uuid.UUID
    summary: str | None
    create_time: datetime


class DiscussOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    speaker_type: str
    speaker_name: str
    content: str
    create_time: datetime


class VoteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    subject: str
    voter_type: str
    choice: str
    comment: str | None
    create_time: datetime


class ResolutionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    content: str
    owner_id: uuid.UUID | None
    due_date: date | None
    is_confirmed: bool
    confirmed_by: uuid.UUID | None
    converted_task_id: uuid.UUID | None
    create_time: datetime
