"""任务编排层（docs/14 §4.2 阶段B）:复合任务 → LLM 规划 DAG → 建步骤卡。

阶段B 拆两块:本模块 B.1 是「规划地基」——
1. classify/is_red_line：技能白名单判定红线步骤（取数/交付=非红线可自动；其余=红线停点）。
2. parse_plan：纯函数，把 LLM 规划产出（JSON）解析成校验过的 DAG 步骤（含无环校验）。
3. plan：一次 LLM 调用识别是否多动作 + 出 DAG；单动作/失败 → 返回 None（调用方走原路）。
4. build_steps：按 DAG 建带 step_no/depends_on 的子任务卡（复用 task_service）。
拓扑驱动/红线停点/产出喂下游在 B.2（scheduler）。

红线：编排只排序+串接，不新增生效权;红线步骤仍停在真人验收，绝不自动跨越。
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from dataclasses import dataclass, field

from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm import get_llm_for_role
from app.models.task import TaskCard
from app.services import task_service

logger = logging.getLogger(__name__)

# 非红线技能白名单：只读取数 + 文件交付可自动推进；白名单外一律红线停点（安全默认）。
_AUTO_SKILLS: frozenset[str] = frozenset({"data_query", "deliver"})
_MAX_STEPS = 8  # 单次编排步骤上限（防失控规划）

_PLANNER_SYSTEM = (
    "你是任务编排规划器。判断用户请求是否是「需要多个有序步骤」的复合任务。"
    "只输出 JSON，不要任何解释或代码块标记。\n"
    "格式:{\"multi\": bool, \"steps\": [{\"no\": int, \"title\": str, \"skill\": str, "
    "\"instruction\": str, \"depends_on\": [int]}]}\n"
    "- multi=false 表示单一动作（普通问答/单步），此时 steps 给空数组。\n"
    "- skill 只能取:data_query(查运营数据)、deliver(生成文件/文档/表格)、"
    "collab(联系其他部门/AI)、notify(通知某真人)、other(其它)。\n"
    "- no 从 0 开始递增;depends_on 填本步依赖的前序步骤 no 列表（无依赖=空数组）。\n"
    "- instruction 用一句话说清这步要做什么。步骤按依赖排序，最多 8 步。\n"
    "示例请求「把昨天运营数据做成日报并通知运营总监」→"
    "{\"multi\":true,\"steps\":[{\"no\":0,\"title\":\"取昨日运营数据\",\"skill\":\"data_query\","
    "\"instruction\":\"查询昨天各产品运营指标\",\"depends_on\":[]},"
    "{\"no\":1,\"title\":\"生成运营日报\",\"skill\":\"deliver\",\"instruction\":\"把数据做成日报文档\","
    "\"depends_on\":[0]},{\"no\":2,\"title\":\"通知运营总监\",\"skill\":\"notify\","
    "\"instruction\":\"把日报通知运营总监\",\"depends_on\":[1]}]}"
)


def is_red_line(skill: str) -> bool:
    """该技能步骤是否红线（推到 reported 后停下等真人验收）。白名单外一律红线（安全默认）。"""
    return skill not in _AUTO_SKILLS


@dataclass
class PlanStep:
    """规划出的一个 DAG 步骤（no 为规划内序号，build 时映射为卡 id）。"""

    no: int
    title: str
    skill: str
    instruction: str
    depends_on: list[int] = field(default_factory=list)


def _strip_fence(raw: str) -> str:
    """去掉 LLM 可能包裹的 ```json ``` 代码块围栏，取出 JSON 主体。"""
    s = raw.strip()
    m = re.search(r"\{.*\}", s, re.DOTALL)
    return m.group(0) if m else s


def _has_cycle(steps: list[PlanStep]) -> bool:
    """DAG 无环校验（DFS 三色）。有环返回 True。"""
    by_no = {s.no: s for s in steps}
    color: dict[int, int] = {}  # 0=未访问 1=在栈 2=完成

    def visit(no: int) -> bool:
        color[no] = 1
        for dep in by_no[no].depends_on:
            if dep not in by_no:
                continue
            c = color.get(dep, 0)
            if c == 1:
                return True  # 回边=环
            if c == 0 and visit(dep):
                return True
        color[no] = 2
        return False

    return any(color.get(s.no, 0) == 0 and visit(s.no) for s in steps)


def parse_plan(raw: str) -> list[PlanStep] | None:
    """纯函数:把规划器 JSON 产出解析成校验过的 DAG 步骤。

    返回 None 表示「不编排」（单动作 / multi=false / 步骤<2 / 解析失败 / 非法 DAG）——
    调用方据此走原路（普通单步执行）。校验:no 唯一、depends_on 引用已存在的 no、无环、限量。
    """
    try:
        data = json.loads(_strip_fence(raw))
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(data, dict) or not data.get("multi"):
        return None
    raw_steps = data.get("steps")
    if not isinstance(raw_steps, list) or len(raw_steps) < 2:
        return None  # 少于 2 步不构成编排
    steps: list[PlanStep] = []
    seen_no: set[int] = set()
    for it in raw_steps[:_MAX_STEPS]:
        if not isinstance(it, dict):
            return None
        no = it.get("no")
        title = (it.get("title") or "").strip()
        skill = (it.get("skill") or "other").strip()
        instruction = (it.get("instruction") or title).strip()
        deps = it.get("depends_on") or []
        if not isinstance(no, int) or no in seen_no or not title:
            return None
        if not isinstance(deps, list) or not all(isinstance(d, int) for d in deps):
            return None
        seen_no.add(no)
        steps.append(PlanStep(no=no, title=title, skill=skill,
                              instruction=instruction, depends_on=list(deps)))
    # depends_on 必须引用已存在的 no，且整体无环
    valid_nos = {s.no for s in steps}
    for s in steps:
        if any(d not in valid_nos for d in s.depends_on):
            return None
    if _has_cycle(steps):
        return None
    return steps


async def plan(db: AsyncSession, request: str) -> list[PlanStep] | None:
    """一次 LLM 规划调用:识别是否多动作 + 出 DAG。单动作/任何失败 → None（走原路）。永不 raise。"""
    if not request or not request.strip():
        return None
    try:
        llm = get_llm_for_role("reasoning", temperature=0.0)
        reply = await llm.ainvoke([
            SystemMessage(content=_PLANNER_SYSTEM),
            HumanMessage(content=f"用户请求:{request.strip()}"),
        ])
        raw = reply.content if isinstance(reply.content, str) else str(reply.content)
        return parse_plan(raw)
    except Exception:  # noqa: BLE001 - 规划故障不阻断，退回单步原路
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
    """按 DAG 建带 step_no/depends_on 的子任务卡。规划内 no → 卡 id 映射后写入 depends_on。"""
    no_to_id: dict[int, uuid.UUID] = {}
    no_to_card: dict[int, TaskCard] = {}
    # 先按 no 升序建卡，记录 no→id / no→card 映射
    for st in sorted(steps, key=lambda s: s.no):
        card = await task_service.create_task(
            db, title=st.title, task_type=st.skill, creator_id=creator_id,
            assignee_agent_id=assignee_agent_id, parent_id=parent_id,
            step_no=st.no,
            payload={"instruction": st.instruction, "skill": st.skill,
                     "red_line": is_red_line(st.skill)},
        )
        no_to_id[st.no] = card.id
        no_to_card[st.no] = card
    # 回填 depends_on（此时所有 no→id 已知，支持依赖任意 no）
    for st in steps:
        no_to_card[st.no].depends_on = [
            str(no_to_id[d]) for d in st.depends_on if d in no_to_id
        ]
    await db.commit()
    cards = [no_to_card[st.no] for st in sorted(steps, key=lambda s: s.no)]
    for c in cards:
        await db.refresh(c)
    return cards
