"""业务异常与统一响应格式 {code, msg, data}。

覆盖全部错误路径：AppError（业务）、RequestValidationError（422）、
HTTPException（404/405等框架错误）、未捕获异常（500，不泄露内部细节）。
"""

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)


def ok(data: Any = None, msg: str = "ok") -> dict[str, Any]:
    """成功响应体。"""
    return {"code": 0, "msg": msg, "data": data}


def _err(status_code: int, code: int, msg: str, data: Any = None) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"code": code, "msg": msg, "data": data})


class AppError(Exception):
    """业务异常：code 非 0，msg 面向用户。"""

    def __init__(self, msg: str, code: int = 1, status_code: int = 400) -> None:
        self.msg = msg
        self.code = code
        self.status_code = status_code
        super().__init__(msg)


def register_exception_handlers(app: FastAPI) -> None:
    """挂载全局异常处理，保证所有错误也返回 {code, msg, data}。"""

    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        return _err(exc.status_code, exc.code, exc.msg)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        return _err(422, 422, "参数校验失败", data=exc.errors())

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        return _err(exc.status_code, exc.status_code, str(exc.detail))

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        # 细节只进日志，不回显给客户端
        logger.exception("未捕获异常：%s %s", request.method, request.url.path)
        return _err(500, 500, "服务器内部错误")
