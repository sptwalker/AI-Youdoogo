"""Composition for external connectivity probes."""

from ..application.use_cases import TestExternalConnectivity
from .adapters import (
    EmbeddingConnectivityProbe,
    FeishuConnectivityProbe,
    LLMConnectivityProbe,
    ThinkingDataConnectivityProbe,
)


def build_connectivity_test() -> TestExternalConnectivity:
    return TestExternalConnectivity(
        (
            LLMConnectivityProbe(),
            EmbeddingConnectivityProbe(),
            FeishuConnectivityProbe(),
            ThinkingDataConnectivityProbe(),
        )
    )
