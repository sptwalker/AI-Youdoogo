"""Versioned capability metadata without runtime handlers."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class CapabilityRisk(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class CapabilitySideEffect(StrEnum):
    NONE = "none"
    INTERNAL_WRITE = "internal_write"
    EXTERNAL_WRITE = "external_write"


@dataclass(frozen=True, slots=True)
class CapabilityDefinition:
    key: str
    version: str
    label: str
    description: str
    input_schema_json: str
    output_schema_json: str
    risk: CapabilityRisk
    side_effect: CapabilitySideEffect
    permission_keys: tuple[str, ...]
    handler_identity: str
    feature_flag: str | None = None
    default_enabled: bool = True


class CapabilityTransport(StrEnum):
    """Provider 协议传输资格：能力可被 Provider 同步就地服务，还是必须经事件门禁交接。"""

    SYNC_LOCAL = "sync_local"
    EVENT_GATED = "event_gated"


def capability_transport(definition: CapabilityDefinition) -> CapabilityTransport:
    """按副作用判传输资格（docs/23 §4.5）：无副作用=只读/短事务可同步就地；有写=必经事件门禁。

    risk 轴正交——审批门已由 human-review 按 risk 驱动真人复核，不并入此判别。
    # ponytail: EVENT_GATED 现仍就地执行；真正的远端异步交接待 Phase 3 远端 Provider 落地。
    """
    if definition.side_effect is CapabilitySideEffect.NONE:
        return CapabilityTransport.SYNC_LOCAL
    return CapabilityTransport.EVENT_GATED
