"""工作流模板（docs/25 P4）——数据驱动的钉死 DAG，重复性工作可复用调用。

一条记录 = 一张可复用的编排模板：steps 为固定步骤 JSON（按 agent_role.code 引用部门承接人），
发起时确定性展开成 WorkflowPlan（跳过 LLM 规划器），其余下游（pair_publish_steps→红线判定→
submit）与 LLM 路径逐字一致。department_id 为未来「部门自维护」预留（本轮不消费）；写者仅
workflow_templating Context（单写者）。
"""

import uuid
from typing import Any

from sqlalchemy import JSON, Boolean, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.platform.database.model import Base, CommonMixin

# JSONB 主类型；sqlite 单测下降级为通用 JSON，仅为 metadata.create_all 可跑
_JSONB = JSON().with_variant(JSONB(), "postgresql")


class WorkflowTemplate(CommonMixin, Base):
    """可复用工作流模板；写者仅 workflow_templating Context（单持久化写者）。"""

    __tablename__ = "workflow_template"

    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 归属部门（空=公司级）；为未来「部门只维护本部门模板」预留，本轮不消费。
    department_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("sys_department.id"), nullable=True
    )
    # 钉死的 DAG：[{no,title,skill,instruction,depends_on,expert_code}]（expert_code 可选）
    steps: Mapped[list[dict[str, Any]]] = mapped_column(_JSONB, default=list)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    # 骨架保护：种子模板不被误删
    is_seed: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
