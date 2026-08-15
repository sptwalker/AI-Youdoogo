"""Entrypoint 网关：暴露 send_to_recipient / feishu_notify_person_available，隔离飞书 notify 细节。

定向通知复用 ``app.integrations.feishu.notify`` 现成 best-effort 封装（send_text_to_user 私聊 /
send_text_to_chat 群聊，受 feishu_notify_enabled 控制、默认关 → no-op、失败只 warning 不抛），
notify 本身即整合层，故不再加 infrastructure 透传壳。与 feishu_notify（固定运营群单向播报）的区别：
本能力发到「指定 open_id 个人 / 指定 chat_id 群」，属点对点对外触达 → 红线，编排步执行前必停真人。
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import runtime_config
from app.core.config import get_settings
from app.integrations.feishu import notify


async def send_to_recipient(
    recipient: str,
    is_chat: bool,
    text: str,
    *,
    session: AsyncSession | None = None,
    recipient_user_id: uuid.UUID | None = None,
) -> bool:
    """向指定收件人发纯文本；is_chat=True 走群聊 chat_id、否则走个人 open_id。

    开关关/收件人空 → notify 内部 no-op 返回 False（不抛）。收件人标识不入日志（隐私）。

    番茄钟单点拦截（docs/27-B B2.3）：当传入 session + recipient_user_id 且该本人正处于
    active 且 intercept_notifications 的专注期，则跳过发送并返回 False（被拦截）。
    ponytail: 拦截=专注期 best-effort 跳过点对点通知，不做补发队列；需要补发再加。
    红线：拦截只影响发给本人的通知；对外定向发送（无 recipient_user_id）不受影响。
    """
    if session is not None and recipient_user_id is not None:
        # 惰性导入避免 integration→business 装配期环；仅在提供本人身份时才判专注拦截。
        from app.contexts.business.time_management.public import (
            is_user_focus_intercepting,
        )

        if await is_user_focus_intercepting(session, recipient_user_id):
            return False
    if is_chat:
        return await notify.send_text_to_chat(recipient, text)
    return await notify.send_text_to_user(recipient, text)


def feishu_notify_person_available() -> bool:
    """通知开关开即视为能力就绪（自门控）。个人/群定向不依赖固定运营群，故只看总开关。

    未开启 → 返 False → prompt_section 不广告、send_to_recipient no-op，生产逐字不变。
    """
    enabled = runtime_config.effective(
        "feishu_notify_enabled", get_settings().feishu_notify_enabled
    )
    return str(enabled).strip().lower() in ("true", "1", "yes")
