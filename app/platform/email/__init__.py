"""异步 SMTP 发信机制（技术层，无业务语义）。"""

from app.platform.email.client import SmtpConfig, send_email

__all__ = ["SmtpConfig", "send_email"]
