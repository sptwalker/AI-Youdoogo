"""Claim the short-lived denied Feishu identity and bind it to user ``zoey``.

Run only from a controlled operator shell:
    uv run python scripts/bind_captured_feishu_zoey.py --confirm-zoey

The captured open_id is never printed or accepted as command-line input.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

from app.core.database import async_session_factory  # noqa: E402
from app.core.exceptions import AppError  # noqa: E402
from app.services.feishu_login import OAuthUnavailable, get_feishu_login_service  # noqa: E402
from app.services.feishu_support import bind_captured_denied_identity_to_zoey  # noqa: E402

CONFIRM_FLAG = "--confirm-zoey"


async def main() -> int:
    """Perform the explicitly confirmed, fixed-target support binding."""
    if sys.argv[1:] != [CONFIRM_FLAG]:
        print(f"用法：uv run python scripts/bind_captured_feishu_zoey.py {CONFIRM_FLAG}")
        return 2

    service = get_feishu_login_service()
    try:
        async with async_session_factory() as db:
            try:
                user = await bind_captured_denied_identity_to_zoey(db, service)
            except OAuthUnavailable:
                print("失败：飞书支持捕获暂不可用")
                return 1
            except AppError as exc:
                print(f"失败：{exc.msg}")
                return 1
    finally:
        await service.close()

    print(f"飞书身份已绑定到用户：{user.username}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
