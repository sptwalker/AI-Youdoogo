"""营销舆情应急响应种子模板扩为 docs/26 §6 终态 8 步

Revision ID: 045_marketing_sentiment_template_full
Revises: 044_sys_user_email
Create Date: 2026-08-13

加法式：把 043 种的同名种子模板「营销舆情应急响应」的 steps 由 3 步更新为 docs/26 §6 终态 8 步
（全部为已注册可派发 skill，无表结构变更）：
  0 data_query 取舆情 → 1 deliver 简报与建议 → 2 create_operational_proposal 运营优化提案〔顾问〕
  → 3 feishu_notify_person 定向转发〔红线·compose 停点〕
  → 4 convene_consultation 紧急会商〔红线·compose 停点〕
  → 5 knowledge_search 检索历史案例 → 6 generate_minutes 机械纪要
  → 7 send_email 邮件同步〔红线·compose 停点〕。

依赖设计：5/6/7 在模板里 depends_on convene 的 **compose 步 no=4**；运行期由
workflow_runtime.domain.policies.pair_publish_steps 把 convene 下游依赖「改指向」插入的 convene
机械发布步——真会议（记为 kind=meeting 的 artifact）在那步产生，generate_minutes(6) 才能拿真
meeting_id。详见 legacy_execution._meeting_artifact / step_completion.pipe_outputs（数据只流向直接
下游）。

# ponytail: 按名 + is_seed update 同一行（无 by-name 查询，模板量小），downgrade 恢复 043 的 3 步。
"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "045_marketing_sentiment_template_full"
down_revision: str | None = "044_sys_user_email"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_JSONB = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")

_TEMPLATE_NAME = "营销舆情应急响应"
_MKT = "dir_marketing"  # 营销总监（取数/简报/转发/会商/邮件承接人）
_OPS = "dir_platform_ops"  # 平台运营总监（运营提案承接人）

# 终态 8 步（no 与 depends_on 全 0-indexed）。红线 3/4/7 走 compose→机械发布两步拆分：
# 模板只登记 compose key，机械发布步由 pair_publish_steps 运行期插入。
_STEPS_FULL: list[dict[str, object]] = [
    {"no": 0, "title": "取舆情数据", "skill": "data_query",
     "expert_code": _MKT,
     "instruction": "拉取本次告警渠道的舆情明细（负面评论/竞品动作/政策原文），"
                    "若暂无对接的外部舆情数据源则如实说明数据缺口、不得臆造或编造数据",
     "depends_on": []},
    {"no": 1, "title": "生成舆情简报与应对建议", "skill": "deliver",
     "expert_code": _MKT,
     "instruction": "结合告警与检索到的历史案例，生成一句话定性的舆情简报与初步应对建议"
                    "（含影响面、紧急度、建议动作），供相关负责人研判",
     "depends_on": [0]},
    {"no": 2, "title": "生成运营优化提案",
     "skill": "create_operational_proposal", "expert_code": _OPS,
     "instruction": "就本次舆情反映出的运营问题，请平台运营总监助理产出一份含背景/目标/方案/"
                    "收益风险/优先级的运营优化提案（仅供管理层参考、不构成决策、不对外发送）",
     "depends_on": [1]},
    {"no": 3, "title": "定向转发相关负责人", "skill": "feishu_notify_person",
     "expert_code": _MKT,
     "instruction": "把舆情简报与应对建议整理成定向飞书草稿，转发给品牌/销售/产品/法务相关负责人"
                    "〔红线：对外触达前须真人验收，本步只产草稿、验收后机械发布〕",
     "depends_on": [1]},
    {"no": 4, "title": "发起跨部门紧急会商", "skill": "convene_consultation",
     "expert_code": _MKT,
     "instruction": "把跨部门紧急会商议题整理成草稿〔红线：本步只产议题草稿、不建会不通知，"
                    "验收后机械步才真建会并定向通知品牌/销售/产品/法务负责人〕",
     "depends_on": [1]},
    {"no": 5, "title": "检索历史处置案例", "skill": "knowledge_search",
     "expert_code": _MKT,
     "instruction": "在可见知识库中检索历史同类舆情的处置参考与复盘结论，回喂供会商与纪要引用"
                    "（只读，无对外副作用）",
     "depends_on": [4]},
    {"no": 6, "title": "生成会商纪要", "skill": "generate_minutes",
     "expert_code": _MKT,
     "instruction": "为已发起的紧急会商机械生成会议纪要（读上游会议，验收后自动执行）",
     "depends_on": [4]},
    {"no": 7, "title": "邮件同步纪要与结论", "skill": "send_email",
     "expert_code": _MKT,
     "instruction": "把会商纪要与最终结论整理成邮件草稿，同步给与会负责人"
                    "〔红线：本步只产邮件草稿、不发邮件，验收后机械步才真发〕",
     "depends_on": [4]},
]

# 043 的原始 3 步（供 downgrade 恢复）。
_STEPS_MIN: list[dict[str, object]] = [
    {"no": 0, "title": "取舆情数据", "skill": "data_query",
     "expert_code": _MKT,
     "instruction": "拉取本次告警渠道的舆情明细（负面评论/竞品动作/政策原文），"
                    "若暂无对接的外部舆情数据源则如实说明数据缺口、不得臆造或编造数据",
     "depends_on": []},
    {"no": 1, "title": "生成舆情简报与应对建议", "skill": "deliver",
     "expert_code": _MKT,
     "instruction": "结合告警与检索到的历史案例，生成一句话定性的舆情简报与初步应对建议"
                    "（含影响面、紧急度、建议动作），供相关负责人研判",
     "depends_on": [0]},
    {"no": 2, "title": "定向转发相关负责人", "skill": "feishu_notify_person",
     "expert_code": _MKT,
     "instruction": "把舆情简报与应对建议定向转发给品牌/销售/产品/法务相关负责人〔红线：对外触达前"
                    "须真人确认，此步停 waiting_human 待人工放行〕",
     "depends_on": [1]},
]

_template = sa.table(
    "workflow_template",
    sa.column("name", sa.String()),
    sa.column("steps", _JSONB),
    sa.column("is_seed", sa.Boolean()),
)


def _set_steps(steps: list[dict[str, object]]) -> None:
    op.execute(
        _template.update()
        .where(_template.c.name == _TEMPLATE_NAME)
        .where(_template.c.is_seed.is_(True))
        .values(steps=steps)
    )


def upgrade() -> None:
    _set_steps(_STEPS_FULL)


def downgrade() -> None:
    _set_steps(_STEPS_MIN)
