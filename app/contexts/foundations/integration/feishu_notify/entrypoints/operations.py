"""Entrypoint 网关：暴露 run_broadcast / feishu_notify_available，隔离飞书 notify 细节。

播报直接复用 ``app.integrations.feishu.notify`` 现成 best-effort 封装（受 feishu_notify_enabled
控制、默认关 → no-op、失败只 warning 不抛），notify 本身即整合层，故不再加 infrastructure 透传壳。
"""

from __future__ import annotations

from app.core import runtime_config
from app.integrations.feishu import notify


async def run_broadcast(text: str) -> bool:
    """向固定运营群播报一条文本；开关关/未配置群 → notify 内部 no-op 返回 False（不抛）。"""
    return await notify.push_ops_message(text)


def feishu_notify_available() -> bool:
    """播报开关开 + 运营群已配才视为能力就绪（自门控），与 push_ops_message 实际生效条件一致。

    未开启或未配群 → 返 False → prompt_section 不广告、run_broadcast no-op，生产逐字不变。
    """
    enabled = str(runtime_config.effective("feishu_notify_enabled", "")).strip().lower()
    chat_id = str(runtime_config.effective("feishu_ops_chat_id", "") or "")
    return enabled in ("true", "1", "yes") and bool(chat_id)
