#!/usr/bin/env python3
"""Send the standard six-field YOUDOOGO card to the shared organization chat."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

TZ = timezone(timedelta(hours=8))
PUBLIC_URL = "https://ai.youdoogo.com/"
CHAT_ID = "oc_aae2fdb8d29cc64e86efa7ce6c0e60da"


def env(name: str) -> str:
    return os.environ.get(name, "")


def card(mode: str) -> dict[str, object]:
    success = mode == "success"
    icon = "✅" if success else "❌"
    result = "成功" if success else "失败"
    title = f"{icon} YOUDOOGO 流水线{result} #{env('CI_PIPELINE_ID')}"
    content = "\n".join(
        [
            f"**流水线**：{env('CI_PIPELINE_URL')}",
            f"**分支**：{env('CI_COMMIT_BRANCH')}",
            f"**提交**：{env('CI_COMMIT_SHORT_SHA')} {env('CI_COMMIT_TITLE')}",
            f"**触发者**：{env('GITLAB_USER_NAME')}",
            f"**完成时间**：{datetime.now(TZ).strftime('%Y-%m-%d %H:%M:%S')}",
            f"**地址**：[YOUDOOGO]({PUBLIC_URL})",
        ]
    )
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": title},
            "template": "green" if success else "red",
        },
        "elements": [{"tag": "markdown", "content": content}],
    }


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode not in {"success", "failure"}:
        print(f"usage: {sys.argv[0]} success|failure", file=sys.stderr)
        return 1

    app_id = env("FEISHU_APP_ID")
    app_secret = env("FEISHU_APP_SECRET")
    if not app_id or not app_secret:
        print("[notify] Feishu credentials unavailable; notification skipped", file=sys.stderr)
        return 0

    token_request = urllib.request.Request(
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        data=json.dumps({"app_id": app_id, "app_secret": app_secret}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(token_request, timeout=10) as response:
            token_response = json.load(response)
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        print(f"[notify] token request failed: {exc}", file=sys.stderr)
        return 1
    token = str(token_response.get("tenant_access_token", ""))
    if not token:
        reason = token_response.get("msg", "unknown")
        print(f"[notify] token request rejected: {reason}", file=sys.stderr)
        return 1

    payload = {
        "receive_id": CHAT_ID,
        "msg_type": "interactive",
        "content": json.dumps(card(mode), ensure_ascii=False),
    }
    message_request = urllib.request.Request(
        "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id",
        data=json.dumps(payload, ensure_ascii=False).encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(message_request, timeout=15) as response:
            message_response = json.load(response)
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        print(f"[notify] send failed: {exc}", file=sys.stderr)
        return 1
    if message_response.get("code") != 0:
        print(f"[notify] send rejected: {message_response.get('msg', 'unknown')}", file=sys.stderr)
        return 1
    print("[notify] Feishu card sent")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
