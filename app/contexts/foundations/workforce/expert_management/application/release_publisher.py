"""Release 发布推送端口（Module 2 / docs/23 §4.2）。

发布是真人确认的特权写，快照真源在 youdoo 库；本端口只负责发布**后**把冻结快照「推」到远端
专家平台（远端据此在 ``_prepare`` 阶段组装 prompt）。默认 ``NoopReleasePublisher`` 不出站；
组合根按 ``expert_execution_mode`` 选 ``HttpReleasePublisher``。推送失败非致命（youdoo 真源，
尽力而为），由 ``publish_release`` 调用点 log+swallow。
"""

from __future__ import annotations

from typing import Protocol

from app.contexts.foundations.workforce.expert_management.domain.models import (
    ExpertRelease,
)


class ReleasePublisherPort(Protocol):
    async def publish(self, release: ExpertRelease) -> None: ...


class NoopReleasePublisher:
    """默认：不推送（``expert_execution_mode=local`` 或未配远端时，生产逐字不变）。"""

    async def publish(self, release: ExpertRelease) -> None:
        return None
