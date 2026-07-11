"""飞书客户端与通知模块单测（respx 拦截 HTTP，不真实外发）。"""

import json
from typing import Any

import httpx
import pytest
import respx

from app.core.config import get_settings
from app.integrations.feishu import notify
from app.integrations.feishu.client import FeishuClient

TOKEN_URL = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
MSG_URL = "https://open.feishu.cn/open-apis/im/v1/messages"


@pytest.fixture
def feishu_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """为测试注入飞书应用凭证（进程级 Settings 单例上打补丁）。"""
    settings = get_settings()
    monkeypatch.setattr(settings, "feishu_app_id", "cli_test")
    monkeypatch.setattr(settings, "feishu_app_secret", "secret_test")


def _mock_token_and_msg() -> tuple[respx.Route, respx.Route]:
    """挂载 token 与消息发送两个 mock 路由。"""
    token_route = respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(
            200, json={"code": 0, "tenant_access_token": "t-xyz", "expire": 7200}
        )
    )
    msg_route = respx.post(MSG_URL).mock(
        return_value=httpx.Response(200, json={"code": 0, "data": {"message_id": "om_1"}})
    )
    return token_route, msg_route


@respx.mock
async def test_tenant_token_cached(feishu_settings: None) -> None:
    """连续两次 send_text 只请求一次 tenant_access_token。"""
    token_route, msg_route = _mock_token_and_msg()
    client = FeishuClient()
    await client.send_text("u1", "hello")
    await client.send_text("u1", "world")
    assert token_route.call_count == 1
    assert msg_route.call_count == 2
    await client.close()


@respx.mock
async def test_send_text_request_body(feishu_settings: None) -> None:
    """send_text 请求体组包正确：receive_id / msg_type / content(JSON字符串)。"""
    _, msg_route = _mock_token_and_msg()
    client = FeishuClient()
    await client.send_text("ou_abc", "你好", receive_id_type="open_id")

    request = msg_route.calls.last.request
    assert request.url.params["receive_id_type"] == "open_id"
    body: dict[str, Any] = json.loads(request.content)
    assert body["receive_id"] == "ou_abc"
    assert body["msg_type"] == "text"
    assert json.loads(body["content"]) == {"text": "你好"}
    await client.close()


@respx.mock
async def test_notify_disabled_no_request(monkeypatch: pytest.MonkeyPatch) -> None:
    """feishu_notify_enabled=False 时 notify 所有方法 no-op，不发任何请求。"""
    monkeypatch.setattr(get_settings(), "feishu_notify_enabled", False)
    assert await notify.send_text_to_user("ou_abc", "hi") is False
    assert await notify.send_card_to_chat("oc_1", {"elements": []}) is False
    assert len(respx.calls) == 0
