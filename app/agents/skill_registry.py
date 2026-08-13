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
    legacy_compose_feishu,
    legacy_convene_consultation,
    legacy_create_operational_proposal,
    legacy_deliver,
    legacy_feishu_notify,
    legacy_feishu_notify_person,
    legacy_knowledge_index,
    legacy_knowledge_search,
    legacy_query,
    legacy_read_attachment,
    legacy_read_url,
    legacy_send_email,
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


def _read_attachment_executor() -> SkillExecutor:
    from app.contexts.foundations.integration.read_attachment.entrypoints import (
        agent_capability,
    )

    return agent_capability.ReadAttachmentSkillExecutor()


def _knowledge_index_executor() -> SkillExecutor:
    from app.contexts.foundations.knowledge.knowledge_indexing.entrypoints import (
        agent_capability,
    )

    return agent_capability.KnowledgeIndexSkillExecutor()


def _knowledge_search_executor() -> SkillExecutor:
    from app.contexts.foundations.knowledge.knowledge_search.entrypoints import (
        agent_capability,
    )

    return agent_capability.KnowledgeSearchSkillExecutor()


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
    "read_attachment": Skill(
        _DEFINITIONS["read_attachment"],
        executor_factory=_read_attachment_executor,
        legacy_executor=legacy_read_attachment,
    ),
    # 历史案例检索：文本指令路径「取回→回喂综合」（只读内部 KB，可信不加防注入 fence）；
    # 无副作用 → 进 AUTOMATIC，编排步无真人停点。prompt_section 始终可用（无门控）。
    "knowledge_search": Skill(
        _DEFINITIONS["knowledge_search"],
        executor_factory=_knowledge_search_executor,
        legacy_executor=legacy_knowledge_search,
    ),
    # compose 走文本指令路径产草稿（executor_factory=None，不作结构化调用）；红线停真人验收。
    # 机械发布半（feishu_publish）待跨模块编排专项统一重建，见 feishu_output.agent_capability。
    "compose_feishu": Skill(
        _DEFINITIONS["compose_feishu"],
        legacy_executor=legacy_compose_feishu,
    ),
    # 运营群播报：文本指令路径直发固定运营群（无结构化调用、无停点，self-gated 默认关）。
    "feishu_notify": Skill(
        _DEFINITIONS["feishu_notify"],
        legacy_executor=legacy_feishu_notify,
    ),
    # 定向飞书 compose 半：文本指令路径产草稿（executor_factory=None）；红线停真人验收，默认关。
    # 机械发布半（feishu_notify_person_publish）由 policies 配对 + 注入 publisher 按 key 派发，
    # 不入 REGISTRY、对规划器/对话不可见（镜像 compose_feishu→feishu_publish）。
    "feishu_notify_person": Skill(
        _DEFINITIONS["feishu_notify_person"],
        legacy_executor=legacy_feishu_notify_person,
    ),
    # 紧急会商 compose 半：文本指令路径产草稿（executor_factory=None，嵌 creator_id）；红线停真人
    # 验收，默认关。机械会商半（convene_consultation_publish）由 policies 配对 + 注入 publisher 按
    # publish_key 派发，不入 REGISTRY、对规划器/对话不可见（镜像 feishu_notify_person→publish）。
    "convene_consultation": Skill(
        _DEFINITIONS["convene_consultation"],
        legacy_executor=legacy_convene_consultation,
    ),
    # 发送邮件 compose 半：文本指令路径产草稿（executor_factory=None，收件人按 username 发布解析）；
    # 红线外部写停真人验收，默认关。机械发送半（send_email_publish）由 policies 配对 + 注入
    # publisher 按 publish_key 派发（自开 session），不入 REGISTRY。
    "send_email": Skill(
        _DEFINITIONS["send_email"],
        legacy_executor=legacy_send_email,
    ),
    # 运营提案：内部顾问输出（notify=False 无对外发送）→ 非红线，走文本指令路径产提案 artifact，
    # 进 AUTOMATIC（编排步免停）、default_enabled=True。无机械步、无结构化 executor。
    "create_operational_proposal": Skill(
        _DEFINITIONS["create_operational_proposal"],
        legacy_executor=legacy_create_operational_proposal,
    ),
    # 会商纪要：机械步（读上游 convene 真 meeting 生成纪要），由 legacy_execution._generate_minutes
    # 专列分支处理——仅登记定义（无 executor_factory/legacy_executor），供模板校验与目录一致性；
    # 对规划器/对话不可见（default_enabled=False，非默认集）。镜像 *_publish 机械键但为可见模板步。
    "generate_minutes": Skill(
        _DEFINITIONS["generate_minutes"],
    ),
    # knowledge_index 走文本指令路径（终端型内部写，无停点、无回喂）；
    # 内部知识沉淀属辅助执行，故进 AUTOMATIC_CAPABILITIES（编排步免红线）。
    "knowledge_index": Skill(
        _DEFINITIONS["knowledge_index"],
        executor_factory=_knowledge_index_executor,
        legacy_executor=legacy_knowledge_index,
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
    if skill.key == "read_attachment":
        from app.contexts.foundations.integration.read_attachment.entrypoints import (
            agent_capability as read_attachment_capability,
        )

        return await read_attachment_capability.prompt_section()
    if skill.key == "knowledge_search":
        from app.contexts.foundations.knowledge.knowledge_search.entrypoints import (
            agent_capability as knowledge_search_capability,
        )

        return await knowledge_search_capability.prompt_section()
    if skill.key == "compose_feishu":
        from app.contexts.foundations.integration.feishu_output.entrypoints import (
            agent_capability as feishu_output_capability,
        )

        return await feishu_output_capability.prompt_section()
    if skill.key == "feishu_notify":
        from app.contexts.foundations.integration.feishu_notify.entrypoints import (
            agent_capability as feishu_notify_capability,
        )

        return await feishu_notify_capability.prompt_section()
    if skill.key == "feishu_notify_person":
        from app.contexts.foundations.integration.feishu_notify_person.entrypoints import (
            agent_capability as feishu_notify_person_capability,
        )

        return await feishu_notify_person_capability.prompt_section()
    if skill.key == "convene_consultation":
        from app.contexts.foundations.integration.convene_consultation.entrypoints import (
            agent_capability as convene_consultation_capability,
        )

        return await convene_consultation_capability.prompt_section()
    if skill.key == "send_email":
        from app.contexts.foundations.integration.send_email.entrypoints import (
            agent_capability as send_email_capability,
        )

        return await send_email_capability.prompt_section()
    if skill.key == "create_operational_proposal":
        from app.contexts.business.operational_analytics.entrypoints import (
            agent_capability as operational_proposal_capability,
        )

        return await operational_proposal_capability.prompt_section()
    if skill.key == "knowledge_index":
        from app.contexts.foundations.knowledge.knowledge_indexing.entrypoints import (
            agent_capability as knowledge_index_capability,
        )

        return await knowledge_index_capability.prompt_section()
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
