"""MinIO-backed object-storage mechanism shared by bounded contexts."""

from __future__ import annotations

import asyncio
import io
from functools import lru_cache

from minio import Minio

from app.core.config import get_settings


@lru_cache
def _client() -> Minio:
    """Return the process-local MinIO client."""
    settings = get_settings()
    return Minio(
        settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.minio_secure,
    )


def _bucket() -> str:
    return get_settings().minio_bucket


def _ensure_bucket_sync() -> None:
    client = _client()
    if not client.bucket_exists(_bucket()):
        client.make_bucket(_bucket())


def _put_sync(object_name: str, data: bytes, content_type: str) -> str:
    _ensure_bucket_sync()
    _client().put_object(
        _bucket(),
        object_name,
        io.BytesIO(data),
        length=len(data),
        content_type=content_type,
    )
    return f"{_bucket()}/{object_name}"


def _get_sync(object_name: str) -> bytes:
    response = _client().get_object(_bucket(), object_name)
    try:
        return response.read()
    finally:
        response.close()
        response.release_conn()


async def put_object(
    object_name: str,
    data: bytes,
    content_type: str = "application/octet-stream",
) -> str:
    """Store bytes and return the bucket-qualified storage path."""
    return await asyncio.to_thread(_put_sync, object_name, data, content_type)


async def get_object_bytes(object_name: str) -> bytes:
    """Read bytes by object key."""
    return await asyncio.to_thread(_get_sync, object_name)
