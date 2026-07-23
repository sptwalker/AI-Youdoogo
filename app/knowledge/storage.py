"""Compatibility facade for the Knowledge object-storage gateway."""

from app.contexts.foundations.knowledge.storage_gateway import (
    get_object_bytes as get_object_bytes,
)
from app.contexts.foundations.knowledge.storage_gateway import put_object as put_object

__all__ = ["get_object_bytes", "put_object"]
