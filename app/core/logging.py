"""统一日志配置：标准 logging，全局一次初始化。"""

import logging

from app.core.request_context import TraceIdLogFilter

_FORMAT = "%(asctime)s | %(levelname)-7s | %(trace_id)s | %(name)s | %(message)s"


def setup_logging(level: str = "INFO") -> None:
    """应用启动时调用一次，统一根日志格式与级别，并挂 trace_id 关联。"""
    logging.basicConfig(level=level.upper(), format=_FORMAT)
    # trace_id 挂到根 handler：每条日志带当前请求 id（请求外为 "-"）。
    for handler in logging.getLogger().handlers:
        handler.addFilter(TraceIdLogFilter())
    # 降噪第三方
    logging.getLogger("httpx").setLevel(logging.WARNING)
