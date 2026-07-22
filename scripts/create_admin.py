"""初始化管理员账号（数据库迁移完成后运行一次）。

用法：uv run python scripts/create_admin.py <用户名> [真实姓名]
密码交互式输入（不回显、不落命令行历史）。已存在同名用户则拒绝。
"""

from __future__ import annotations

import asyncio
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

from app.contexts.shared_kernel import ApplicationError  # noqa: E402
from app.core.database import async_session_factory  # noqa: E402
from app.schemas.auth import UserCreate  # noqa: E402
from app.services.auth_service import create_user  # noqa: E402


async def main() -> int:
    """创建 admin 角色用户。"""
    if len(sys.argv) < 2:
        print("用法：uv run python scripts/create_admin.py <用户名> [真实姓名]")
        return 1
    username = sys.argv[1]
    real_name = sys.argv[2] if len(sys.argv) > 2 else ""
    password = getpass.getpass("设置密码（≥8位）：")
    if password != getpass.getpass("再输一遍确认："):
        print("两次输入不一致")
        return 1
    async with async_session_factory() as db:
        try:
            user = await create_user(
                db,
                UserCreate(
                    username=username, password=password, real_name=real_name, role_code="admin"
                ),
            )
        except ApplicationError as exc:
            print(f"失败：{exc}")
            return 1
    print(f"管理员已创建：{user.username}（id={user.id}）")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
