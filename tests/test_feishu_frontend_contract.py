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
    assert "管理员预绑定本地账号" in source
    assert "暂无系统访问权限，请联系管理员完成账号预绑定" in source


def test_auth_guard_preserves_the_intended_same_origin_path() -> None:
    guard = (ROOT / "frontend/src/components/RequireAuth.tsx").read_text(encoding="utf-8")
    client = (ROOT / "frontend/src/api/client.ts").read_text(encoding="utf-8")
    paths = (ROOT / "frontend/src/auth/paths.ts").read_text(encoding="utf-8")
    assert "loginRedirectPath(location)" in guard
    assert "location.pathname" in client and "location.search" in client
    assert "return_to" in client
    assert "parsed.origin !== window.location.origin" in paths
    assert "decoded.startsWith('//')" in paths


def test_current_user_failure_is_not_rendered_as_an_ordinary_user() -> None:
    source = (ROOT / "frontend/src/layouts/AppLayout.tsx").read_text(encoding="utf-8")
    assert ".catch(() => {})" not in source
    assert "无法加载当前用户权限" in source
    assert "meError" in source
    assert "buildMenu(me.role_code === 'admin')" in source


def test_existing_prebound_user_role_can_be_explicitly_administered() -> None:
    source = (ROOT / "frontend/src/pages/Users.tsx").read_text(encoding="utf-8")
    assert "调整角色" in source
    assert "await updateUser(row.id, { role_code })" in source
    assert "未绑定身份不能登录，也不会自动开户" in source
