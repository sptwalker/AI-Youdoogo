"""SSE 工具：把 (event, data) 异步流包装成 text/event-stream 响应。

统一协议（三个对话端点共用）：message_start / delta / message_end / done / error。
业务异常经 error 事件送达（流已 200 开头，无法再改状态码）；正常结束追加 done。
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from fastapi.responses import StreamingResponse

from app.contexts.shared_kernel import ApplicationError

logger = logging.getLogger(__name__)

Event = tuple[str, dict[str, Any]]


def _frame(name: str, data: dict[str, Any]) -> str:
    return f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def sse_response(source: AsyncIterator[Event]) -> StreamingResponse:
    """把服务层事件流转为 SSE 响应；异常转 error 事件，正常结束补 done。"""

    async def gen() -> AsyncIterator[str]:
        try:
            async for name, data in source:
                yield _frame(name, data)
        except ApplicationError as exc:
            yield _frame("error", {"msg": str(exc)})
            return
        except Exception:  # noqa: BLE001 - 流中未知异常也要给前端可显示的结束帧
            logger.exception("SSE 流处理异常")
            yield _frame("error", {"msg": "服务器内部错误"})
            return
        yield _frame("done", {})

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
