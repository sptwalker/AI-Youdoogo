"""平台运营数据接口：Excel 上传落库 + 按日查询指标。"""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, File, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, require_roles
from app.core.database import get_db
from app.core.exceptions import AppError, ok
from app.integrations.thinkingdata.client import ThinkingDataError
from app.models.system import SysUser
from app.services import ops_data
from app.services.excel_ingest import ExcelParseError

router = APIRouter(prefix="/ops-data", tags=["ops-data"])

DB = Annotated[AsyncSession, Depends(get_db)]
Manager = Annotated[SysUser, Depends(require_roles("admin", "executive"))]

_MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # 20MB 上限，防大文件读入内存 OOM


@router.post("/daily/upload")
async def upload_daily(db: DB, _: Manager, file: Annotated[UploadFile, File()]) -> dict:
    """上传 ops_daily 模板 Excel（≤20MB），解析后幂等落库。"""
    if file.size is not None and file.size > _MAX_UPLOAD_BYTES:
        raise AppError("文件过大（>20MB），请压缩或拆分后上传")
    content = await file.read()
    if len(content) > _MAX_UPLOAD_BYTES:
        raise AppError("文件过大（>20MB），请压缩或拆分后上传")
    try:
        summary = await ops_data.ingest_ops_daily_excel(db, content)
    except ExcelParseError as exc:
        raise AppError(str(exc)) from exc
    return ok(summary)


@router.get("/daily")
async def list_daily(
    db: DB,
    _: CurrentUser,
    stat_date: Annotated[date, Query(description="统计日期 YYYY-MM-DD")],
) -> dict:
    """查询某日运营指标。"""
    return ok(await ops_data.get_ops_metrics(db, stat_date))


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
        raise AppError(f"ThinkingData 拉取失败：{exc}") from exc
