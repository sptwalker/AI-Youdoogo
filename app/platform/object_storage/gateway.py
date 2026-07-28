"""MinIO-backed object-storage mechanism shared by bounded contexts."""

from __future__ import annotations

import asyncio
import io
from datetime import timedelta
from functools import lru_cache

from minio import Minio

from app.core.config import get_settings


class ObjectStorageAccessDenied(PermissionError):
    """The configured bucket/prefix allowlist rejects an object target."""


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


def _allowlist(raw_value: str) -> tuple[str, ...]:
    return tuple(value.strip() for value in raw_value.split(",") if value.strip())


def _validate_path_segments(value: str, *, field: str) -> str:
    """Reject ambiguous object paths before they reach HTTP proxies or MinIO."""
    if not value or value.startswith(("/", "\\")) or "\\" in value:
        raise ObjectStorageAccessDenied(f"{field} must be a relative canonical path")
    segments = value.split("/")
    if any(segment in {"", ".", ".."} for segment in segments):
        raise ObjectStorageAccessDenied(f"{field} contains an unsafe path segment")
    return value


def _validate_bucket_access(bucket_name: str) -> None:
    settings = get_settings()
    allowed_buckets = _allowlist(settings.minio_allowed_buckets) or (settings.minio_bucket,)
    if bucket_name not in allowed_buckets:
        raise ObjectStorageAccessDenied(f"bucket is outside configured grant: {bucket_name}")


def validate_object_access(object_name: str, *, bucket_name: str | None = None) -> None:
    """Fail closed when a target exceeds the configured bucket/prefix grant.

    Empty allowlists preserve the old single-bucket behavior. Once prefixes are set,
    each entry protects a complete path segment (``reports`` grants ``reports/...`` but
    not ``reports-private/...``).
    """
    settings = get_settings()
    resolved_bucket = bucket_name or settings.minio_bucket
    _validate_bucket_access(resolved_bucket)
    _validate_path_segments(object_name, field="object key")

    allowed_prefixes = _allowlist(settings.minio_allowed_prefixes)
    if not allowed_prefixes:
        return
    for allowed_prefix in allowed_prefixes:
        normalized_prefix = allowed_prefix.rstrip("/")
        _validate_path_segments(normalized_prefix, field="configured prefix")
        if object_name == normalized_prefix or object_name.startswith(f"{normalized_prefix}/"):
            return
    raise ObjectStorageAccessDenied("object key is outside configured prefix grant")


def _ensure_bucket_sync() -> None:
    _validate_bucket_access(_bucket())
    client = _client()
    if not client.bucket_exists(_bucket()):
        client.make_bucket(_bucket())


def _put_sync(object_name: str, data: bytes, content_type: str) -> str:
    validate_object_access(object_name)
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
    validate_object_access(object_name)
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


def _presign_expiry(expires_seconds: int | None) -> timedelta:
    resolved = (
        get_settings().minio_presign_expire_seconds
        if expires_seconds is None
        else expires_seconds
    )
    if resolved < 1 or resolved > 604_800:
        raise ValueError("presigned URL expiry must be between 1 and 604800 seconds")
    return timedelta(seconds=resolved)


def _presign_get_sync(object_name: str, expires_seconds: int | None) -> str:
    validate_object_access(object_name)
    return _client().presigned_get_object(
        _bucket(),
        object_name,
        expires=_presign_expiry(expires_seconds),
    )


def _presign_put_sync(object_name: str, expires_seconds: int | None) -> str:
    validate_object_access(object_name)
    return _client().presigned_put_object(
        _bucket(),
        object_name,
        expires=_presign_expiry(expires_seconds),
    )


async def presign_get_object(
    object_name: str,
    *,
    expires_seconds: int | None = None,
) -> str:
    """Create a time-limited GET URL without changing current download behavior."""
    return await asyncio.to_thread(_presign_get_sync, object_name, expires_seconds)


async def presign_put_object(
    object_name: str,
    *,
    expires_seconds: int | None = None,
) -> str:
    """Create a time-limited PUT URL without changing current upload behavior."""
    return await asyncio.to_thread(_presign_put_sync, object_name, expires_seconds)
