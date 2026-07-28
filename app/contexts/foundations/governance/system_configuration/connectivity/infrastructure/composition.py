"""Composition and execution for external connectivity probes."""

from ..contracts import ConnectivityProbeResult
from .adapters import (
    EmbeddingConnectivityProbe,
    FeishuConnectivityProbe,
    LLMConnectivityProbe,
    ThinkingDataConnectivityProbe,
)


async def probe_external_dependencies() -> tuple[ConnectivityProbeResult, ...]:
    probes = (
        LLMConnectivityProbe(),
        EmbeddingConnectivityProbe(),
        FeishuConnectivityProbe(),
        ThinkingDataConnectivityProbe(),
    )
    return tuple([await probe.probe() for probe in probes])
