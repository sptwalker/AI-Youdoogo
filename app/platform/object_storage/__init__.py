"""Shared object-storage runtime with dormant presigned-URL capabilities."""

from app.platform.object_storage.gateway import (
    ObjectStorageAccessDenied,
    get_object_bytes,
    presign_get_object,
    presign_put_object,
    put_object,
    validate_object_access,
)

__all__ = [
    "ObjectStorageAccessDenied",
    "get_object_bytes",
    "presign_get_object",
    "presign_put_object",
    "put_object",
    "validate_object_access",
]
