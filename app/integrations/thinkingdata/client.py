"""ThinkingData（数数科技 TE）Open API 异步客户端。

接口契约依据 docs/11-数据接入设计 附录B（官方文档 data_api）：
- POST /querySql            同步查询，响应为多行文本：首行 meta JSON + 每行一条数据
- POST /open/execute-sql    提交分页查询，返回 taskId/pageCount
- GET  /open/sql-result-page 按 taskId+pageId 取页数据
- token 一律走 URL 参数；return_code 0=成功，-1005=请求频率过快（限流）

ponytail: /open/submit-sql 异步任务（大区间历史补拉）暂未封装，需要时再加。
安全约定：token 不进日志、不进异常信息；实际响应格式以联调为准（见 docs/11 B.4）。
"""

import asyncio
import json
import logging
from collections.abc import AsyncGenerator
from typing import Any

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_RATE_LIMIT_CODE = -1005
_MAX_RETRIES = 3


class ThinkingDataError(Exception):
    """TD 接口错误：带 return_code 与服务端 message（已确保不含 token）。"""

    def __init__(self, message: str, return_code: int | None = None) -> None:
        self.return_code = return_code
        super().__init__(message)


class ThinkingDataClient:
    """轻量异步客户端：仅封装本系统数据接入所需的查询能力。"""

    def __init__(
        self,
        base_url: str | None = None,
        api_secret: str | None = None,
        retry_base_delay: float = 0.5,
    ) -> None:
        settings = get_settings()
        self._base_url = (base_url if base_url is not None else settings.td_base_url).rstrip("/")
        self._secret = api_secret if api_secret is not None else settings.td_api_secret
        self._retry_base_delay = retry_base_delay
        self._client: httpx.AsyncClient | None = None

    def _ensure_config(self) -> None:
        if not self._base_url or not self._secret:
            raise ThinkingDataError("未配置 TD_BASE_URL / TD_API_SECRET（见 .env.example）")

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(base_url=self._base_url, timeout=120)
        return self._client

    async def close(self) -> None:
        """释放连接（FastAPI lifespan 关闭时调用）。"""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _request(self, method: str, path: str, params: dict[str, Any]) -> httpx.Response:
        """带限流退避的请求：-1005 或网络错误时指数退避重试。"""
        self._ensure_config()
        params = {"token": self._secret, **params}
        last_error: Exception | None = None
        for attempt in range(_MAX_RETRIES + 1):
            if attempt:
                await asyncio.sleep(self._retry_base_delay * (2 ** (attempt - 1)))
            try:
                resp = await self._http().request(method, path, params=params)
                resp.raise_for_status()
            except httpx.HTTPError as exc:
                # 不复用 str(exc)：httpx 异常文本含带 token 的完整 URL
                last_error = ThinkingDataError(f"请求失败（{type(exc).__name__}），路径 {path}")
                logger.warning("TD 请求异常，第 %s 次重试：%s", attempt + 1, type(exc).__name__)
                continue
            meta = self._peek_meta(resp.text)
            if meta is not None and meta.get("return_code") == _RATE_LIMIT_CODE:
                last_error = ThinkingDataError("请求频率过快", return_code=_RATE_LIMIT_CODE)
                logger.warning("TD 限流(-1005)，第 %s 次退避重试", attempt + 1)
                continue
            return resp
        raise last_error if last_error else ThinkingDataError(f"请求失败，路径 {path}")

    @staticmethod
    def _peek_meta(text: str) -> dict[str, Any] | None:
        """取响应首行 meta（解析失败返回 None，交由上层按数据行处理）。"""
        first_line = text.strip().split("\n", 1)[0]
        try:
            meta = json.loads(first_line)
        except json.JSONDecodeError:
            return None
        return meta if isinstance(meta, dict) and "return_code" in meta else None

    @staticmethod
    def _check_meta(meta: dict[str, Any] | None, context: str) -> dict[str, Any]:
        if meta is None:
            raise ThinkingDataError(f"{context}：响应格式无法解析")
        code = meta.get("return_code")
        if code != 0:
            raise ThinkingDataError(
                f"{context}：{meta.get('return_message', '未知错误')}", return_code=code
            )
        return meta

    def _parse_rows(self, text: str, context: str) -> list[Any]:
        """解析「首行 meta + 每行一条 JSON 数据」的响应体。"""
        lines = [ln for ln in text.strip().split("\n") if ln.strip()]
        if not lines:
            return []
        self._check_meta(self._peek_meta(text), context)
        return [json.loads(ln) for ln in lines[1:]]

    async def query_sql(
        self, sql: str, *, fmt: str = "json_object", timeout_seconds: int = 60
    ) -> list[Any]:
        """同步 SQL 查询（小结果集，如日汇总指标）。

        Returns:
            数据行列表；fmt=json_object 时每行为 dict（列名→值）。
        """
        resp = await self._request(
            "POST", "/querySql", {"sql": sql, "format": fmt, "timeoutSeconds": timeout_seconds}
        )
        rows = self._parse_rows(resp.text, "querySql")
        logger.info("TD querySql 完成：%s 行（sql 前80字：%s）", len(rows), sql[:80])
        return rows

    async def iter_sql_rows(
        self,
        sql: str,
        *,
        page_size: int = 1000,
        fmt: str = "json_object",
        timeout_seconds: int = 600,
    ) -> AsyncGenerator[Any, None]:
        """分页 SQL 查询（日增量明细拉取首选）：提交后逐页取数、逐行产出。

        page_size 服务端最小 1000；页间串行请求，配合 -1005 退避不打爆接口。
        """
        resp = await self._request(
            "POST",
            "/open/execute-sql",
            {"sql": sql, "format": fmt, "pageSize": page_size, "timeoutSeconds": timeout_seconds},
        )
        meta = self._check_meta(self._peek_meta(resp.text), "execute-sql")
        data = meta.get("data") or {}
        task_id, page_count = data.get("taskId"), int(data.get("pageCount") or 0)
        if not task_id:
            raise ThinkingDataError("execute-sql：响应缺少 taskId")
        logger.info("TD execute-sql 提交完成：taskId=%s，共 %s 页", task_id, page_count)
        for page_id in range(page_count):
            page_resp = await self._request(
                "GET", "/open/sql-result-page", {"taskId": task_id, "pageId": page_id}
            )
            for row in self._parse_rows(page_resp.text, f"sql-result-page[{page_id}]"):
                yield row


td_client = ThinkingDataClient()
