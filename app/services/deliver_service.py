"""文件交付技能（docs/13 §11）：AI 回复中的【交付】指令 → 生成文件落 MinIO → 交付到桌面。

指令（写进全局提示词【文件交付】段，模型据此产出，编排层代为执行）：
    【交付】名称：<文件名>；格式：<csv|xlsx|md|txt>
    ```
    <payload：csv/xlsx 放 markdown 表格；md/txt 放正文>
    ```

- 表格类（csv/xlsx）：把 fenced 块里的 markdown 表解析成行 → 写 CSV/XLSX 字节。
- 文档类（md/txt）：payload 原样落文件。
- 每回复最多 2 个交付；单条失败转 note 不 raise（复刻 collab_protocol 容错）。
- user_id 为空（自动任务无接收人）→ 跳过并出 note：交付必须有归属真人桌面。

红线：交付物只是文件，下载即用，不触发任何业务决议；取数仍走 collab 咨询/复核。
"""

from __future__ import annotations

import csv
import io
import logging
import re
import uuid

from openpyxl import Workbook
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.knowledge import storage
from app.models.agent import AgentRole
from app.models.deliverable import Deliverable
from app.services import config_service
from app.services.collab_protocol import ProtocolResult

logger = logging.getLogger(__name__)

_MAX_DELIVERIES = 2  # 每回复最多交付数（防刷屏/失控）
_VALID_FORMATS = ("csv", "xlsx", "md", "txt")

# 【交付】名称：X；格式：Y  换行  ```(可选语言) 正文 ```  —— DOTALL 让正文跨行非贪婪
_DELIVER_RE = re.compile(
    r"【交付】\s*名称[：:]\s*([^；;\n]+?)\s*[；;]\s*格式[：:]\s*(csv|xlsx|md|txt)\s*\n+"
    r"```[^\n]*\n(.*?)\n?```",
    re.DOTALL,
)

_CONTENT_TYPE = {
    "csv": "text/csv; charset=utf-8",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "md": "text/markdown; charset=utf-8",
    "txt": "text/plain; charset=utf-8",
}

PROMPT_SECTION = (
    "\n\n【文件交付】（系统内建，已启用）当用户要你产出可下载的表格或文档时，"
    "在回复中单独写一段交付指令，系统会自动生成文件并放入用户工作桌面的「文件交付区」：\n"
    "格式：先写一行 【交付】名称：<文件名>；格式：<csv|xlsx|md|txt>，"
    "紧接一个 ``` 代码块作为内容。\n"
    "- 表格（csv/xlsx）：代码块里放标准 Markdown 表格（首行表头，第二行 --- 分隔）。\n"
    "- 文档（md/txt）：代码块里放正文。\n"
    "每次回复最多交付 2 个文件。示例：\n"
    "【交付】名称：销售周报；格式：xlsx\n```\n| 日期 | 产品 | 销量 |\n| --- | --- | --- |\n"
    "| 2026-07-14 | A | 120 |\n```\n"
    "需要别的同事的数据时，先用【咨询 @AI名】取数，拿到后再在同一或下一轮回复里交付。"
)


def parse(output: str) -> list[tuple[str, str, str]]:
    """解析产出中的交付指令（纯函数）。返回 (名称, 格式, payload)，截断到上限。"""
    items = [
        (name.strip(), fmt.strip().lower(), body)
        for name, fmt, body in _DELIVER_RE.findall(output or "")
        if name.strip() and fmt.strip().lower() in _VALID_FORMATS and body.strip()
    ]
    return items[:_MAX_DELIVERIES]


def _markdown_table_to_rows(body: str) -> list[list[str]]:
    """Markdown 表 → 行列表。丢弃 |---| 分隔行；容忍首尾竖线与内外空白。"""
    rows: list[list[str]] = []
    for line in body.splitlines():
        line = line.strip()
        if not line or "|" not in line:
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if all(set(c) <= {"-", ":", " "} and c for c in cells):
            continue  # 分隔行 |---|:--:|
        rows.append(cells)
    return rows


def _build_bytes(fmt: str, body: str) -> bytes:
    """按格式生成文件字节。csv/xlsx 走 markdown 表解析；md/txt 原样。"""
    if fmt in ("md", "txt"):
        return body.strip().encode("utf-8")
    rows = _markdown_table_to_rows(body)
    if not rows:
        raise ValueError("交付内容不含可解析的表格")
    if fmt == "csv":
        buf = io.StringIO()
        csv.writer(buf).writerows(rows)
        return buf.getvalue().encode("utf-8-sig")  # BOM 让 Excel 正确识别 UTF-8
    wb = Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def _safe_name(name: str, fmt: str) -> str:
    """清洗文件名并补正确扩展名（去路径分隔符，限长）。"""
    base = re.sub(r"[/\\:*?\"<>|]", "_", name).strip()[:120] or "交付物"
    suffix = f".{fmt}"
    return base if base.lower().endswith(suffix) else base + suffix


async def _enabled(db: AsyncSession) -> bool:
    flag = await config_service.resolve(db, "agent_deliver", True)
    return str(flag).lower() not in ("false", "0")


async def _deliver_one(
    db: AsyncSession, initiator: AgentRole, user_id: uuid.UUID,
    name: str, fmt: str, body: str, result: ProtocolResult,
) -> None:
    data = _build_bytes(fmt, body)
    file_name = _safe_name(name, fmt)
    row = Deliverable(
        owner_user_id=user_id, agent_id=initiator.id, agent_name=initiator.name,
        file_name=file_name, file_format=fmt, storage_path="", file_size=len(data),
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    row.storage_path = await storage.put_object(
        f"deliverables/{row.id}/{file_name}", data, _CONTENT_TYPE[fmt]
    )
    await db.commit()
    result.notes.append(f"已交付文件「{file_name}」，见工作桌面文件交付区")
    # 结构化载荷（阶段A 产出管道，docs/14 §4.1）：交付引用供下游步骤/前端定位
    result.artifacts.append(
        {
            "deliverable_id": str(row.id), "file_name": file_name,
            "file_format": fmt, "storage_path": row.storage_path,
            "file_size": len(data), "agent_name": initiator.name,
        }
    )


async def execute(
    db: AsyncSession, initiator: AgentRole, output: str,
    *, user_id: uuid.UUID | None = None,
) -> ProtocolResult:
    """解析并执行产出中的交付指令。每条独立容错转 note，永不 raise。"""
    result = ProtocolResult()
    try:
        items = parse(output)
        if not items:
            return result  # 零指令快速路径（绝大多数回复）
        if not await _enabled(db):
            return result
        if user_id is None:
            result.notes.append("交付需指定接收人，自动任务无桌面归属，已跳过文件交付")
            return result
        for name, fmt, body in items:
            try:
                await _deliver_one(db, initiator, user_id, name, fmt, body, result)
            except Exception:  # noqa: BLE001 - 单条交付失败不影响其余
                logger.warning("交付执行失败 name=%s fmt=%s", name, fmt, exc_info=True)
                result.notes.append(f"交付「{name}」失败，已忽略")
    except Exception:  # noqa: BLE001 - 交付层故障不连累业务消息流
        logger.warning("交付协议处理失败", exc_info=True)
    return result


async def list_deliverables(
    db: AsyncSession, owner_user_id: uuid.UUID, *, limit: int = 50
) -> list[dict[str, str | int]]:
    """某真人桌面的交付物（未删除，按时间倒序）。"""
    stmt = (
        select(Deliverable)
        .where(
            Deliverable.owner_user_id == owner_user_id,
            Deliverable.is_delete.is_(False),
        )
        .order_by(Deliverable.create_time.desc())
        .limit(limit)
    )
    return [
        {
            "id": str(d.id), "file_name": d.file_name, "file_format": d.file_format,
            "agent_name": d.agent_name, "file_size": d.file_size,
            "create_time": d.create_time.isoformat(),
        }
        for d in (await db.execute(stmt)).scalars()
    ]
