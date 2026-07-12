"""知识库请求/响应模型。"""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class FileOut(BaseModel):
    """知识库文档信息。"""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    file_name: str
    category: str | None
    uploader_id: uuid.UUID
    file_size: int | None
    mime_type: str | None
    status: str
    create_time: datetime


class TextIngestRequest(BaseModel):
    """粘贴正文入库。"""

    title: str = Field(min_length=1, max_length=255)
    text: str = Field(min_length=1)
    category: str | None = Field(default=None, max_length=64)


class FeishuIngestRequest(BaseModel):
    """拉取飞书云文档入库。"""

    document_id: str = Field(min_length=1, max_length=128)
    category: str | None = Field(default=None, max_length=64)


class AskRequest(BaseModel):
    """知识库问答。"""

    query: str = Field(min_length=1, max_length=1000)
    top_k: int = Field(default=5, ge=1, le=20)


class AskResponse(BaseModel):
    """问答结果：答案 + 来源列表。"""

    answer: str
    sources: list[dict[str, Any]]
