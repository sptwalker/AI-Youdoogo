"""Connectivity probe ports."""

from __future__ import annotations

from typing import Protocol

from ..contracts import ConnectivityProbeResult


class ConnectivityProbePort(Protocol):
    async def probe(self) -> ConnectivityProbeResult: ...
