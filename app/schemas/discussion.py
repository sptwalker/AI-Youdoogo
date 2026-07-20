"""协作空间请求模型（F3'）。"""

import uuid

from pydantic import BaseModel, Field


class ChannelMemberIn(BaseModel):
    """群成员（真人 human / AI ai）。"""

    member_type: str = Field(pattern="^(human|ai)$")
    member_id: uuid.UUID
    member_name: str = Field(default="", max_length=64)


class ChannelCreate(BaseModel):
    """新建讨论频道（可带初始成员，真人+AI 混合）。"""

    name: str = Field(min_length=1, max_length=128)
    department_id: uuid.UUID | None = None
    default_agent_id: uuid.UUID | None = None
    members: list[ChannelMemberIn] = Field(default_factory=list)


class MessagePost(BaseModel):
    """频道发言（mentioned_agent_ids 为 @ 的 AI 顾问，服务端去重并截断 ≤3）。"""

    content: str = Field(min_length=1, max_length=5000)
    mentioned_agent_ids: list[uuid.UUID] = Field(default_factory=list)


class PromoteRequest(BaseModel):
    """把消息升格为提案/任务。"""

    target: str = Field(pattern="^(proposal|task)$")
