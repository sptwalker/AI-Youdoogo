"""Shared object-storage runtime."""

from app.platform.object_storage.gateway import get_object_bytes, put_object

__all__ = ["get_object_bytes", "put_object"]
