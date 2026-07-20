"""Narrow offline support operation for the Feishu pre-binding flow."""

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.models.system import SysUser
from app.services.feishu_login import FeishuLoginService

SUPPORT_BIND_USERNAME = "zoey"


async def bind_captured_denied_identity_to_zoey(
    db: AsyncSession, service: FeishuLoginService
) -> SysUser:
    """Consume the pending support capture and bind it only to active user ``zoey``.

    The target is deliberately fixed so this helper cannot become a general-purpose
    self-service binding mechanism. A consumed capture is not restored on a database
    failure; the Feishu user must retry login to create a fresh short-lived capture.
    """
    stmt = (
        select(SysUser)
        .where(
            SysUser.username == SUPPORT_BIND_USERNAME,
            SysUser.is_delete.is_(False),
        )
        .with_for_update()
    )
    user = (await db.execute(stmt)).scalar_one_or_none()
    if user is None or not user.is_active:
        raise AppError("目标用户 zoey 不存在或不可用", code=409, status_code=409)
    if user.feishu_open_id is not None:
        raise AppError("目标用户 zoey 已绑定飞书身份", code=409, status_code=409)

    open_id = await service.consume_captured_denied_identity()
    if open_id is None:
        raise AppError("没有可领取的飞书拒绝身份或捕获已过期", code=404, status_code=404)

    user.feishu_open_id = open_id
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise AppError("捕获的飞书身份已绑定其他用户", code=409, status_code=409) from None
    except SQLAlchemyError:
        await db.rollback()
        raise AppError("飞书身份绑定失败，请让用户重新登录后再试", status_code=500) from None
    await db.refresh(user)
    return user
