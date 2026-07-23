"""对话归档兜底：遍历所有 active 真人，把超过保留期的旧桌面对话归档进各自助理的记忆库。

主触发是「用户打开工作桌面时懒扫」；本脚本供宿主 OS cron 兜底扫到不常登录的用户。
用法：uv run python scripts/archive_conversations.py
cron 例（每天4点）：0 4 * * * cd /opt/youdoo && uv run python scripts/archive_conversations.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # 允许以脚本方式直跑
sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]  # Windows GBK 控制台兼容

from sqlalchemy import select  # noqa: E402

from app.contexts.business.assistant_conversations.application.contracts import (  # noqa: E402
    Principal,
)
from app.contexts.business.assistant_conversations.entrypoints import (  # noqa: E402
    operations as assistant_conversations,
)
from app.core.database import async_session_factory  # noqa: E402
from app.models.system import SysUser  # noqa: E402


def _principal(user: SysUser) -> Principal:
    return Principal(
        id=user.id,
        display_name=user.real_name or user.username,
        department_id=user.department_id,
    )


async def _run() -> int:
    total = 0
    async with async_session_factory() as db:
        users = list(
            (
                await db.execute(
                    select(SysUser).where(SysUser.is_active.is_(True), SysUser.is_delete.is_(False))
                )
            ).scalars()
        )
        for user in users:
            try:
                n = await assistant_conversations.archive_old(db, _principal(user))
            except Exception as exc:  # noqa: BLE001 - 单个用户失败不影响其余
                print(f"用户 {user.username} 归档失败：{exc}")
                continue
            if n:
                print(f"用户 {user.username}：归档 {n} 条旧对话")
                total += n
    print(f"完成，共归档 {total} 条。")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_run()))
