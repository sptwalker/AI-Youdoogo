"""Compatibility module alias for canonical Knowledge Indexing infrastructure."""

from __future__ import annotations

import sys

from app.contexts.foundations.knowledge.knowledge_indexing.infrastructure import (
    sqlalchemy_index as _implementation,
)

sys.modules[__name__] = _implementation
