"""Capability Provider 传输资格判别（Module 5 / docs/23 §4.5）——纯派生，离线。

守护不变式：SYNC_LOCAL ⟺ 无副作用。防未来把写副作用能力误标为可同步就地迁移。
"""

from __future__ import annotations

from app.contexts.foundations.execution.capability_catalog.contracts.definition import (
    CapabilitySideEffect,
    CapabilityTransport,
    capability_transport,
)
from app.contexts.foundations.execution.capability_catalog.infrastructure.registry import (
    CAPABILITY_DEFINITIONS,
)


def test_sync_local_iff_no_side_effect() -> None:
    for definition in CAPABILITY_DEFINITIONS:
        transport = capability_transport(definition)
        no_side_effect = definition.side_effect is CapabilitySideEffect.NONE
        assert (transport is CapabilityTransport.SYNC_LOCAL) is no_side_effect


def test_current_catalog_classification() -> None:
    by_key = {d.key: capability_transport(d) for d in CAPABILITY_DEFINITIONS}
    assert by_key["env_context"] is CapabilityTransport.SYNC_LOCAL
    assert by_key["data_query"] is CapabilityTransport.SYNC_LOCAL
    assert by_key["collab"] is CapabilityTransport.EVENT_GATED
    assert by_key["deliver"] is CapabilityTransport.EVENT_GATED
