"""平台运营数据接口：Excel 上传落库 + 按日查询指标。"""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, File, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, require_roles
from app.contexts.shared_kernel import RuleViolation
from app.core.database import get_db
from app.integrations.thinkingdata.client import ThinkingDataError
from app.models.system import SysUser
from app.platform.http_runtime import ok
from app.services import data_catalog_service, data_query_service, ops_data, td_event_service
from app.services.excel_ingest import ExcelParseError

router = APIRouter(prefix="/ops-data", tags=["ops-data"])

DB = Annotated[AsyncSession, Depends(get_db)]
Manager = Annotated[SysUser, Depends(require_roles("admin", "executive"))]

_MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # 20MB 上限，防大文件读入内存 OOM


class EventAlias(BaseModel):
    """一条事件别名。display_name 空串=清除。"""

    view: str = Field(min_length=1, max_length=64)
    event_code: str = Field(min_length=1, max_length=128)
    display_name: str = Field(default="", max_length=128)


class EventAliasSave(BaseModel):
    """批量保存事件别名。"""

    aliases: list[EventAlias] = Field(default_factory=list, max_length=500)


class SqlQuery(BaseModel):
    """只读取数请求。"""

    sql: str = Field(min_length=1, max_length=5000)


@router.get("/catalog")
async def get_catalog(db: DB, _: Manager) -> dict:
    """AI 可读数据目录:数据源 + 视图→产品 + 已命名事件（供取数/外部预览）。"""
    return ok(await data_catalog_service.get_catalog(db))


@router.post("/query")
async def run_query(body: SqlQuery, db: DB, user: Manager) -> dict:
    """只读 SQL 取数:护栏校验（仅SELECT+白名单视图+强制LIMIT）→ 执行 → 截断 → 审计。"""
    return ok(await data_query_service.run_readonly_sql(
        db, body.sql, actor_id=user.id, actor_role=user.role_code, source="manual",
    ))


@router.get("/events")
async def list_events(
    db: DB,
    _: Manager,
    stat_date: Annotated[date, Query(description="统计日期 YYYY-MM-DD")],
) -> dict:
    """列出各视图当日全部事件码+次数（合并已存中文别名），供「运营事件命名」。"""
    return ok(await td_event_service.list_events(db, stat_date))


@router.put("/event-aliases")
async def save_event_aliases(body: EventAliasSave, db: DB, _: Manager) -> dict:
    """批量保存事件中文别名（空串清除）。"""
    n = await td_event_service.save_aliases(
        db, [a.model_dump() for a in body.aliases]
    )
    return ok({"saved": n})


@router.post("/daily/upload")
async def upload_daily(db: DB, _: Manager, file: Annotated[UploadFile, File()]) -> dict:
    """上传 ops_daily 模板 Excel（≤20MB），解析后幂等落库。"""
    if file.size is not None and file.size > _MAX_UPLOAD_BYTES:
        raise RuleViolation("文件过大（>20MB），请压缩或拆分后上传")
    content = await file.read()
    if len(content) > _MAX_UPLOAD_BYTES:
        raise RuleViolation("文件过大（>20MB），请压缩或拆分后上传")
    try:
        summary = await ops_data.ingest_ops_daily_excel(db, content)
    except ExcelParseError as exc:
        raise RuleViolation(str(exc)) from exc
    return ok(summary)


@router.get("/daily")
async def list_daily(
    db: DB,
    _: CurrentUser,
    stat_date: Annotated[date, Query(description="统计日期 YYYY-MM-DD")],
) -> dict:
    """查询某日运营指标。"""
    return ok(await ops_data.get_ops_metrics(db, stat_date))


@router.get("/test-read")
async def test_read(
    db: DB,
    _: Manager,
    stat_date: Annotated[date, Query(description="统计日期 YYYY-MM-DD")],
) -> dict:
    """用生效配置（含 UI 填的密钥/地址）真跑一次 TD 日指标查询验证读取，不落库、不回显密钥。"""
    return ok(await ops_data.test_read_thinkingdata(db, stat_date))


@router.post("/sync-thinkingdata")
async def sync_thinkingdata(
    db: DB,
    _: Manager,
    stat_date: Annotated[date, Query(description="统计日期 YYYY-MM-DD")],
) -> dict:
    """从 ThinkingData 拉取某日运营指标入库（地址/SQL/字段映射见系统配置，密钥见 .env）。"""
    try:
        return ok(await ops_data.ingest_from_thinkingdata(db, stat_date))
    except ThinkingDataError as exc:
        raise RuleViolation(f"ThinkingData 拉取失败：{exc}") from exc
