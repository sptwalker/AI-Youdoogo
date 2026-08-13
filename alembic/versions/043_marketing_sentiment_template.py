"""种营销舆情应急响应种子模板（docs/26 P2 拱心石最小闭环）

Revision ID: 043_marketing_sentiment_template
Revises: 042_workflow_template
Create Date: 2026-08-13

加法式：只在 workflow_template 表种一张 is_seed 模板「营销舆情应急响应」（3 步，仅用可派发
skill：data_query 取舆情 → deliver 简报与应对建议 → feishu_notify_person 定向转发〔红线〕）。
无表结构变更、无新列。模板 enabled，但事件响应由 sentiment_response_enabled 自门控（默认关）；
发起仍走 report_scheduler._start_workflow 同一 is_red_line——对外步骤前必停 waiting_human。

# ponytail: docs/26 §6 终态 8 步含 http_api/create_operational_proposal/convene_consultation/
#   send_email，但前者不可派发（connector 侧）、后三者对应能力 P3/P4/P5 才落地。P2 拱心石
#   只需证明「检测→发事件→展开模板→start〔红线停点〕」闭环，故种最小 3 步；终态待 P5 扩。
"""
import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "043_marketing_sentiment_template"
down_revision: str | None = "042_workflow_template"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_JSONB = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")

_TEMPLATE_NAME = "营销舆情应急响应"
_MKT = "dir_marketing"  # 营销总监（取数/简报/转发承接人）

_STEPS: list[dict[str, object]] = [
    {"no": 0, "title": "取舆情数据", "skill": "data_query", "expert_code": _MKT,
     "instruction": "拉取本次告警渠道的舆情明细（负面评论/竞品动作/政策原文），"
                    "若暂无对接的外部舆情数据源则如实说明数据缺口、不得臆造或编造数据",
     "depends_on": []},
    {"no": 1, "title": "生成舆情简报与应对建议", "skill": "deliver", "expert_code": _MKT,
     "instruction": "结合告警与检索到的历史案例，生成一句话定性的舆情简报与初步应对建议"
                    "（含影响面、紧急度、建议动作），供相关负责人研判",
     "depends_on": [0]},
    {"no": 2, "title": "定向转发相关负责人", "skill": "feishu_notify_person", "expert_code": _MKT,
     "instruction": "把舆情简报与应对建议定向转发给品牌/销售/产品/法务相关负责人〔红线：对外触达前"
                    "须真人确认，此步停 waiting_human 待人工放行〕",
     "depends_on": [1]},
]

_template = sa.table(
    "workflow_template",
    sa.column("id", sa.Uuid()),
    sa.column("is_delete", sa.Boolean()),
    sa.column("name", sa.String()),
    sa.column("description", sa.Text()),
    sa.column("department_id", sa.Uuid()),
    sa.column("steps", _JSONB),
    sa.column("enabled", sa.Boolean()),
    sa.column("is_seed", sa.Boolean()),
)


def upgrade() -> None:
    op.bulk_insert(
        _template,
        [
            {
                "id": uuid.uuid4(),
                "is_delete": False,
                "name": _TEMPLATE_NAME,
                "description": "舆情异常命中后系统发起：取舆情→简报与建议→定向转发〔红线停点〕。",
                "department_id": None,
                "steps": _STEPS,
                "enabled": True,
                "is_seed": True,
            }
        ],
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "DELETE FROM workflow_template WHERE name = :name AND is_seed = true"
        ).bindparams(name=_TEMPLATE_NAME)
    )
