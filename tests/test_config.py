"""配置校验：非 local 环境拒绝弱 JWT 密钥。"""

import pytest

from app.contexts.foundations.identity import browser_login as feishu_login
from app.core.config import Settings
from app.integrations.feishu.oauth import FeishuOAuthConfig


def test_prod_rejects_default_secret() -> None:
    with pytest.raises(ValueError, match="JWT_SECRET"):
        Settings(
            app_env="production",
            jwt_secret="local-only-jwt-secret-change-in-production",
            _env_file=None,
        )


def test_prod_rejects_short_secret() -> None:
    with pytest.raises(ValueError, match="JWT_SECRET"):
        Settings(app_env="production", jwt_secret="tooshort", _env_file=None)


def test_prod_accepts_strong_secret() -> None:
    s = Settings(app_env="production", jwt_secret="x" * 40, _env_file=None)
    assert s.app_env == "production"


def test_local_allows_default() -> None:
    s = Settings(
        app_env="local",
        jwt_secret="local-only-jwt-secret-change-in-production",
        _env_file=None,
    )
    assert s.jwt_secret == "local-only-jwt-secret-change-in-production"


def test_production_oauth_requires_https_callback_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = feishu_login.get_settings()
    monkeypatch.setattr(settings, "app_env", "production")
    values: dict[str, object] = {
        "feishu_oauth_enabled": True,
        "feishu_app_id": "cli_test_app",
        "feishu_app_secret": "test-secret-not-real",
        "feishu_redirect_url": "https://app.example.test/api/v1/auth/feishu/callback",
    }
    monkeypatch.setattr(
        feishu_login.runtime_config,
        "effective",
        lambda key, default="": values.get(key, default),
    )
    config = feishu_login.load_oauth_config()
    assert isinstance(config, FeishuOAuthConfig)
    assert config.redirect_url == values["feishu_redirect_url"]

    values["feishu_redirect_url"] = "https://app.example.test/lodge/feishu-callback"
    with pytest.raises(feishu_login.OAuthUnavailable):
        feishu_login.load_oauth_config()

    values["feishu_redirect_url"] = "http://app.example.test/api/v1/auth/feishu/callback"
    with pytest.raises(feishu_login.OAuthUnavailable):
        feishu_login.load_oauth_config()


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("feishu_app_id", " cli_test_app"),
        ("feishu_app_secret", "secret\nvalue"),
        ("feishu_redirect_url", "http://localhost:bad/api/v1/auth/feishu/callback"),
        ("feishu_redirect_url", "https://[invalid/api/v1/auth/feishu/callback"),
    ],
)
def test_local_oauth_rejects_malformed_credentials_and_redirect(
    monkeypatch: pytest.MonkeyPatch, key: str, value: str
) -> None:
    settings = feishu_login.get_settings()
    monkeypatch.setattr(settings, "app_env", "local")
    values: dict[str, object] = {
        "feishu_oauth_enabled": True,
        "feishu_app_id": "cli_test_app",
        "feishu_app_secret": "test-secret-not-real",
        "feishu_redirect_url": "http://localhost:8000/api/v1/auth/feishu/callback",
    }
    values[key] = value
    monkeypatch.setattr(
        feishu_login.runtime_config,
        "effective",
        lambda config_key, default="": values.get(config_key, default),
    )
    with pytest.raises(feishu_login.OAuthUnavailable):
        feishu_login.load_oauth_config()
