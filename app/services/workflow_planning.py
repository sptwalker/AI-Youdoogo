"""LLM workflow planning and legacy TaskCard step construction."""

from __future__ import annotations

import json
import logging
import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm import get_llm_for_role
from app.models.task import TaskCard
from app.services import task_service

logger = logging.getLogger(__name__)

AUTO_SKILLS: frozenset[str] = frozenset({"data_query", "deliver"})
MAX_STEPS = 8

PLANNER_SYSTEM = (
    "你是任务编排规划器。判断用户请求是否是「需要多个有序步骤」的复合任务。"
    "只输出 JSON，不要任何解释或代码块标记。\n"
    '格式:{"multi": bool, "steps": [{"no": int, "title": str, "skill": str, '
    '"instruction": str, "depends_on": [int]}]}\n'
    "- multi=false 表示单一动作（普通问答/单步），此时 steps 给空数组。\n"
    "- skill 只能取:data_query(查运营数据)、deliver(生成文件/文档/表格)、"
    "collab(联系其他部门/AI)、notify(通知某真人)、other(其它)。\n"
    "- no 从 0 开始递增;depends_on 填本步依赖的前序步骤 no 列表（无依赖=空数组）。\n"
    "- instruction 用一句话说清这步要做什么。步骤按依赖排序，最多 8 步。\n"
    "示例请求「把昨天运营数据做成日报并通知运营总监」→"
    '{"multi":true,"steps":[{"no":0,"title":"取昨日运营数据","skill":"data_query",'
    '"instruction":"查询昨天各产品运营指标","depends_on":[]},'
    '{"no":1,"title":"生成运营日报","skill":"deliver","instruction":"把数据做成日报文档",'
    '"depends_on":[0]},{"no":2,"title":"通知运营总监","skill":"notify",'
    '"instruction":"把日报通知运营总监","depends_on":[1]}]}'
)


def is_red_line(skill: str) -> bool:
    return skill not in AUTO_SKILLS


@dataclass
class PlanStep:
    no: int
    title: str
    skill: str
    instruction: str
    depends_on: list[int] = field(default_factory=list)


def _strip_fence(raw: str) -> str:
    text = raw.strip()
    match = re.search(r"\{.*\}", text, re.DOTALL)
    return match.group(0) if match else text


def _has_cycle(steps: list[PlanStep]) -> bool:
    by_no = {step.no: step for step in steps}
    color: dict[int, int] = {}

    def visit(no: int) -> bool:
        color[no] = 1
        for dep in by_no[no].depends_on:
            if dep not in by_no:
                continue
            state = color.get(dep, 0)
            if state == 1 or (state == 0 and visit(dep)):
                return True
        color[no] = 2
        return False

    return any(color.get(step.no, 0) == 0 and visit(step.no) for step in steps)


def parse_plan(raw: str) -> list[PlanStep] | None:
    try:
        data = json.loads(_strip_fence(raw))
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(data, dict) or not data.get("multi"):
        return None
    raw_steps = data.get("steps")
    if not isinstance(raw_steps, list) or len(raw_steps) < 2:
        return None
    steps: list[PlanStep] = []
    seen_no: set[int] = set()
    for item in raw_steps[:MAX_STEPS]:
        if not isinstance(item, dict):
            return None
        no = item.get("no")
        title = (item.get("title") or "").strip()
        skill = (item.get("skill") or "other").strip()
        instruction = (item.get("instruction") or title).strip()
        deps = item.get("depends_on") or []
        if not isinstance(no, int) or no in seen_no or not title:
            return None
        if not isinstance(deps, list) or not all(isinstance(dep, int) for dep in deps):
            return None
        seen_no.add(no)
        steps.append(PlanStep(no, title, skill, instruction, list(deps)))
    valid_nos = {step.no for step in steps}
    if any(dep not in valid_nos for step in steps for dep in step.depends_on):
        return None
    return None if _has_cycle(steps) else steps


async def plan(
    db: AsyncSession,
    request: str,
    *,
    llm_factory: Callable[..., Any] = get_llm_for_role,
) -> list[PlanStep] | None:
    del db
    if not request or not request.strip():
        return None
    try:
        llm = llm_factory("reasoning", temperature=0.0)
        reply = await llm.ainvoke(
            [
                SystemMessage(content=PLANNER_SYSTEM),
                HumanMessage(content=f"用户请求:{request.strip()}"),
            ]
        )
        raw = reply.content if isinstance(reply.content, str) else str(reply.content)
        return parse_plan(raw)
    except Exception:  # noqa: BLE001
        logger.warning("任务编排规划失败，退回单步执行", exc_info=True)
        return None


async def build_steps(
    db: AsyncSession,
    parent_id: uuid.UUID,
    steps: list[PlanStep],
    *,
    creator_id: uuid.UUID,
    assignee_agent_id: uuid.UUID | None = None,
) -> list[TaskCard]:
    no_to_id: dict[int, uuid.UUID] = {}
    no_to_card: dict[int, TaskCard] = {}
    for step in sorted(steps, key=lambda item: item.no):
        card = await task_service.create_task(
            db,
            title=step.title,
            task_type=step.skill,
            creator_id=creator_id,
            assignee_agent_id=assignee_agent_id,
            parent_id=parent_id,
            step_no=step.no,
            payload={
                "instruction": step.instruction,
                "skill": step.skill,
                "red_line": is_red_line(step.skill),
            },
        )
        no_to_id[step.no] = card.id
        no_to_card[step.no] = card
    for step in steps:
        no_to_card[step.no].depends_on = [str(no_to_id[dep]) for dep in step.depends_on]
    await db.commit()
    cards = [no_to_card[step.no] for step in sorted(steps, key=lambda item: item.no)]
    for card in cards:
        await db.refresh(card)
    return cards
