"""只读取数服务:AI/客户端的 SQL → 护栏校验 → 执行 → 截断 → 审计。

内部 agent(阶段3)与 MCP tool(阶段4)都调 run_readonly_sql——一套逻辑两处用。
护栏(sql_guard)硬保证仅 SELECT + 白名单视图 + 强制 LIMIT;结果行/列再封顶防拖爆;每次落审计。
返回结构化 dict(不 raise 常规拒绝/失败)——供 agent/客户端回读并自我纠正。
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.integration.governed_data_query import SqlRejected, check_sql
from app.services import audit_service, data_catalog_service, ops_data

logger = logging.getLogger(__name__)

_MAX_ROWS = 1000  # 结果行上限(与 LIMIT 上限一致)
_MAX_COLS = 50  # 结果列上限
_MAX_TIMEOUT = 60  # TD 查询超时上限(秒)


async def run_readonly_sql(
    db: AsyncSession,
    sql: str,
    *,
    actor_id: uuid.UUID | None,
    actor_role: str | None,
    source: str = "agent",
) -> dict[str, Any]:
    """校验并执行只读 SQL。永不 raise:拒绝/失败均转结构化返回。

    Returns:
        {status: ok|rejected|fail, ...}
        - ok:  columns / rows(截断) / row_count / truncated
        - rejected: reason(护栏未过)
        - fail: msg(TD 报错 / 配置缺失)
    """
    from app.integrations.thinkingdata.client import ThinkingDataClient, ThinkingDataError

    # 1. 护栏
    try:
        allow = await data_catalog_service.allowed_views(db)
        safe_sql = check_sql(sql, allowed_views=allow, max_limit=_MAX_ROWS)
    except SqlRejected as exc:
        await _audit(db, actor_id, actor_role, sql, source, result="rejected",
                     extra={"reason": str(exc)})
        return {"status": "rejected", "reason": str(exc)}

    # 2. 配置 + 执行
    cfg = await ops_data._resolve_td_config(db)
    if not cfg["base_url"] or not cfg["api_secret"]:
        return {"status": "fail", "msg": "未配置 TD 地址/密钥"}
    client = ThinkingDataClient(base_url=cfg["base_url"], api_secret=cfg["api_secret"])
    try:
        rows = await client.query_sql(safe_sql, timeout_seconds=_MAX_TIMEOUT)
    except ThinkingDataError as exc:
        await _audit(db, actor_id, actor_role, safe_sql, source, result="fail",
                     extra={"msg": str(exc)[:200]})
        return {"status": "fail", "msg": str(exc)[:200]}
    finally:
        await client.close()

    # 3. 截断(行/列封顶)
    truncated = len(rows) > _MAX_ROWS
    rows = rows[:_MAX_ROWS]
    columns = list(rows[0].keys())[:_MAX_COLS] if rows and isinstance(rows[0], dict) else []
    if columns:
        rows = [{c: r.get(c) for c in columns} for r in rows]

    await _audit(db, actor_id, actor_role, safe_sql, source, result="ok",
                 extra={"row_count": len(rows)})
    return {
        "status": "ok", "columns": columns, "rows": rows,
        "row_count": len(rows), "truncated": truncated,
    }


async def _audit(
    db: AsyncSession, actor_id: uuid.UUID | None, actor_role: str | None,
    sql: str, source: str, *, result: str, extra: dict[str, Any],
) -> None:
    """落一条取数审计(sql 不含密钥;detail 经 audit _mask 兜底)。"""
    await audit_service.audit(
        db, actor_id=actor_id, actor_role=actor_role, action="data.query",
        summary=f"取数[{source}/{result}]:{sql[:60]}", target_type="data_source",
        detail={"sql": sql[:2000], "source": source, **extra}, result=result,
    )
