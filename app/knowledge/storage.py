"""MinIO 对象存储封装（同步 SDK 用 to_thread 包成异步）。

知识库原始文件落 MinIO，storage_path 记 "bucket/object" 供溯源与二次解析。
"""

from __future__ import annotations

import asyncio
import io
from functools import lru_cache

from minio import Minio

from app.core.config import get_settings


@lru_cache
def _client() -> Minio:
    """进程级单例客户端（endpoint 不含 scheme；本地默认非 TLS）。"""
    s = get_settings()
    return Minio(
        s.minio_endpoint,
        access_key=s.minio_access_key,
        secret_key=s.minio_secret_key,
        secure=False,
    )


def _bucket() -> str:
    return get_settings().minio_bucket


def _ensure_bucket_sync() -> None:
    c = _client()
    if not c.bucket_exists(_bucket()):
        c.make_bucket(_bucket())


def _put_sync(object_name: str, data: bytes, content_type: str) -> str:
    _ensure_bucket_sync()
    _client().put_object(
        _bucket(), object_name, io.BytesIO(data), length=len(data), content_type=content_type
    )
    return f"{_bucket()}/{object_name}"


def _get_sync(object_name: str) -> bytes:
    resp = _client().get_object(_bucket(), object_name)
    try:
        return resp.read()
    finally:
        resp.close()
        resp.release_conn()


async def put_object(
    object_name: str, data: bytes, content_type: str = "application/octet-stream"
) -> str:
    """存对象，返回 storage_path（bucket/object）。"""
    return await asyncio.to_thread(_put_sync, object_name, data, content_type)


async def get_object_bytes(object_name: str) -> bytes:
    """按 object key 读回字节。"""
    return await asyncio.to_thread(_get_sync, object_name)
