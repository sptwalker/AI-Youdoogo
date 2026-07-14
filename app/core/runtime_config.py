"""运行时配置覆盖层（sys_config 覆盖 .env）。

让 AI/外部数据/飞书 等配置可在「系统配置」页填写并被 app 实际使用：
  effective(key) = sys_config 覆盖值(非空) → .env(Settings) → default。
启动时从 sys_config 载入一次；改配置(set_config)后同步更新本进程覆盖。
# ponytail: 进程内缓存，多 worker 下各自持有；需跨进程实时一致再上 Redis/pub-sub。
密钥虽存 DB，但 list 接口读时脱敏、审计 detail 打码、绝不硬编码。
"""

from __future__ import annotations

from typing import Any

from app.core.config import get_settings

_overlay: dict[str, Any] = {}


def effective(key: str, default: Any = "") -> Any:
    """取生效配置：sys_config 覆盖值(非空) 优先，否则 .env 同名字段，否则 default。"""
    v = _overlay.get(key)
    if v is not None and v != "":
        return v
    return getattr(get_settings(), key, default)


def set_override(key: str, value: Any) -> None:
    """改配置后同步本进程覆盖（config_service.set_config 调用）。"""
    _overlay[key] = value


def load(values: dict[str, Any]) -> None:
    """启动时用 sys_config 全量 key→value 覆盖（main lifespan 调用）。"""
    _overlay.clear()
    _overlay.update(values)
