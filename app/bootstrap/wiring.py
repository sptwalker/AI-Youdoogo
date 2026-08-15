"""FastAPI route registration owned by the composition root."""

from fastapi import FastAPI

from app.api.v1.admin import router as admin_router
from app.api.v1.agents import router as agents_router
from app.api.v1.ai_providers import router as ai_providers_router
from app.api.v1.ai_tasks import router as ai_tasks_router
from app.api.v1.auth import router as auth_router
from app.api.v1.collab import router as collab_router
from app.api.v1.data_sources import router as data_sources_router
from app.api.v1.desktop import router as desktop_router
from app.api.v1.discussion import message_router as discussion_message_router
from app.api.v1.discussion import router as discussion_router
from app.api.v1.eval import router as eval_router
from app.api.v1.grants import router as grants_router
from app.api.v1.knowledge import router as knowledge_router
from app.api.v1.knowledge_bases import router as knowledge_bases_router
from app.api.v1.meetings import router as meetings_router
from app.api.v1.my_knowledge import router as my_knowledge_router
from app.api.v1.ops_data import router as ops_data_router
from app.api.v1.org import router as org_router
from app.api.v1.projects import router as projects_router
from app.api.v1.proposals import router as proposals_router
from app.api.v1.schedule import router as schedule_router
from app.api.v1.semantic import router as semantic_router
from app.api.v1.tasks import router as tasks_router
from app.api.v1.users import router as users_router
from app.api.v1.workflow_templates import router as workflow_templates_router
from app.contexts.business.proposal_management.entrypoints import (
    register_proposal_error_handlers,
)
from app.core.config import get_settings
from app.platform.eventing.entrypoints import router as eventing_router


def register_routes(app: FastAPI) -> None:
    """Register all current HTTP entrypoints without giving them composition duties."""
    prefix = "/api/v1"
    for router in (
        auth_router,
        users_router,
        knowledge_router,
        knowledge_bases_router,
        my_knowledge_router,
        data_sources_router,
        agents_router,
        ops_data_router,
        tasks_router,
        ai_tasks_router,
        proposals_router,
        projects_router,
        meetings_router,
        org_router,
        desktop_router,
        schedule_router,
        discussion_router,
        discussion_message_router,
        admin_router,
        grants_router,
        collab_router,
        ai_providers_router,
        semantic_router,
        eval_router,
        workflow_templates_router,
    ):
        app.include_router(router, prefix=prefix)
    # 服务间事件入站端点（docs/23 §3.3）：默认关 → 不注册（零新入站面）；on 才挂。不挂 /api/v1
    # （内部服务身份鉴权，非公开 API）。回环自验/收对端事件需 event_inbox_enabled=on。
    if get_settings().event_inbox_enabled:
        app.include_router(eventing_router)
    # 同步 Capability Provider 服务面（docs/23 §6.7）：默认关 → 不注册（生产逐字不变、零新攻击面）。
    if get_settings().capability_provider_enabled:
        from app.contexts.foundations.execution.capability_catalog.infrastructure.registry import (
            InMemoryCapabilityCatalog,
        )
        from app.contexts.foundations.execution.capability_execution.entrypoints import (
            PROVIDER_OVERRIDE_KEY,
            ProviderOverride,
        )
        from app.contexts.foundations.execution.capability_execution.entrypoints import (
            router as capability_provider_router,
        )

        # 组合根注入具体 catalog（entrypoints 不跨 Context 依赖 infra）；handler 默认走 REGISTRY。
        setattr(
            app.state,
            PROVIDER_OVERRIDE_KEY,
            ProviderOverride(catalog=InMemoryCapabilityCatalog()),
        )
        app.include_router(capability_provider_router)  # 内部端点不挂 /api/v1
    register_proposal_error_handlers(app)
