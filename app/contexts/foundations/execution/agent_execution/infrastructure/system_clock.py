"""Monotonic execution clock adapter."""

import time


class SystemExecutionClock:
    def monotonic_ms(self) -> int:
        return int(time.monotonic() * 1000)
