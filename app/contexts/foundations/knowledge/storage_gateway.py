"""Compatibility facade for the shared object-storage runtime."""

from app.platform.object_storage.gateway import (
    get_object_bytes as get_object_bytes,
)
from app.platform.object_storage.gateway import put_object as put_object

__all__ = ["get_object_bytes", "put_object"]
