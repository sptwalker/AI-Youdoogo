"""Offline frontend contract checks for the Feishu login entry and callback UX."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_login_keeps_default_password_submit_and_separate_feishu_entry() -> None:
    source = (ROOT / "frontend/src/pages/Login.tsx").read_text(encoding="utf-8")
    assert "fetchFeishuStatus()" in source
    assert "exchangeFeishuLogin()" in source
    assert "startFeishuLogin(returnTo)" in source
    assert "submitButtonProps" in source
    assert source.index("</LoginForm>") < source.index('className="feishu-login-button"')
    assert "localStorage.setItem(TOKEN_KEY, token.access_token)" in source
    assert "normalizeAppPath(token.redirect_to)" in source


def test_auth_guard_preserves_the_intended_same_origin_path() -> None:
    guard = (ROOT / "frontend/src/components/RequireAuth.tsx").read_text(encoding="utf-8")
    paths = (ROOT / "frontend/src/auth/paths.ts").read_text(encoding="utf-8")
    assert "location.pathname" in guard and "location.search" in guard
    assert "return_to" in guard
    assert "parsed.origin !== window.location.origin" in paths
    assert "decoded.startsWith('//')" in paths
