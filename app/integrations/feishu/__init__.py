"""飞书集成：异步客户端 / 卡片构建 / best-effort 通知。"""

from app.integrations.feishu import notify
from app.integrations.feishu.client import (
    FeishuAPIError,
    FeishuAuthError,
    FeishuClient,
    feishu_client,
)

__all__ = [
    "FeishuAPIError",
    "FeishuAuthError",
    "FeishuClient",
    "feishu_client",
    "notify",
]
