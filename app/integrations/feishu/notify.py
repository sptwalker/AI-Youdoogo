"""飞书消息通知（best-effort 高层封装）。

所有发送受配置开关 feishu_notify_enabled 控制：关闭时（默认）所有方法为
无操作（no-op），开发与测试期间不会真实外发。发送失败只记日志、不抛异常。
方法仅接收纯值（str/dict 等，而非 ORM 对象），以便在请求结束、数据库会话
关闭后的后台任务中安全执行。
"""

import logging
from typing import Any

from app.core.config import get_settings
from app.integrations.feishu.client import FeishuAPIError, feishu_client

logger = logging.getLogger(__name__)


def _enabled() -> bool:
    """通知全局开关。"""
    return bool(get_settings().feishu_notify_enabled)


async def send_text_to_user(user_open_id: str, text: str) -> bool:
    """向用户私聊发送纯文本（receive_id_type=open_id），返回是否实际发送。"""
    if not _enabled():
        logger.debug("Feishu notify disabled; skip sending text")
        return False
    if not user_open_id:
        logger.debug("No user_open_id; skip sending text")
        return False
    try:
        await feishu_client.send_text(user_open_id, text, receive_id_type="open_id")
        return True
    except FeishuAPIError as e:
        # 通知为尽力而为，失败不应影响主流程
        logger.warning("Failed to send Feishu text: %s", e)
        return False


async def send_card_to_chat(chat_id: str, card: dict[str, Any]) -> bool:
    """向群聊发送交互式卡片（receive_id_type=chat_id），返回是否实际发送。"""
    if not _enabled():
        logger.debug("Feishu notify disabled; skip sending card")
        return False
    if not chat_id:
        logger.debug("No chat_id; skip sending card")
        return False
    try:
        await feishu_client.send_card(chat_id, card, receive_id_type="chat_id")
        return True
    except FeishuAPIError as e:
        # 通知为尽力而为，失败不应影响主流程
        logger.warning("Failed to send Feishu card: %s", e)
        return False


async def send_text_to_chat(chat_id: str, text: str) -> bool:
    """向群聊发送纯文本（receive_id_type=chat_id），返回是否实际发送。"""
    if not _enabled():
        logger.debug("Feishu notify disabled; skip sending chat text")
        return False
    if not chat_id:
        logger.debug("No chat_id; skip sending chat text")
        return False
    try:
        await feishu_client.send_text(chat_id, text, receive_id_type="chat_id")
        return True
    except FeishuAPIError as e:
        logger.warning("Failed to send Feishu chat text: %s", e)
        return False


async def push_ops_message(text: str) -> bool:
    """把运营日报/告警等文本推送到配置的运营群（feishu_ops_chat_id）。

    best-effort：未开启通知或未配置群时静默跳过，返回是否实际发送。
    """
    return await send_text_to_chat(get_settings().feishu_ops_chat_id, text)
