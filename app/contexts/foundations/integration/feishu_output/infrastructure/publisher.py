"""飞书云文档/多维表格发布器（不可逆对外写；仅被机械发布步在真人验收后调用）。

只调既有 ``FeishuClient``（不改 client）。凭证走 ``runtime_config``（sys_config 覆盖 .env）。
安全红线：未配凭证 → 能力不可用（自门控）；日志只记数量，不打 token / 完整 URL / 正文 body。
"""

from __future__ import annotations

import logging
from typing import Any

from app.core import runtime_config
from app.integrations.feishu.client import FeishuClient, feishu_client

logger = logging.getLogger(__name__)


def credentials_configured() -> bool:
    """飞书应用凭证是否就绪（app_id + secret 均非空）——供提示词/规划自门控。"""
    app_id = str(runtime_config.effective("feishu_app_id", "") or "")
    secret = str(runtime_config.effective("feishu_app_secret", "") or "")
    return bool(app_id and secret)


async def publish(draft: dict[str, Any]) -> dict[str, Any]:
    """把一份已验收草稿写入飞书；按 kind 分派 docx / bitable（失败抛出，上层记录失败）。"""
    kind = draft.get("kind")
    if kind == "docx":
        return await _publish_docx(draft)
    if kind == "bitable":
        return await _publish_bitable(draft)
    raise ValueError(f"未知飞书草稿类型：{kind!r}")


async def _publish_docx(draft: dict[str, Any]) -> dict[str, Any]:
    title = str(draft.get("title") or "未命名文档")
    document_id = await feishu_client.create_document(title)
    blocks = _body_to_blocks(str(draft.get("body") or ""))
    if blocks:
        await feishu_client.append_document_blocks(document_id, blocks)
    logger.info("飞书云文档已发布 blocks=%d", len(blocks))
    return {
        "kind": "docx",
        "title": title,
        "document_id": document_id,
        "block_count": len(blocks),
    }


async def _publish_bitable(draft: dict[str, Any]) -> dict[str, Any]:
    app_token = str(draft.get("app_token") or "")
    table_id = str(draft.get("table_id") or "")
    if not app_token or not table_id:
        raise ValueError("飞书多维表格草稿缺少 app_token/table_id")
    records = draft.get("records")
    rows = [item for item in records if isinstance(item, dict)] if isinstance(records, list) else []
    record_ids: list[str] = []
    for fields in rows:
        created = await feishu_client.bitable_create_record(app_token, table_id, fields)
        record_id = str((created.get("record") or {}).get("record_id") or "")
        if record_id:
            record_ids.append(record_id)
    logger.info("飞书多维表格已写入 records=%d", len(record_ids))
    return {
        "kind": "bitable",
        "app_token": app_token,
        "table_id": table_id,
        "record_ids": record_ids,
        "record_count": len(record_ids),
    }


def _body_to_blocks(body: str) -> list[dict[str, Any]]:
    """把 markdown-ish 正文按行转飞书块：#/##/### 开头→标题块，其余非空行→文本块。"""
    blocks: list[dict[str, Any]] = []
    for raw in body.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("### "):
            blocks.append(FeishuClient.heading_block(line[4:].strip(), 3))
        elif line.startswith("## "):
            blocks.append(FeishuClient.heading_block(line[3:].strip(), 2))
        elif line.startswith("# "):
            blocks.append(FeishuClient.heading_block(line[2:].strip(), 1))
        else:
            blocks.append(FeishuClient.text_block(line))
    return blocks
