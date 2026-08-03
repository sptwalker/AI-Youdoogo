"""统一语义层：业务术语/指标字典（docs/15 §4.2）。

泛化 TdEventAlias（事件码→中文名）为通用术语字典:规范名 + 别名 + 定义 + 类型 + 关联数据。
两个用途:①提示词注入统一跨部门口径 ②别名→规范名查询扩展喂给关键词臂。
非知识图谱本体（决策3 轻量字典）;不触发任何业务决议，只提供口径与参考。
"""

import uuid
from typing import Any

from sqlalchemy import JSON, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.platform.database.model import Base, CommonMixin

_JSONB = JSON().with_variant(JSONB(), "postgresql")
_ACTIVE = text("is_delete = false")  # 部分唯一索引条件（软删后可重建同名）

# term_type 取值
TERM_METRIC = "metric"  # 指标（累计激活设备数…）：可关联 TD 视图/取数模板
TERM_DIMENSION = "dimension"  # 维度（渠道、地区…）
TERM_ENTITY = "entity"  # 实体（产品、部门…）


class SemanticTerm(CommonMixin, Base):
    """一条业务术语：规范名 + 别名集 + 定义 + 类型 + 关联数据。

    唯一键 = canonical_name（同一规范名不重复；软删后可重建）。
    aliases 存别名/同义词列表，供查询扩展命中任一别名即映射到规范名。
    """

    __tablename__ = "semantic_term"
    __table_args__ = (
        Index("uq_semantic_canonical", "canonical_name", unique=True, postgresql_where=_ACTIVE),
    )

    canonical_name: Mapped[str] = mapped_column(String(128))  # 规范名
    aliases: Mapped[list[str]] = mapped_column(_JSONB, default=list)  # 别名/同义词
    term_type: Mapped[str] = mapped_column(String(16), default=TERM_METRIC)
    definition: Mapped[str | None] = mapped_column(Text, nullable=True)  # 口径定义
    linked_view: Mapped[str | None] = mapped_column(String(64), nullable=True)  # 指标关联 TD 视图
    sql_template: Mapped[str | None] = mapped_column(Text, nullable=True)  # 指标取数模板
    kb_refs: Mapped[list[str]] = mapped_column(_JSONB, default=list)  # 关联 KB 文档引用
    department_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("sys_department.id"), nullable=True
    )  # 归属范围（空=全公司通用）

    def as_dict(self) -> dict[str, Any]:
        """序列化为接口/提示词可用的普通 dict。"""
        return {
            "id": str(self.id),
            "canonical_name": self.canonical_name,
            "aliases": list(self.aliases or []),
            "term_type": self.term_type,
            "definition": self.definition,
            "linked_view": self.linked_view,
            "sql_template": self.sql_template,
            "kb_refs": list(self.kb_refs or []),
            "department_id": str(self.department_id) if self.department_id else None,
        }
