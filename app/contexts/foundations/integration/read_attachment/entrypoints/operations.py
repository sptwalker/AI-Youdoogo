"""Entrypoint 网关：run_read_attachment（取字节→解析）+ read_attachment_available（依赖门控）。"""

from __future__ import annotations

import importlib.util

from app.contexts.foundations.integration.read_attachment.infrastructure.parser import (
    AttachmentOutcome,
    parse_attachment,
)
from app.platform.object_storage.gateway import get_object_bytes


async def run_read_attachment(storage_path: str, name: str) -> AttachmentOutcome:
    """按已鉴权的 storage_path 回读字节并解析（storage_path 去桶前缀即 object key）。"""
    _, _, object_name = storage_path.partition("/")
    try:
        data = await get_object_bytes(object_name)
    except Exception as exc:  # noqa: BLE001 - 取字节失败折进原因，不打断消息流
        return AttachmentOutcome(text="", reason=f"附件读取失败（{type(exc).__name__}）")
    return parse_attachment(name, data)


async def read_attachment_available() -> bool:
    """解析依赖齐备即视为能力就绪（pdf/docx/xlsx 三库任一缺失则不广告，优雅降级）。"""
    return all(
        importlib.util.find_spec(module) is not None
        for module in ("pypdf", "docx", "openpyxl")
    )
