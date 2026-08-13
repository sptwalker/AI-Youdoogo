"""Workflow-owned human-stop and mechanical-publish policy for capability steps."""

from __future__ import annotations

from dataclasses import replace

from app.contexts.foundations.execution.workflow_runtime.contracts.runtime import (
    WorkflowLaunchStep,
)

# 机械发布步键：真人验收 compose 草稿后由机械步做不可逆对外写——无 LLM、无二次真人停点。
# 对规划器/模板不可见（§8.4），只由 pair_publish_steps 配对生成。
MECHANICAL_CAPABILITIES: frozenset[str] = frozenset(
    {
        "feishu_publish",
        "feishu_notify_person_publish",
        "convene_consultation_publish",
        "send_email_publish",
        # 机械纪要步：读上游 convene 机械步产出的真 meeting 机械生成纪要（docs/26 §6，非发布步，
        # 由 legacy_execution._generate_minutes 专列分支处理，不走 pair_publish_steps 配对）。
        "generate_minutes",
    }
)

# 无需真人停点：只读取数/检索/交付/内部知识沉淀 + 内部顾问提案（不对外发送）+ 已被上游 compose
# 验收门控的机械步（含 generate_minutes）。
AUTOMATIC_CAPABILITIES: frozenset[str] = (
    frozenset(
        {
            "data_query",
            "knowledge_search",
            "deliver",
            "knowledge_index",
            "create_operational_proposal",
        }
    )
    | MECHANICAL_CAPABILITIES
)

# compose 红线键 → (机械发布键, 发布步标题, 发布步指令)。
_PUBLISH_PAIRINGS: dict[str, tuple[str, str, str]] = {
    "compose_feishu": ("feishu_publish", "发布飞书草稿", "将已验收的飞书草稿发布到飞书"),
    "feishu_notify_person": (
        "feishu_notify_person_publish",
        "发送定向飞书通知",
        "将已验收的定向飞书草稿发送到指定的人或群",
    ),
    "convene_consultation": (
        "convene_consultation_publish",
        "拉起紧急会商",
        "将已验收的会商草稿真正建会并定向通知品牌/销售/产品/法务负责人",
    ),
    "send_email": (
        "send_email_publish",
        "发送邮件",
        "将已验收的邮件草稿真正发送给指定收件人",
    ),
}

# 机械发布步会产出「消费型数据」（真会议）的红线 compose 键：下游若依赖这些 compose 步，须把依赖
# 改指向其机械发布步（真会议输出所在），否则 generate_minutes/邮件步拿不到 meeting。其余红线发布
# 步（飞书/邮件）无消费型产出，下游依赖保持指向 compose 即可。
_REPOINT_COMPOSE_KEYS: frozenset[str] = frozenset({"convene_consultation"})


def requires_human_review(capability_key: str) -> bool:
    return capability_key not in AUTOMATIC_CAPABILITIES


def is_mechanical(capability_key: str) -> bool:
    return capability_key in MECHANICAL_CAPABILITIES


def pair_publish_steps(
    steps: tuple[WorkflowLaunchStep, ...],
) -> tuple[WorkflowLaunchStep, ...]:
    """为每个红线 compose 步追加一个依赖它的机械发布步（compose→publish 两步 DAG，docs/14 §8）。

    规划器/模板只可见 compose 键；这里配出的 ``*_publish`` 机械步在真人验收 compose 草稿后才由
    机械步做不可逆对外写——就绪充要条件=依赖步 SUCCEEDED（见 step_leases.ready_steps），故真人
    验收前发布步结构性无法就绪。防御：上游若混入裸 ``*_publish`` 步一律丢弃，配对只由本函数生成。
    草稿经 pipe_outputs 流入机械步 input_data。
    """
    publish_keys = {spec[0] for spec in _PUBLISH_PAIRINGS.values()}
    kept = [step for step in steps if step.capability_key not in publish_keys]
    composes = [step for step in kept if step.capability_key in _PUBLISH_PAIRINGS]
    if not composes:
        return tuple(kept)
    next_number = max(step.number for step in kept) + 1
    extra: list[WorkflowLaunchStep] = []
    repoint: dict[int, int] = {}  # compose.number → publish.number（仅产真会议的 convene）
    for compose in composes:
        publish_key, title, instruction = _PUBLISH_PAIRINGS[compose.capability_key]
        extra.append(
            WorkflowLaunchStep(
                number=next_number,
                title=title,
                capability_key=publish_key,
                instruction=instruction,
                depends_on=(compose.number,),
            )
        )
        if compose.capability_key in _REPOINT_COMPOSE_KEYS:
            repoint[compose.number] = next_number
        next_number += 1
    if repoint:
        # 把下游对 convene compose 步的依赖改指向其机械发布步（真会议所在）；机械发布步本身仍依赖
        # compose（不改指向自己，否则成环），故只重写 kept（不含发布步）。
        kept = [
            replace(
                step,
                depends_on=tuple(repoint.get(dep, dep) for dep in step.depends_on),
            )
            for step in kept
        ]
    return tuple(kept) + tuple(extra)
