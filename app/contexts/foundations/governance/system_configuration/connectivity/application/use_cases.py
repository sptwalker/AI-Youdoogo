"""Run the configured external dependency probes."""

from __future__ import annotations

from ..contracts import ConnectivityProbeResult
from .ports import ConnectivityProbePort


class TestExternalConnectivity:
    def __init__(self, probes: tuple[ConnectivityProbePort, ...]) -> None:
        self._probes = probes

    async def execute(self) -> tuple[ConnectivityProbeResult, ...]:
        return tuple([await probe.probe() for probe in self._probes])
