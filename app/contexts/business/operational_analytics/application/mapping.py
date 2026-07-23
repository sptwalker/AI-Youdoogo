"""Pure configuration mapping policy."""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_MAPPING = {"product": "product", "dau": "dau", "new_users": "new_users"}
DEFAULT_EVENT_VIEWS = (
    ("v_event_4", "盒子"),
    ("v_event_5", "游戏"),
    ("v_event_6", "APP"),
)


def resolve_mapping(raw: Any) -> dict[str, str]:
    if isinstance(raw, dict):
        merged = {**DEFAULT_MAPPING, **raw}
        return {key: str(merged[key]) for key in DEFAULT_MAPPING}
    if isinstance(raw, str) and raw.strip():
        try:
            return resolve_mapping(json.loads(raw))
        except json.JSONDecodeError:
            logger.warning("td_field_mapping 非法 JSON，回退默认映射")
    return dict(DEFAULT_MAPPING)


def resolve_event_views(raw: Any) -> tuple[tuple[str, str], ...]:
    if isinstance(raw, str) and raw.strip():
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("td_event_views 非法 JSON，回退默认视图")
            return DEFAULT_EVENT_VIEWS
    if isinstance(raw, list):
        parsed = tuple(
            (str(item["view"]), str(item.get("product") or item["view"]))
            for item in raw
            if isinstance(item, dict) and item.get("view")
        )
        return parsed or DEFAULT_EVENT_VIEWS
    return DEFAULT_EVENT_VIEWS
