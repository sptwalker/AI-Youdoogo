"""Stable Wiki Management application facade for outer adapters."""

from app.contexts.foundations.knowledge.wiki_management.entrypoints.operations import (
    create_knowledge_base as create_knowledge_base,
)
from app.contexts.foundations.knowledge.wiki_management.entrypoints.operations import (
    delete_knowledge_base as delete_knowledge_base,
)
from app.contexts.foundations.knowledge.wiki_management.entrypoints.operations import (
    get_default_knowledge_base as get_default_knowledge_base,
)
from app.contexts.foundations.knowledge.wiki_management.entrypoints.operations import (
    get_knowledge_base as get_knowledge_base,
)
from app.contexts.foundations.knowledge.wiki_management.entrypoints.operations import (
    list_knowledge_bases as list_knowledge_bases,
)
from app.contexts.foundations.knowledge.wiki_management.entrypoints.operations import (
    update_knowledge_base as update_knowledge_base,
)
from app.contexts.foundations.knowledge.wiki_management.infrastructure.sqlalchemy import (
    ensure_personal_kb as ensure_personal_kb,
)
from app.contexts.foundations.knowledge.wiki_management.infrastructure.visibility import (
    agent_visible_knowledge_base_ids as agent_visible_knowledge_base_ids,
)
from app.contexts.foundations.knowledge.wiki_management.infrastructure.visibility import (
    ancestor_department_ids as ancestor_department_ids,
)
from app.contexts.foundations.knowledge.wiki_management.infrastructure.visibility import (
    visible_knowledge_base_ids as visible_knowledge_base_ids,
)
