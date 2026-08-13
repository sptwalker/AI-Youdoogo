"""飞书输出操作入口（entrypoint→infrastructure 网关；仿 web_search operations）。"""

from __future__ import annotations

from typing import Any

from app.contexts.foundations.integration.feishu_output.infrastructure import publisher


async def feishu_output_available() -> bool:
    """飞书发布能力是否可用（凭证已配）——供提示词自门控与规划配对门控。"""
    return publisher.credentials_configured()


async def run_publish(draft: dict[str, Any]) -> dict[str, Any]:
    """发布一份已验收草稿到飞书（docx/bitable），返回发布结果标识。"""
    return await publisher.publish(draft)
