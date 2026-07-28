"""评估集（H3.1，docs/16）：评估驱动开发的用例库。

每条用例 = 一个输入 + 评分标准(rubric)，绑定到某角色(role_id 空=通用)。
run_eval 用某提示词跑全部 active 用例、LLM-as-Judge 逐条打分，得聚合分;
shadow_compare 用「当前 vs 候选」提示词各跑一遍对比得分——让"改提示词是否变好"可量化。
红线:评估只产出分数与建议，提示词是否应用仍真人确认（不自动落地）。
"""

import uuid

from sqlalchemy import Boolean, ForeignKey, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.platform.database.model import Base, CommonMixin

_ACTIVE = text("is_delete = false")


class EvalCase(CommonMixin, Base):
    """一条评估用例:输入 + 评分标准。role_id 空=通用用例（对所有角色适用）。"""

    __tablename__ = "eval_case"
    __table_args__ = (Index("ix_eval_case_role", "role_id"),)

    name: Mapped[str] = mapped_column(String(128))
    role_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agent_role.id"), nullable=True
    )  # 空=通用；非空=仅评该角色
    input_text: Mapped[str] = mapped_column(Text)  # 喂给 AI 的输入
    rubric: Mapped[str] = mapped_column(Text)  # 评分标准（judge 依此打 1~5）
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
