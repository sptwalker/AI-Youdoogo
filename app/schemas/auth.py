"""鉴权与用户管理的请求/响应模型。"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

VALID_ROLES = ("admin", "executive", "member")


class LoginRequest(BaseModel):
    """登录请求。"""

    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class TokenResponse(BaseModel):
    """令牌响应。"""

    access_token: str
    token_type: str = "bearer"
    expires_in: int  # 秒


class UserOut(BaseModel):
    """用户信息（不含密码哈希）。"""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    username: str
    real_name: str
    role_code: str
    department_id: uuid.UUID | None
    is_active: bool
    create_time: datetime


class UserCreate(BaseModel):
    """创建用户（仅 admin）。"""

    username: str = Field(min_length=2, max_length=64, pattern=r"^[a-zA-Z0-9_.-]+$")
    password: str = Field(min_length=8, max_length=128)
    real_name: str = Field(default="", max_length=64)
    role_code: str = Field(default="member")
    department_id: uuid.UUID | None = None


class UserUpdate(BaseModel):
    """更新用户（仅 admin）：未提供的字段不变。"""

    password: str | None = Field(default=None, min_length=8, max_length=128)
    real_name: str | None = Field(default=None, max_length=64)
    role_code: str | None = None
    department_id: uuid.UUID | None = None
    is_active: bool | None = None
