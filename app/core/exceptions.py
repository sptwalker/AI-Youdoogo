"""业务异常与统一响应格式 {code, msg, data}。"""

from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


def ok(data: Any = None, msg: str = "ok") -> dict[str, Any]:
    """成功响应体。"""
    return {"code": 0, "msg": msg, "data": data}


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
        return JSONResponse(
            status_code=exc.status_code,
            content={"code": exc.code, "msg": exc.msg, "data": None},
        )
