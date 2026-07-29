"""资产迁移盘点（D5 / docs/21 §D「盘点专家、Prompt、Skill、Tool 和工作流数据」）。

产出**只读** JSON 迁移基线：每类资产的计数 + 归属 Context + 来源，外加迁移最关心的两条
跨界依赖——工作流→专家（assignee_agent_id）、step.skill→能力注册表。拆平台时这两条边断了
就会「工作流引用了将被拆走的专家」或「step 引用了注册表里已不存在的 skill（功能丢失）」。

归属是静态事实（docs/20 所有权图派生，非可查询）；计数打真库；skill/tool 是 in-code 注册表
（`CAPABILITY_DEFINITIONS`，无 DB 表）。纯函数（skill_coverage/dangling_refs）无 DB、可单测导入。

用法：uv run python scripts/inventory_assets.py [--out baseline.json]
  省略 --out 打到 stdout（管道友好）。仅统计未软删（is_delete=false）的活跃资产。
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass

# 资产 → 归属限界上下文（docs/20 所有权图 / docs/21 平台边界派生，静态事实，非查询）。
OWNERSHIP: dict[str, str] = {
    "expert": "foundations/workforce/expert_management",
    "prompt": "foundations/workforce/expert_management + foundations/governance",
    "skill_tool": "foundations/execution/capability_catalog",
    "tool_execution": "foundations/execution/capability_execution",
    "workflow": "foundations/execution/workflow_runtime",
}


@dataclass(frozen=True)
class SkillCoverage:
    """step.skill 对能力注册表的覆盖。orphans 非空 = 迁移会丢功能（引用了注册表没有的 skill）。"""

    defined: tuple[str, ...]  # 注册表现有 key
    referenced: tuple[str, ...]  # workflow_step 实际引用过的 skill（去重）
    orphans: tuple[str, ...]  # referenced - defined，迁移风险点


def skill_coverage(referenced: Iterable[str], defined: Iterable[str]) -> SkillCoverage:
    """引用的 skill 里哪些注册表已没有（orphan）。空串引用忽略（step 建时可能未填）。"""
    defined_set = {key for key in defined if key}
    ref_set = {key for key in referenced if key}
    orphans = tuple(sorted(ref_set - defined_set))
    return SkillCoverage(tuple(sorted(defined_set)), tuple(sorted(ref_set)), orphans)


def dangling_refs(referenced_ids: Iterable[str], existing_ids: Iterable[str]) -> tuple[str, ...]:
    """引用了但已不存在的外键目标（如 workflow.assignee_agent_id 指向已删专家）。None 引用忽略。"""
    existing = {str(i) for i in existing_ids}
    return tuple(sorted({str(i) for i in referenced_ids if i is not None} - existing))


# ponytail: 计数 + 两条关键跨界边够作迁移基线；逐行孤儿明细/全字段快照留 D6 对账脚本，
# 需要时按 orphans/dangling 的 id 回捞。批量归属重写也归 D6（本轮只读盘点，不改数据）。


async def _run() -> dict[str, object]:
    from sqlalchemy import func, select

    from app.contexts.foundations.execution.capability_catalog.infrastructure.registry import (
        CAPABILITY_DEFINITIONS,
    )
    from app.core.database import async_session_factory
    from app.models.agent import AgentRole
    from app.models.sys_config import CAT_PROMPT, SysConfig
    from app.models.workflow import ToolExecution, WorkflowRun, WorkflowStep

    def _active(model: type) -> object:
        return model.is_delete == False  # noqa: E712 - SQL 列比较，非 Python 布尔

    async with async_session_factory() as db:

        async def _count(stmt: object) -> int:
            return int((await db.execute(stmt)).scalar_one())

        # 专家
        experts_total = await _count(
            select(func.count()).select_from(AgentRole).where(_active(AgentRole))
        )
        experts_personal = await _count(
            select(func.count())
            .select_from(AgentRole)
            .where(_active(AgentRole), AgentRole.owner_user_id.is_not(None))
        )
        experts_seed = await _count(
            select(func.count())
            .select_from(AgentRole)
            .where(_active(AgentRole), AgentRole.is_seed == True)  # noqa: E712
        )
        # Prompt：有非空 prompt_template 的专家 + sys_config category=prompt 行
        prompts_expert = await _count(
            select(func.count())
            .select_from(AgentRole)
            .where(_active(AgentRole), func.length(AgentRole.prompt_template) > 0)
        )
        prompts_config = await _count(
            select(func.count())
            .select_from(SysConfig)
            .where(_active(SysConfig), SysConfig.category == CAT_PROMPT)
        )
        # Skill/Tool：静态注册表（无表） + tool_execution 执行留痕行数
        tool_execs = await _count(select(func.count()).select_from(ToolExecution))
        # 工作流
        runs_total = await _count(select(func.count()).select_from(WorkflowRun))
        steps_total = await _count(select(func.count()).select_from(WorkflowStep))

        # 跨界边 1：workflow → agent_role。悬挂 = assignee 指向已不存在的专家。
        assignees = (
            (await db.execute(select(WorkflowRun.assignee_agent_id).distinct()))
            .scalars()
            .all()
        )
        existing_agents = (await db.execute(select(AgentRole.id))).scalars().all()
        dangling_assignees = dangling_refs(assignees, existing_agents)
        # 跨界边 2：step.skill → 能力注册表。
        step_skills = (
            (await db.execute(select(WorkflowStep.skill).distinct())).scalars().all()
        )
        coverage = skill_coverage(step_skills, [d.key for d in CAPABILITY_DEFINITIONS])

    return {
        "experts": {
            "owner": OWNERSHIP["expert"],
            "source": "agent_role (table)",
            "total_active": experts_total,
            "personal_assistants": experts_personal,
            "seed": experts_seed,
        },
        "prompts": {
            "owner": OWNERSHIP["prompt"],
            "source": "agent_role.prompt_template + sys_config[category=prompt]",
            "expert_prompts": prompts_expert,
            "config_prompts": prompts_config,
        },
        "skills_tools": {
            "owner": OWNERSHIP["skill_tool"],
            "source": "CAPABILITY_DEFINITIONS (in-code registry, no table)",
            "registered": len(CAPABILITY_DEFINITIONS),
            "tool_executions": tool_execs,
        },
        "workflows": {
            "owner": OWNERSHIP["workflow"],
            "source": "workflow_run + workflow_step (tables)",
            "runs_total": runs_total,
            "steps_total": steps_total,
        },
        "cross_context_deps": {
            "workflow_to_expert": {
                "edge": "workflow_run.assignee_agent_id -> agent_role.id",
                "dangling_assignee_agent_ids": list(dangling_assignees),
            },
            "step_to_capability": {
                "edge": "workflow_step.skill -> capability_catalog key",
                "defined": list(coverage.defined),
                "referenced": list(coverage.referenced),
                "orphans": list(coverage.orphans),
            },
        },
    }


if __name__ == "__main__":
    import argparse
    import asyncio
    import sys
    from pathlib import Path

    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]  # Windows 控制台

    parser = argparse.ArgumentParser(description="资产迁移盘点（只读 JSON 基线）")
    parser.add_argument("--out", type=str, default="", help="写文件；省略则打 stdout")
    args = parser.parse_args()

    baseline = asyncio.run(_run())
    text = json.dumps(baseline, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"✓ 盘点基线已写入 {args.out}")
    else:
        print(text)
