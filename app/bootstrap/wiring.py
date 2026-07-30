"""FastAPI route registration owned by the composition root."""

from fastapi import FastAPI

from app.api.v1.admin import router as admin_router
from app.api.v1.agents import router as agents_router
from app.api.v1.ai_providers import router as ai_providers_router
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
from app.api.v1.ops_data import router as ops_data_router
from app.api.v1.org import router as org_router
from app.api.v1.proposals import router as proposals_router
from app.api.v1.semantic import router as semantic_router
from app.api.v1.tasks import router as tasks_router
from app.api.v1.users import router as users_router
from app.contexts.business.proposal_management.entrypoints import (
    register_proposal_error_handlers,
)
from app.platform.eventing.entrypoints import router as eventing_router


def register_routes(app: FastAPI) -> None:
    """Register all current HTTP entrypoints without giving them composition duties."""
    prefix = "/api/v1"
    for router in (
        auth_router,
        users_router,
        knowledge_router,
        knowledge_bases_router,
        data_sources_router,
        agents_router,
        ops_data_router,
        tasks_router,
        proposals_router,
        meetings_router,
        org_router,
        desktop_router,
        discussion_router,
        discussion_message_router,
        admin_router,
        grants_router,
        collab_router,
        ai_providers_router,
        semantic_router,
        eval_router,
    ):
        app.include_router(router, prefix=prefix)
    # 服务间事件入站端点：不挂 /api/v1（内部服务身份鉴权，非面向用户的公开 API）。
    app.include_router(eventing_router)
    register_proposal_error_handlers(app)
