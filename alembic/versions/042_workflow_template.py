"""workflow_template: 模板底座 + 种月度经营报告模板 + report_schedule.template_id（docs/25 P4）

Revision ID: 042_workflow_template
Revises: 041_report_schedule
Create Date: 2026-08-13

加法式：建 workflow_template 表；report_schedule 加 template_id nullable FK；种一张 is_seed 月报
模板（10 步，按 agent_role.code 派 6 部门，展开时 pair_publish_steps 自动 +1 feishu_publish 共
11≤16）；按 name 把 041 种子 schedule 指向该模板。**模板 enabled，但 schedule 仍 enabled=false /
creator_id=NULL**——三重保险不变，未激活前生产逐字不变；发起仍走 start 同一 is_red_line 入口。
"""
import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "042_workflow_template"
down_revision: str | None = "041_report_schedule"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_JSONB = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")

# 无内部业务数据源的 5 部门（生产/销售/研发/宣传/财务）：取数步显式要求「无源即如实声明缺口、
# 不臆造」——守诚实红线。运营维度有 thinkingdata 真实源；外网数据经 read_url。
_NO_SOURCE = "，若暂无对接的内部业务数据源则如实说明数据缺口、不得臆造或编造数据"
_OPS = "dir_platform_ops"  # 运营总监（汇总/交付/入库承接人），缩写以控行宽

_STEPS: list[dict[str, object]] = [
    {"no": 0, "title": "取生产维度数据", "skill": "data_query", "expert_code": "dir_product_base",
     "instruction": "查询本月生产/基础产品维度经营数据" + _NO_SOURCE, "depends_on": []},
    {"no": 1, "title": "取销售维度数据", "skill": "data_query", "expert_code": "dir_marketing",
     "instruction": "查询本月销售/营销维度经营数据" + _NO_SOURCE, "depends_on": []},
    {"no": 2, "title": "取研发维度数据", "skill": "data_query", "expert_code": "dir_game_rd",
     "instruction": "查询本月游戏研发维度经营数据" + _NO_SOURCE, "depends_on": []},
    {"no": 3, "title": "取宣传维度数据", "skill": "data_query", "expert_code": "dir_brand",
     "instruction": "查询本月品牌宣传维度经营数据" + _NO_SOURCE, "depends_on": []},
    {"no": 4, "title": "取运营维度数据", "skill": "data_query", "expert_code": _OPS,
     "instruction": "查询本月平台运营维度经营数据（运营指标可取 thinkingdata 真实数据源）",
     "depends_on": []},
    {"no": 5, "title": "取财务维度数据", "skill": "data_query", "expert_code": "dir_finance",
     "instruction": "查询本月财务维度经营数据" + _NO_SOURCE, "depends_on": []},
    {"no": 6, "title": "汇总分析生成报告初稿", "skill": "deliver", "expert_code": _OPS,
     "instruction": "汇总六部门数据并对比知识库历史数据，做趋势分析与问题识别，生成标准化的月度经营"
                    "报告初稿（含关键指标、趋势、问题与建议）",
     "depends_on": [0, 1, 2, 3, 4, 5]},
    {"no": 7, "title": "整理飞书文档报告", "skill": "compose_feishu", "expert_code": _OPS,
     "instruction": "把月度经营报告初稿整理成飞书云文档（红线草稿，待真人验收后再发布）",
     "depends_on": [6]},
    {"no": 8, "title": "生成 PPT 初稿", "skill": "deliver", "expert_code": _OPS,
     "instruction": "把月度经营报告初稿生成为 PPT 演示初稿（pptx 格式）", "depends_on": [6]},
    {"no": 9, "title": "报告留存知识库", "skill": "knowledge_index", "expert_code": _OPS,
     "instruction": "把已生成的月度经营报告留存到公司知识库，供日后检索复用", "depends_on": [6]},
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
    op.create_table(
        "workflow_template",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("create_time", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("update_time", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("is_delete", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "department_id", sa.Uuid(), sa.ForeignKey("sys_department.id"), nullable=True
        ),
        sa.Column("steps", _JSONB, nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("is_seed", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "report_schedule",
        sa.Column(
            "template_id",
            sa.Uuid(),
            sa.ForeignKey("workflow_template.id"),
            nullable=True,
        ),
    )
    template_id = uuid.uuid4()
    op.bulk_insert(
        _template,
        [
            {
                "id": template_id,
                "is_delete": False,
                "name": "月度经营报告",
                "description": "按依赖向 6 部门派发取数→运营汇总分析→飞书报告(红线草稿)+PPT+入库。",
                "department_id": None,
                "steps": _STEPS,
                "enabled": True,
                "is_seed": True,
            }
        ],
    )
    # 041 种子行 id 运行期随机，按 name 更新指向本模板（该行仍 enabled=false / creator_id=NULL）。
    op.execute(
        sa.text(
            "UPDATE report_schedule SET template_id = :tid "
            "WHERE name = '月度经营报告' AND is_delete = false"
        ).bindparams(tid=template_id)
    )


def downgrade() -> None:
    op.drop_column("report_schedule", "template_id")
    op.drop_table("workflow_template")
