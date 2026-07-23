"""Published connectivity probe result."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ConnectivityProbeResult:
    target: str
    status: str
    latency_ms: int
    message: str

    def to_dict(self) -> dict[str, object]:
        return {
            "target": self.target,
            "status": self.status,
            "latency_ms": self.latency_ms,
            "msg": self.message,
        }
