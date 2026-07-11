"""配置校验：非 local 环境拒绝弱 JWT 密钥。"""

import pytest

from app.core.config import Settings


def test_prod_rejects_default_secret() -> None:
    with pytest.raises(ValueError, match="JWT_SECRET"):
        Settings(app_env="production", jwt_secret="change-me-in-phase-1", _env_file=None)


def test_prod_rejects_short_secret() -> None:
    with pytest.raises(ValueError, match="JWT_SECRET"):
        Settings(app_env="production", jwt_secret="tooshort", _env_file=None)


def test_prod_accepts_strong_secret() -> None:
    s = Settings(app_env="production", jwt_secret="x" * 40, _env_file=None)
    assert s.app_env == "production"


def test_local_allows_default() -> None:
    s = Settings(app_env="local", jwt_secret="change-me-in-phase-1", _env_file=None)
    assert s.jwt_secret == "change-me-in-phase-1"
