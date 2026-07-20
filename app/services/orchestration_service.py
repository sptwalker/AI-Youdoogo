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
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import run_agent
from app.llm import get_llm_for_role
from app.models.agent import AgentRole
from app.models.task import TaskCard
from app.services import task_flow, task_service
from app.services.collab_protocol import ProtocolResult

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


# ── B.2 调度驱动（拓扑推进 + 产出喂下游 + 红线停点 + 父卡聚合）───────────────

_PREVIEW_ROWS = 30  # 喂下游步骤时单数据集渲染的最大行数（控 prompt 体积）


async def _step_cards(db: AsyncSession, parent_id: uuid.UUID) -> list[TaskCard]:
    """取某编排父卡下的全部步骤卡（按 step_no 升序）。"""
    steps = await task_service.list_tasks(db, parent_id=parent_id, limit=_MAX_STEPS + 2)
    return sorted(steps, key=lambda s: (s.step_no if s.step_no is not None else 0))


def _ready_steps(steps: list[TaskCard]) -> list[TaskCard]:
    """可执行步骤:自身待执行（created/dispatched）且所有依赖已 accepted。"""
    done = {str(s.id) for s in steps if s.status == task_flow.ACCEPTED}
    ready = []
    for s in steps:
        if s.status not in (task_flow.CREATED, task_flow.DISPATCHED):
            continue
        if all(d in done for d in (s.depends_on or [])):
            ready.append(s)
    return ready


def _render_dataset(ds: dict[str, Any]) -> str:
    """把上游取数产出渲染成紧凑表格文本（喂下游步骤）。"""
    cols = ds.get("columns") or []
    rows = ds.get("rows") or []
    if not rows:
        return f"（查询 {ds.get('sql', '')[:40]} 无数据）"
    head = "| " + " | ".join(str(c) for c in cols) + " |"
    sep = "| " + " | ".join("---" for _ in cols) + " |"
    body = ["| " + " | ".join(str(r.get(c, "")) for c in cols) + " |" for r in rows[:_PREVIEW_ROWS]]
    return "\n".join([head, sep, *body])


def _step_message(step: TaskCard) -> str:
    """把步骤卡（含上游注入的 step_input）渲染成给智能体的输入消息。"""
    payload = step.payload or {}
    parts = [f"任务：{step.title}", f"要求：{payload.get('instruction', step.title)}"]
    si = step.step_input or {}
    datasets = si.get("datasets") or []
    if datasets:
        parts.append("\n上游步骤已取得以下真实数据，请据此完成本步（勿另行编造）：")
        parts.extend(_render_dataset(d) for d in datasets)
    artifacts = si.get("artifacts") or []
    if artifacts:
        names = "、".join(a.get("file_name", "") for a in artifacts)
        parts.append(f"\n上游已产出文件：{names}")
    parts.append("\n请完成本步骤。需要数据用【取数】指令，需生成文件用【交付】指令。")
    return "\n".join(parts)


async def _run_step(
    db: AsyncSession, step: TaskCard, operator_id: uuid.UUID | None
) -> ProtocolResult | None:
    """驱动单个步骤卡执行到 reported，返回其技能产出（datasets/artifacts）。

    失败（无执行者/执行异常）→ 推到 reported 记错、返回 None（不 accept，天然阻断下游、留痕）。
    """
    from app.agents import skills

    role = await db.get(AgentRole, step.assignee_agent_id) if step.assignee_agent_id else None
    if role is None or not role.is_active:
        await _to_reported(db, step, operator_id, "步骤无可用执行者", None)
        return None
    # created → dispatched → executing
    if step.status == task_flow.CREATED:
        await task_service.transition(
            db, step.id, task_flow.DISPATCHED, operator_id=operator_id, note="编排分发"
        )
    await task_service.transition(
        db, step.id, task_flow.EXECUTING, operator_id=operator_id, note="编排执行"
    )
    record = await run_agent(
        db, role, task_type=step.task_type,
        input_summary=f"编排步骤：{step.title[:40]}",
        user_message=_step_message(step), user_id=operator_id, use_knowledge=True,
    )
    result = record.output_content or record.error_msg or "（无产出）"
    proto = await skills.execute_all(
        db, role, result, user_id=operator_id,
        user_intent=(step.payload or {}).get("instruction"),
    )
    for consulted, rec in proto.consult_replies:
        result += f"\n\n---\n【{consulted.name} 答复】\n{rec.output_content or rec.error_msg or ''}"
    result = skills.fold_notes(result, proto)
    await _to_reported(db, step, role.id, f"执行 status={record.status}", result)
    return None if record.status == "failed" else proto


async def _to_reported(
    db: AsyncSession, step: TaskCard, operator_id: uuid.UUID | None,
    note: str, result: str | None,
) -> None:
    """把步骤推到 reported（容忍已 executing/dispatched 的中间态）。"""
    if step.status in (task_flow.EXECUTING,):
        await task_service.transition(
            db, step.id, task_flow.REPORTED, operator_id=operator_id,
            note=note, result_content=result,
        )
        return
    # 未进入 executing（如无执行者早退）：补齐流转到 reported，保证有终态可验收
    for nxt in (task_flow.DISPATCHED, task_flow.EXECUTING, task_flow.REPORTED):
        if task_flow.can_transition(step.status, nxt):
            await task_service.transition(
                db, step.id, nxt, operator_id=operator_id,
                note=note, result_content=result if nxt == task_flow.REPORTED else None,
            )


async def _pipe_outputs(
    db: AsyncSession, step: TaskCard, proto: ProtocolResult, all_steps: list[TaskCard]
) -> None:
    """把步骤产出（datasets/artifacts）注入直接下游步骤的 step_input。"""
    if not (proto.datasets or proto.artifacts):
        return
    sid = str(step.id)
    for ds in all_steps:
        if sid not in (ds.depends_on or []):
            continue
        si = dict(ds.step_input or {})
        si["datasets"] = (si.get("datasets") or []) + proto.datasets
        si["artifacts"] = (si.get("artifacts") or []) + proto.artifacts
        ds.step_input = si  # 重新赋值触发 JSONB 变更追踪
    await db.commit()


async def advance(
    db: AsyncSession, parent_id: uuid.UUID, *, operator_id: uuid.UUID | None
) -> dict[str, Any]:
    """拓扑推进编排:反复执行「依赖已完成」的步骤。

    - 非红线步骤:执行到 reported → 自动验收（accepted）→ 产出喂下游。
    - 红线步骤:执行到 reported 后**停下等真人 accept**，绝不自动跨越。
    - 失败步骤:停在 reported 不验收，天然阻断下游、留痕，不连累其余分支。
    真人验收某红线步后再次调用本函数即从停点继续（resume）。
    """
    await _kickoff_parent(db, parent_id, operator_id)
    while True:
        steps = await _step_cards(db, parent_id)
        ready = _ready_steps(steps)
        if not ready:
            break
        progressed = False
        for s in ready:
            proto = await _run_step(db, s, operator_id)
            if proto is None:
                continue  # 失败：留在 reported 阻断下游
            if (s.payload or {}).get("red_line"):
                continue  # 红线：停在 reported 等真人 accept
            await task_service.transition(
                db, s.id, task_flow.ACCEPTED, operator_id=operator_id,
                note="非红线步骤自动验收",
            )
            await _pipe_outputs(db, s, proto, steps)
            progressed = True
        if not progressed:
            break  # 剩余可执行步骤均为红线/失败（已停在 reported），等真人
    return await progress(db, parent_id)


async def _kickoff_parent(
    db: AsyncSession, parent_id: uuid.UUID, operator_id: uuid.UUID | None
) -> None:
    """首次推进时把父编排卡推到 executing（created→dispatched→executing）。"""
    parent = await task_service.get_task(db, parent_id)
    if parent.status == task_flow.CREATED:
        await task_service.transition(
            db, parent_id, task_flow.DISPATCHED, operator_id=operator_id, note="编排启动"
        )
        await task_service.transition(
            db, parent_id, task_flow.EXECUTING, operator_id=operator_id, note="编排执行中"
        )


_MIN_REQUEST_LEN = 8  # 短消息（问候等）不进规划，省一次 LLM 调用


async def start(
    db: AsyncSession,
    request: str,
    *,
    creator_id: uuid.UUID,
    assignee_agent_id: uuid.UUID | None,
    operator_id: uuid.UUID | None,
    title: str | None = None,
) -> dict[str, Any] | None:
    """复合任务入口:规划 → 建父编排卡 + DAG 步骤卡 → 拓扑推进到红线停点。

    返回进度快照;若非复合任务（plan 返回 None）→ 返回 None，调用方走原路（普通单步）。
    永不 raise（规划/建卡故障退回 None）。
    """
    if not request or len(request.strip()) < _MIN_REQUEST_LEN:
        return None
    try:
        steps = await plan(db, request)
        if steps is None:
            return None
        parent = await task_service.create_task(
            db, title=(title or request.strip())[:200], task_type="orchestration",
            creator_id=creator_id, assignee_agent_id=assignee_agent_id,
            payload={"origin": "orchestration", "request": request.strip()},
        )
        await build_steps(
            db, parent.id, steps, creator_id=creator_id, assignee_agent_id=assignee_agent_id
        )
        return await advance(db, parent.id, operator_id=operator_id)
    except Exception:  # noqa: BLE001 - 编排启动故障不阻断，退回普通对话
        logger.warning("任务编排启动失败，退回普通处理", exc_info=True)
        return None


async def resume_if_step(
    db: AsyncSession, task: TaskCard, *, operator_id: uuid.UUID | None
) -> dict[str, Any] | None:
    """真人验收某卡后:若它是编排步骤卡，从停点继续推进父编排。否则 None。"""
    if task.step_no is None or task.parent_id is None:
        return None
    return await advance(db, task.parent_id, operator_id=operator_id)


async def progress(db: AsyncSession, parent_id: uuid.UUID) -> dict[str, Any]:
    """编排进度快照:父卡状态 + 各步骤状态/红线标记（供前端进度卡渲染）。"""
    steps = await _step_cards(db, parent_id)
    total = len(steps)
    accepted = sum(1 for s in steps if s.status == task_flow.ACCEPTED)
    waiting = [s for s in steps if s.status == task_flow.REPORTED]
    return {
        "parent_id": str(parent_id),
        "total": total,
        "accepted": accepted,
        "awaiting_human": [str(s.id) for s in waiting if (s.payload or {}).get("red_line")],
        "done": accepted == total and total > 0,
        "steps": [
            {
                "id": str(s.id), "step_no": s.step_no, "title": s.title,
                "skill": s.task_type, "status": s.status,
                "red_line": bool((s.payload or {}).get("red_line")),
            }
            for s in steps
        ],
    }


# ── 崩溃恢复扫描（H4.1，docs/16）─────────────────────────

async def recover_incomplete(db: AsyncSession) -> dict[str, int]:
    """启动时崩溃恢复:复位孤儿步骤 + 重新推进未完成的编排。永不 raise。

    进程崩在某步 LLM 调用中途 → 那步卡在 executing/dispatched（无人复位），
    且没人重新触发 advance。本函数扫出仍 executing 的编排父卡:
    1. 把其下卡在 executing/dispatched 的孤儿步骤复位到 created（可重跑;取数只读、
       交付幂等，重跑安全）。已 reported（含红线等真人）的步骤不动。
    2. 对每个父卡重新 advance，推进依赖已满足的步骤。
    不上工作流引擎——DAG 本就持久在 task_card，只补"崩溃复位 + 重启续跑"这一环。

    返回 {orchestrations, steps_reset}。任何单卡故障隔离，不连累其余。
    """
    from sqlalchemy import select

    result = {"orchestrations": 0, "steps_reset": 0}
    try:
        stmt = select(TaskCard).where(
            TaskCard.task_type == "orchestration",
            TaskCard.status == task_flow.EXECUTING,
            TaskCard.is_delete.is_(False),
        )
        parents = list((await db.execute(stmt)).scalars())
    except Exception:  # noqa: BLE001 - 恢复扫描不阻断启动
        logger.warning("崩溃恢复扫描查询失败", exc_info=True)
        return result

    for parent in parents:
        try:
            steps = await _step_cards(db, parent.id)
            reset = 0
            for s in steps:
                if s.status in (task_flow.EXECUTING, task_flow.DISPATCHED):
                    # 崩溃复位:直接改 status（绕状态机，孤儿态无干净迁移路径）
                    s.status = task_flow.CREATED
                    reset += 1
            if reset:
                await db.commit()
                result["steps_reset"] += reset
            await advance(db, parent.id, operator_id=None)  # 重启续跑
            result["orchestrations"] += 1
        except Exception:  # noqa: BLE001 - 单编排恢复失败不连累其余
            logger.warning("编排 %s 崩溃恢复失败", parent.id, exc_info=True)
    if result["orchestrations"]:
        logger.info(
            "崩溃恢复:续跑 %d 个编排，复位 %d 个孤儿步骤",
            result["orchestrations"], result["steps_reset"],
        )
    return result
