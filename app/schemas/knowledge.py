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
    knowledge_base_id: uuid.UUID | None = None  # 缺省=公司公共库


class FeishuIngestRequest(BaseModel):
    """拉取飞书云文档入库。"""

    document_id: str = Field(min_length=1, max_length=128)
    category: str | None = Field(default=None, max_length=64)
    knowledge_base_id: uuid.UUID | None = None  # 缺省=公司公共库


class AskRequest(BaseModel):
    """知识库问答。"""

    query: str = Field(min_length=1, max_length=1000)
    top_k: int = Field(default=5, ge=1, le=20)


class AskResponse(BaseModel):
    """问答结果：答案 + 来源列表。"""

    answer: str
    sources: list[dict[str, Any]]


class KnowledgeBaseCreate(BaseModel):
    """新建知识库。department scope 需 department_id；personal scope 需 owner_agent_id。"""

    name: str = Field(min_length=1, max_length=128)
    scope: str = Field(default="department")
    code: str | None = Field(default=None, max_length=64)
    department_id: uuid.UUID | None = None
    owner_agent_id: uuid.UUID | None = None
    is_confidential: bool = False
    description: str | None = None


class KnowledgeBaseUpdate(BaseModel):
    """改知识库（仅传需改字段）。"""

    name: str | None = Field(default=None, max_length=128)
    is_confidential: bool | None = None
    description: str | None = None
    is_active: bool | None = None


class DataSourceCreate(BaseModel):
    """新建数据接口。secret_ref 存 .env 变量名，绝不存明文。"""

    name: str = Field(min_length=1, max_length=128)
    type: str
    code: str | None = Field(default=None, max_length=64)
    department_id: uuid.UUID | None = None
    config: dict[str, Any] | None = None
    secret_ref: str | None = Field(default=None, max_length=128)


class DataSourceUpdate(BaseModel):
    """改数据接口（仅传需改字段）。"""

    name: str | None = Field(default=None, max_length=128)
    config: dict[str, Any] | None = None
    secret_ref: str | None = Field(default=None, max_length=128)
    is_active: bool | None = None
