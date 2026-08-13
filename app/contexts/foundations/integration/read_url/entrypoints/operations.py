"""Entrypoint 网关：暴露 run_read_url / read_url_available，隔离 infrastructure 细节。"""

from __future__ import annotations

import importlib.util

from app.contexts.foundations.integration.read_url.infrastructure.connector import (
    ReadUrlOutcome,
    UrlReader,
)


async def run_read_url(url: str) -> ReadUrlOutcome:
    return await UrlReader().fetch(url)


async def read_url_available() -> bool:
    """trafilatura 可用即视为能力就绪（无凭证，不靠 key 自门控）；缺依赖则不广告（优雅降级）。"""
    return importlib.util.find_spec("trafilatura") is not None
