"""Capability Execution entrypoints（含同步 Provider 服务面 HTTP，默认关经 bootstrap 条件挂载）。"""

from __future__ import annotations

from app.contexts.foundations.execution.capability_execution.entrypoints.http import (
    CAPABILITIES_EXECUTE_SCOPE,
    PROVIDER_OVERRIDE_KEY,
    ProviderOverride,
    router,
)

__all__ = [
    "CAPABILITIES_EXECUTE_SCOPE",
    "PROVIDER_OVERRIDE_KEY",
    "ProviderOverride",
    "router",
]
