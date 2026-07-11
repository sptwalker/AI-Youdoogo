"""统一日志配置：标准 logging，全局一次初始化。"""

import logging

_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"


def setup_logging(level: str = "INFO") -> None:
    """应用启动时调用一次，统一根日志格式与级别。"""
    logging.basicConfig(level=level.upper(), format=_FORMAT)
    # 降噪第三方
    logging.getLogger("httpx").setLevel(logging.WARNING)
