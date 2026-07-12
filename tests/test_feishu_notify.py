"""飞书运营推送单测（不发真实请求）：开关关闭静默、开启则发到运营群。"""

from typing import Any

import pytest

from app.core.config import get_settings
from app.integrations.feishu import notify
from app.integrations.feishu.client import feishu_client


async def test_push_disabled_is_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "feishu_notify_enabled", False)
    monkeypatch.setattr(get_settings(), "feishu_ops_chat_id", "oc_x")
    assert await notify.push_ops_message("hi") is False


async def test_push_no_chat_is_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "feishu_notify_enabled", True)
    monkeypatch.setattr(get_settings(), "feishu_ops_chat_id", "")
    assert await notify.push_ops_message("hi") is False


async def test_push_enabled_sends_to_chat(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "feishu_notify_enabled", True)
    monkeypatch.setattr(get_settings(), "feishu_ops_chat_id", "oc_ops")
    sent: dict[str, Any] = {}

    async def _fake_send_text(receive_id: str, text: str, receive_id_type: str = "user_id") -> dict:
        sent.update(receive_id=receive_id, text=text, receive_id_type=receive_id_type)
        return {}

    monkeypatch.setattr(feishu_client, "send_text", _fake_send_text)
    assert await notify.push_ops_message("运营日报正文") is True
    assert sent == {"receive_id": "oc_ops", "text": "运营日报正文", "receive_id_type": "chat_id"}
