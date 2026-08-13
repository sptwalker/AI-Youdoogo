"""Entrypoint 网关：解析收件人（按 username 查邮箱） + 装配 SMTP 配置 + 发送。

跨 Context 只走门面（identity.get_user_by_username），零直连 identity ORM/repository。
SMTP 配置经 runtime_config.effective() 覆盖层读取（sys_config 覆盖 .env，镜像 web_search_api_key）。
收件人无 email / SMTP 未配置 → 如实声明并安全跳过，不臆造地址（CLAUDE.md 红线）。
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.identity import public as identity
from app.core import runtime_config
from app.core.config import get_settings
from app.platform.email.client import SmtpConfig, send_email


@dataclass(frozen=True, slots=True)
class SendEmailResult:
    """发送结果：成败 + 如实声明的原因（供执行器回喂 notes）。"""

    sent: bool
    reason: str | None = None  # 未发送时的原因说明（未配置/无邮箱/发送失败）


def _smtp_config() -> SmtpConfig:
    settings = get_settings()
    return SmtpConfig(
        host=str(runtime_config.effective("smtp_host", settings.smtp_host) or ""),
        port=int(runtime_config.effective("smtp_port", settings.smtp_port) or settings.smtp_port),
        username=str(runtime_config.effective("smtp_username", settings.smtp_username) or ""),
        password=str(runtime_config.effective("smtp_password", settings.smtp_password) or ""),
        from_addr=str(runtime_config.effective("smtp_from_addr", settings.smtp_from_addr) or ""),
    )


def send_email_available() -> bool:
    """SMTP 是否已配置（host 非空）——供机械发布器 available() 判定是否放行本步。"""
    return bool(_smtp_config().host)


async def send_to_username(
    session: AsyncSession,
    *,
    username: str,
    subject: str,
    body: str,
) -> SendEmailResult:
    """按 username 解析收件人邮箱并发送；缺配置/缺邮箱如实声明安全跳过。"""
    config = _smtp_config()
    if not config.host:
        return SendEmailResult(sent=False, reason="SMTP 未配置，已安全跳过")

    user = await identity.get_user_by_username(session, username=username)
    if user is None:
        return SendEmailResult(sent=False, reason=f"未找到账号 {username}，已安全跳过")
    if not user.email:
        return SendEmailResult(sent=False, reason=f"{username} 无工作邮箱，已安全跳过")

    sent = await send_email(config, to=user.email, subject=subject, body=body)
    if not sent:
        return SendEmailResult(sent=False, reason="邮件发送失败")
    return SendEmailResult(sent=True)
