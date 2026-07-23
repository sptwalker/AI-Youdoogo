"""Stable Semantic Catalog application facade for outer adapters."""

from app.contexts.foundations.knowledge.semantic_catalog.entrypoints.operations import (
    create_term as create_term,
)
from app.contexts.foundations.knowledge.semantic_catalog.entrypoints.operations import (
    delete_term as delete_term,
)
from app.contexts.foundations.knowledge.semantic_catalog.entrypoints.operations import (
    expand_query as expand_query,
)
from app.contexts.foundations.knowledge.semantic_catalog.entrypoints.operations import (
    list_terms as list_terms,
)
from app.contexts.foundations.knowledge.semantic_catalog.entrypoints.operations import (
    term_prompt as term_prompt,
)
from app.contexts.foundations.knowledge.semantic_catalog.entrypoints.operations import (
    update_term as update_term,
)
