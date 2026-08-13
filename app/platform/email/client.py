"""异步 SMTP 客户端——纯技术机制，无业务/收件人解析语义，供任意 Context 复用。

TLS（STARTTLS）+ 超时 + 有界重试（网络类瞬时错误重试，鉴权/协议类错误不重试，避免锁死账号）。
凭证/收件人/正文均不入日志（隐私 + CLAUDE.md 开发铁律#4：日志不打凭证/正文）。
# ponytail: 纯文本/简单 HTML 正文即可，附件/富模板留到有需求再加。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from email.message import EmailMessage

import aiosmtplib

logger = logging.getLogger(__name__)

_MAX_ATTEMPTS = 3
_TIMEOUT_SECONDS = 10.0


@dataclass(frozen=True, slots=True)
class SmtpConfig:
    """SMTP 连接参数（由调用方从 config/runtime_config 装配，本模块不读配置）。"""

    host: str
    port: int
    username: str
    password: str
    from_addr: str


async def send_email(config: SmtpConfig, to: str, subject: str, body: str) -> bool:
    """发一封纯文本邮件；host 未配置直接返 False（调用方判定"未配置"）。

    网络类瞬时错误（连接/超时）有界重试 _MAX_ATTEMPTS 次；鉴权/协议类错误
    （SMTPResponseException 等）不重试，直接返 False，避免反复触发目标 SMTP 服务的鉴权失败锁定。
    """
    if not config.host or not to:
        return False
    message = EmailMessage()
    message["From"] = config.from_addr or config.username
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)

    last_error: Exception | None = None
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            await aiosmtplib.send(
                message,
                hostname=config.host,
                port=config.port,
                username=config.username or None,
                password=config.password or None,
                start_tls=True,
                timeout=_TIMEOUT_SECONDS,
            )
            return True
        except (
            aiosmtplib.SMTPConnectError,
            aiosmtplib.SMTPTimeoutError,
            TimeoutError,
            OSError,
        ) as exc:
            last_error = exc
            logger.warning(
                "SMTP 发送第 %d 次瞬时失败，%s",
                attempt,
                "重试" if attempt < _MAX_ATTEMPTS else "放弃",
            )
            continue
        except Exception as exc:  # noqa: BLE001 - 鉴权/协议类错误不重试，如实记录后安全返回
            last_error = exc
            break
    logger.warning("SMTP 发送失败：%s", type(last_error).__name__ if last_error else "未知错误")
    return False
