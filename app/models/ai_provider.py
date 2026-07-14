"""AI 模型卡片（迁移 019）：动态多 Provider 管理，取代固定预置密钥项。

每张卡片 = 一个 OpenAI 兼容端点（名称/档位/地址/Key/模型）。档位 tier(daily/reasoning)
对接 agent_role.model_role：日常任务用 daily 卡片、会商/提案预研用 reasoning 卡片。
同档位内 is_primary 唯一（主用），其余 active 卡片作 failover。必须建卡片才能用 AI。
api_key 存本表（is_secret 语义）：list 脱敏只回 api_key_hint(末4位)，绝不回显明文。
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CommonMixin

TIER_DAILY = "daily"
TIER_REASONING = "reasoning"
VALID_TIERS = (TIER_DAILY, TIER_REASONING)


class AiProvider(CommonMixin, Base):
    """一张 AI 模型卡片。"""

    __tablename__ = "ai_provider"
    __table_args__ = (Index("ix_ai_provider_tier_active", "tier", "is_active"),)

    name: Mapped[str] = mapped_column(String(64))
    tier: Mapped[str] = mapped_column(String(16), default=TIER_DAILY, server_default=TIER_DAILY)
    base_url: Mapped[str] = mapped_column(String(512))
    api_key: Mapped[str] = mapped_column(String(512), default="", server_default="")
    api_key_hint: Mapped[str] = mapped_column(String(16), default="", server_default="")
    model: Mapped[str] = mapped_column(String(128))
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    # 连通测试结果（test 端点落库；list 回显状态灯）
    last_test_status: Mapped[str] = mapped_column(
        String(16), default="untested", server_default="untested"
    )  # ok / fail / untested
    last_test_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_test_latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_test_msg: Mapped[str | None] = mapped_column(String(256), nullable=True)
