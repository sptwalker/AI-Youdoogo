"""Skill descriptors, feature gates, and prompt metadata."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.contracts import AgentSubject, SkillExecutor, agent_subject
from app.agents.legacy_skill_adapters import (
    LegacyExecutor,
    legacy_collab,
    legacy_deliver,
    legacy_query,
    legacy_read_url,
)
from app.contexts.foundations.execution.capability_catalog.contracts.definition import (
    CapabilityDefinition,
)
from app.contexts.foundations.execution.capability_catalog.infrastructure.registry import (
    CAPABILITY_DEFINITIONS,
)
from app.contexts.foundations.governance.system_configuration import (
    public as system_configuration,
)

logger = logging.getLogger(__name__)

ConfigurationResolver = Callable[[AsyncSession, str, Any], Awaitable[Any]]


@dataclass(frozen=True)
class Skill:
    """Legacy runtime binding kept separate from catalog metadata."""

    definition: CapabilityDefinition
    executor_factory: Callable[[], SkillExecutor] | None = None
    legacy_executor: LegacyExecutor | None = None

    @property
    def key(self) -> str:
        return self.definition.key

    @property
    def label(self) -> str:
        return self.definition.label

    @property
    def description(self) -> str:
        return self.definition.description

    @property
    def flag_key(self) -> str:
        return self.definition.feature_flag or ""

    @property
    def default_on(self) -> bool:
        return self.definition.default_enabled


_DEFINITIONS = {definition.key: definition for definition in CAPABILITY_DEFINITIONS}


def _collab_executor() -> SkillExecutor:
    from app.contexts.business.collaboration_requests.entrypoints import agent_capability

    return agent_capability.CollabSkillExecutor()


def _deliver_executor() -> SkillExecutor:
    from app.contexts.foundations.execution.deliverable_management.entrypoints import (
        agent_capability,
    )

    return agent_capability.DeliverySkillExecutor()


def _query_executor() -> SkillExecutor:
    from app.contexts.foundations.integration.governed_data_query.entrypoints import (
        agent_capability,
    )

    return agent_capability.DataQuerySkillExecutor()


def _read_url_executor() -> SkillExecutor:
    from app.contexts.foundations.integration.read_url.entrypoints import (
        agent_capability,
    )

    return agent_capability.ReadUrlSkillExecutor()


REGISTRY: dict[str, Skill] = {
    "env_context": Skill(
        _DEFINITIONS["env_context"],
    ),
    "collab": Skill(
        _DEFINITIONS["collab"],
        executor_factory=_collab_executor,
        legacy_executor=legacy_collab,
    ),
    "deliver": Skill(
        _DEFINITIONS["deliver"],
        executor_factory=_deliver_executor,
        legacy_executor=legacy_deliver,
    ),
    "data_query": Skill(
        _DEFINITIONS["data_query"],
        executor_factory=_query_executor,
        legacy_executor=legacy_query,
    ),
    "read_url": Skill(
        _DEFINITIONS["read_url"],
        executor_factory=_read_url_executor,
        legacy_executor=legacy_read_url,
    ),
}


def enabled_skills(role: AgentSubject | object) -> list[Skill]:
    """Return enabled skills; an empty tools list means all defaults are enabled."""
    subject = agent_subject(role)
    tools = list(subject.capability_keys)
    if not tools and not subject.capabilities_configured:
        return [skill for skill in REGISTRY.values() if skill.default_on]
    return [REGISTRY[key] for key in tools if key in REGISTRY]


async def flag_on(
    db: AsyncSession,
    skill: Skill,
    resolver: ConfigurationResolver | None = None,
) -> bool:
    resolve = resolver or system_configuration.resolve_configuration
    flag = await resolve(db, skill.flag_key, True)
    return str(flag).lower() not in ("false", "0")


async def _section(db: AsyncSession, skill: Skill) -> str:
    if skill.key == "env_context":
        from app.contexts.foundations.environment_projection import (
            public as environment_projection,
        )

        snapshot = await environment_projection.get_env_context(db)
        if not snapshot:
            return ""
        return f"\n\n【系统环境快照】（由系统档案员维护，实时数据，可直接引用）\n{snapshot}"
    if skill.key == "collab":
        from app.contexts.business.collaboration_requests.entrypoints import (
            agent_capability as collaboration_capability,
        )

        return collaboration_capability.PROMPT_SECTION
    if skill.key == "deliver":
        from app.contexts.foundations.execution.deliverable_management.entrypoints import (
            agent_capability as delivery_capability,
        )

        return delivery_capability.PROMPT_SECTION
    if skill.key == "data_query":
        from app.contexts.foundations.integration.governed_data_query.entrypoints import (
            agent_capability as query_capability,
        )

        return await query_capability.prompt_section(db)
    if skill.key == "read_url":
        from app.contexts.foundations.integration.read_url.entrypoints import (
            agent_capability as read_url_capability,
        )

        return await read_url_capability.prompt_section()
    return ""


async def prompt_sections(
    db: AsyncSession,
    role: AgentSubject | object,
    resolver: ConfigurationResolver | None = None,
) -> str:
    """Build enabled prompt sections while isolating individual skill failures."""
    parts: list[str] = []
    for skill in enabled_skills(role):
        try:
            if await flag_on(db, skill, resolver):
                parts.append(await _section(db, skill))
        except Exception:  # noqa: BLE001 - one prompt failure must not block the agent
            logger.warning("技能提示词段注入失败 skill=%s", skill.key, exc_info=True)
    return "".join(parts)
