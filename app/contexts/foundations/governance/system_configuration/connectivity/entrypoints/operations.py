"""Published connectivity operations."""

from ..contracts import ConnectivityProbeResult
from ..infrastructure.composition import probe_external_dependencies


async def test_external_connectivity() -> tuple[ConnectivityProbeResult, ...]:
    return await probe_external_dependencies()
