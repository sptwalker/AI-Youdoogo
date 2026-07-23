"""Published connectivity operations."""

from ..contracts import ConnectivityProbeResult
from ..infrastructure.composition import build_connectivity_test


async def test_external_connectivity() -> tuple[ConnectivityProbeResult, ...]:
    return await build_connectivity_test().execute()
