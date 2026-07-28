"""Object storage retains old behavior while adding opt-in TLS and presigned URLs."""

from datetime import timedelta
from typing import Any

import pytest

from app.core.config import Settings
from app.platform.object_storage import gateway


class _FakeMinio:
    def __init__(self, *args: object, **kwargs: object) -> None:
        self.args = args
        self.kwargs = kwargs
        self.presign_calls: list[tuple[str, str, str, timedelta]] = []

    def presigned_get_object(
        self,
        bucket: str,
        object_name: str,
        *,
        expires: timedelta,
    ) -> str:
        self.presign_calls.append(("get", bucket, object_name, expires))
        return "https://storage.example/get"

    def presigned_put_object(
        self,
        bucket: str,
        object_name: str,
        *,
        expires: timedelta,
    ) -> str:
        self.presign_calls.append(("put", bucket, object_name, expires))
        return "https://storage.example/put"


def _settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "minio_endpoint": "storage.internal:9000",
        "minio_access_key": "test-access",
        "minio_secret_key": "test-secret",
        "minio_bucket": "youdoo",
        "_env_file": None,
    }
    values.update(overrides)
    return Settings(**values)


def test_client_secure_flag_is_configurable_without_changing_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: list[_FakeMinio] = []

    def construct(*args: object, **kwargs: object) -> _FakeMinio:
        client = _FakeMinio(*args, **kwargs)
        created.append(client)
        return client

    monkeypatch.setattr(gateway, "Minio", construct)
    monkeypatch.setattr(gateway, "get_settings", lambda: _settings(minio_secure=True))
    gateway._client.cache_clear()
    try:
        gateway._client()
    finally:
        gateway._client.cache_clear()

    assert created[0].args == ("storage.internal:9000",)
    assert created[0].kwargs["secure"] is True
    assert Settings(_env_file=None).minio_secure is False  # type: ignore[call-arg]


def test_bucket_and_segment_prefix_allowlist(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        gateway,
        "get_settings",
        lambda: _settings(
            minio_allowed_buckets="youdoo,archive",
            minio_allowed_prefixes="deliverables, knowledge/private/",
        ),
    )

    gateway.validate_object_access("deliverables/report.pdf")
    gateway.validate_object_access("knowledge/private/doc.txt", bucket_name="archive")
    with pytest.raises(gateway.ObjectStorageAccessDenied, match="bucket"):
        gateway.validate_object_access("deliverables/report.pdf", bucket_name="other")
    with pytest.raises(gateway.ObjectStorageAccessDenied, match="prefix"):
        gateway.validate_object_access("deliverables-private/report.pdf")
    with pytest.raises(gateway.ObjectStorageAccessDenied, match="unsafe path segment"):
        gateway.validate_object_access("deliverables/../private/report.pdf")
    with pytest.raises(gateway.ObjectStorageAccessDenied, match="canonical path"):
        gateway.validate_object_access("/deliverables/report.pdf")


def test_empty_allowlists_preserve_current_single_bucket_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(gateway, "get_settings", lambda: _settings())
    gateway.validate_object_access("any/existing/object-key")
    with pytest.raises(gateway.ObjectStorageAccessDenied):
        gateway.validate_object_access("any/existing/object-key", bucket_name="other")


@pytest.mark.asyncio
async def test_presigned_get_and_put_use_explicit_or_configured_expiry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _FakeMinio()
    monkeypatch.setattr(
        gateway,
        "get_settings",
        lambda: _settings(
            minio_allowed_prefixes="deliverables",
            minio_presign_expire_seconds=600,
        ),
    )
    monkeypatch.setattr(gateway, "_client", lambda: client)

    get_url = await gateway.presign_get_object("deliverables/report.pdf")
    put_url = await gateway.presign_put_object(
        "deliverables/upload.pdf",
        expires_seconds=120,
    )

    assert get_url.endswith("/get")
    assert put_url.endswith("/put")
    assert client.presign_calls == [
        ("get", "youdoo", "deliverables/report.pdf", timedelta(seconds=600)),
        ("put", "youdoo", "deliverables/upload.pdf", timedelta(seconds=120)),
    ]


@pytest.mark.asyncio
async def test_presigned_url_rejects_out_of_grant_and_invalid_expiry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        gateway,
        "get_settings",
        lambda: _settings(minio_allowed_prefixes="deliverables"),
    )
    monkeypatch.setattr(gateway, "_client", lambda: _FakeMinio())

    with pytest.raises(gateway.ObjectStorageAccessDenied):
        await gateway.presign_get_object("knowledge/doc.txt")
    with pytest.raises(ValueError, match="expiry"):
        await gateway.presign_put_object("deliverables/doc.txt", expires_seconds=0)
