"""取数技能(阶段3):AI 回复中的【取数】指令 → 只读 SQL 护栏 → 执行 → 结果折进消息。

指令(写进提示词【可查数据】段，模型据此产出，编排层代为执行):
    【取数】<一句只读 SELECT SQL>

- 复用 data_query_service.run_readonly_sql:护栏(仅SELECT+白名单视图+强制LIMIT)+ 执行 + 审计。
- 每回复最多 2 次取数;结果渲染成紧凑表格文本，作为 note 折进 AI 消息(fold_notes)。
- 提示词段用 data_catalog_service.catalog_prompt(AI 知道有哪些视图/事件可查)。
红线:只读分析权;拿到数据可分析/写日报，但任何决议仍走真人确认。
"""

from __future__ import annotations

import logging
import re
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import run_agent
from app.models.agent import AgentRole
from app.services import config_service, data_query_service
from app.services.collab_protocol import ProtocolResult

logger = logging.getLogger(__name__)

_MAX_QUERIES = 2  # 每回复最多取数次数（防刷屏/失控）
_MAX_PREVIEW_ROWS = 50  # 回喂给 AI 的最大行数（控 prompt 体积）

# 【取数】后跟一句 SQL，取到行尾（分号由护栏拒多语句，这里只截首行）
_QUERY_RE = re.compile(r"【取数】\s*([^\n]+)")


def parse(output: str) -> list[str]:
    """解析产出中的取数指令（纯函数）。返回 SQL 列表，截断到上限。"""
    sqls = [m.strip() for m in _QUERY_RE.findall(output or "") if m.strip()]
    return sqls[:_MAX_QUERIES]


def _table(res: dict[str, Any]) -> str:
    """把一条取数结果渲染成 Markdown 表格（供回喂 AI）。"""
    rows = res.get("rows") or []
    cols = res.get("columns") or []
    if not rows:
        return "（0 行）"
    head = "| " + " | ".join(cols) + " |"
    sep = "| " + " | ".join("---" for _ in cols) + " |"
    body = [
        "| " + " | ".join(str(r.get(c, "")) for c in cols) + " |"
        for r in rows[:_MAX_PREVIEW_ROWS]
    ]
    tail = f"\n（共 {res['row_count']} 行" + ("，已截断" if res.get("truncated") else "") + "）"
    return "\n".join([head, sep, *body]) + tail


async def _enabled(db: AsyncSession) -> bool:
    flag = await config_service.resolve(db, "agent_data_query", True)
    return str(flag).lower() not in ("false", "0")


async def execute(
    db: AsyncSession, initiator: AgentRole, output: str,
    *, user_id: uuid.UUID | None = None, user_intent: str | None = None,
    exclude: set[str] | None = None,
) -> ProtocolResult:
    """解析并执行取数指令 → 把数据回喂 AI 生成自然语言解读，作为追加消息。永不 raise。

    闭环:AI 产出【取数】SQL → 护栏执行 → 数据回喂同一 AI 再生成一轮（解读+格式化表格
    +可写【交付】/【协作】）→ 解读放进 consult_replies，由调用方渲染为追加消息;
    解读轮里的交付/协作指令由 _interpret 代为执行（阶段A 闭环,docs/14 §4.1）。
    失败/被拒的查询转 note 折进原消息（不回喂，直接告知）。

    - datasets:每条成功取数的结构化产出（sql/columns/rows/row_count）进 result.datasets，
      作为"下一步输入"面向编排层（阶段B 拓扑传递用）。
    - user_intent:调用方透传的用户原始诉求（如"要日报文档"），让解读轮 AI 知道除解读外
      还要交付,而不仅口头解读。
    - exclude:解读轮回跑 execute_all 时要额外屏蔽的技能（并上 data_query 防递归）。被咨询
      AI 取数时传 {"collab"}，避免咨询链在解读里再生二次咨询（保持深度硬限）。
    """
    result = ProtocolResult()
    try:
        sqls = parse(output)
        if not sqls:
            return result  # 零指令快速路径
        if not await _enabled(db):
            return result

        blocks: list[str] = []  # 成功查询的「SQL + 表格」，回喂给 AI
        for sql in sqls:
            try:
                res = await data_query_service.run_readonly_sql(
                    db, sql, actor_id=user_id, actor_role=None,
                    source=f"agent:{initiator.name}",
                )
            except Exception:  # noqa: BLE001 - 单条取数失败不连累其余
                logger.warning("取数执行失败 sql=%s", sql[:80], exc_info=True)
                result.notes.append(f"取数执行异常，已忽略:{sql[:80]}")
                continue
            status = res.get("status")
            if status == "rejected":
                result.notes.append(f"取数被拒（{res.get('reason', '')}）:{sql[:80]}")
            elif status == "fail":
                result.notes.append(f"取数失败（{res.get('msg', '')}）:{sql[:80]}")
            else:
                blocks.append(f"查询:{sql}\n结果:\n{_table(res)}")
                # 结构化载荷（阶段A 产出管道）:面向下一步输入，非仅显示
                result.datasets.append(
                    {
                        "sql": sql, "columns": res.get("columns") or [],
                        "rows": res.get("rows") or [], "row_count": res.get("row_count", 0),
                        "truncated": bool(res.get("truncated")),
                    }
                )

        if blocks:
            await _interpret(db, initiator, output, blocks, user_id, result, user_intent, exclude)
    except Exception:  # noqa: BLE001 - 取数层故障不连累业务消息流
        logger.warning("取数协议处理失败", exc_info=True)
    return result


async def _interpret(
    db: AsyncSession, initiator: AgentRole, original: str, blocks: list[str],
    user_id: uuid.UUID | None, result: ProtocolResult, user_intent: str | None = None,
    exclude: set[str] | None = None,
) -> None:
    """把取数结果回喂 AI，生成自然语言解读+格式化表格，作为追加消息。

    深度硬限:对解读产出**只放行非取数技能**（交付/协作），仍禁【取数】防递归——这样
    "取数→拿真实数据→同轮交付日报"一句话打通（阶段A 修 bug,docs/14 §4.1）。
    exclude 并上 data_query 传给回跑的 execute_all：被咨询链上取数时含 collab，避免二次咨询。
    """
    data_text = "\n\n".join(blocks)
    intent_line = (
        f"用户的原始诉求是:「{user_intent.strip()}」。请据此判断除解读外是否还需交付文档"
        "（若用户要日报/表格/文件，请用【交付】指令生成对应文件）。\n"
        if user_intent and user_intent.strip()
        else ""
    )
    prompt = (
        f"你之前的回复中发起了数据查询，系统已执行并返回真实结果如下:\n\n{data_text}\n\n"
        f"{intent_line}"
        "请基于以上真实数据，面向提问者给出简明的运营解读:先用 1~3 句话说明关键结论"
        "（如整体量级、亮点或异常），再用一个清晰的 Markdown 表格呈现核心指标。"
        "只依据上面的数据，不要编造未查询的数字;不要再写【取数】指令"
        "（数据已就绪，无需再查）。"
    )
    record = await run_agent(
        db, initiator, task_type="data_interpret",
        input_summary=f"解读取数结果:{original[:40]}",
        user_message=prompt, user_id=user_id, use_knowledge=False,
    )
    result.consult_replies.append((initiator, record))
    # 解读轮放行交付/协作（禁 data_query 防递归）：解读里写的【交付】在此真正执行，
    # 产出的 notes/artifacts/协作答复并入本结果，交付 note 最终折进原消息。
    interpret_text = record.output_content or ""
    if interpret_text:
        from app.agents import skills

        sub = await skills.execute_all(
            db, initiator, interpret_text, user_id=user_id,
            exclude=(exclude or set()) | {"data_query"},
        )
        result.notes.extend(sub.notes)
        result.consult_replies.extend(sub.consult_replies)
        result.datasets.extend(sub.datasets)
        result.artifacts.extend(sub.artifacts)



async def prompt_section(db: AsyncSession) -> str:
    """取数技能的提示词段 = 数据目录 + 指令说明。无可查数据返回空串。"""
    from app.services import data_catalog_service

    catalog = await data_catalog_service.catalog_prompt(db)
    if not catalog:
        return ""
    return (
        catalog
        + "\n取数指令:需要数据时，单独一行写 【取数】<你的只读 SELECT 语句>，"
        "系统会自动校验执行并把结果表格加入对话。每次回复最多 2 次;"
        "只能 SELECT 上表列出的视图，系统会自动限制返回行数。"
    )
