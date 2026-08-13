"""Workflow-owned human-stop and mechanical-publish policy for capability steps."""

from __future__ import annotations

from app.contexts.foundations.execution.workflow_runtime.contracts.runtime import (
    WorkflowLaunchStep,
)

# 机械发布步键：真人验收 compose 草稿后由机械步做不可逆对外写——无 LLM、无二次真人停点。
# 对规划器/模板不可见（§8.4），只由 pair_publish_steps 配对生成。
MECHANICAL_CAPABILITIES: frozenset[str] = frozenset({"feishu_publish"})

# 无需真人停点：只读取数/交付/内部知识沉淀 + 已被上游 compose 验收门控的机械发布步。
AUTOMATIC_CAPABILITIES: frozenset[str] = (
    frozenset({"data_query", "deliver", "knowledge_index"}) | MECHANICAL_CAPABILITIES
)

# compose 红线键 → (机械发布键, 发布步标题, 发布步指令)。
# ponytail: 目前仅飞书；send_email/feishu_notify_person/convene 落地时各加一行即复用整套编排。
#           convene 的机械步会产 meeting 数据集供下游消费，届时需补「下游依赖改指向机械步」的
#           repoint 逻辑（当前无消费方，YAGNI）。
_PUBLISH_PAIRINGS: dict[str, tuple[str, str, str]] = {
    "compose_feishu": ("feishu_publish", "发布飞书草稿", "将已验收的飞书草稿发布到飞书"),
}


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
        next_number += 1
    return tuple(kept) + tuple(extra)
