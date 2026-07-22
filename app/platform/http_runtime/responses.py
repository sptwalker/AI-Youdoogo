"""HTTP response-envelope helpers shared by delivery adapters."""

from typing import Any

from fastapi.responses import JSONResponse


def ok(data: Any = None, msg: str = "ok") -> dict[str, Any]:
    """Return the stable successful API response envelope."""
    return {"code": 0, "msg": msg, "data": data}


def error_response(
    status_code: int,
    code: int,
    msg: str,
    data: Any = None,
) -> JSONResponse:
    """Return the stable failed API response envelope."""
    return JSONResponse(
        status_code=status_code,
        content={"code": code, "msg": msg, "data": data},
    )
