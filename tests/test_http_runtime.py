"""HTTP error adapters preserve the public response contract."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.bootstrap.error_wiring import register_application_error_handlers
from app.contexts.business.proposal_management import (
    ProposalError,
    ProposalNotApproved,
    ProposalNotFound,
)
from app.contexts.business.proposal_management.entrypoints import (
    register_proposal_error_handlers,
)
from app.contexts.shared_kernel import (
    ApplicationError,
    AuthenticationFailed,
    ConflictDetected,
    DependencyUnavailable,
    InvalidInput,
    PermissionDenied,
    ResourceNotFound,
    RuleViolation,
)
from app.main import app as production_app
from app.platform.http_runtime import register_exception_handlers


def _client() -> TestClient:
    app = FastAPI()
    register_exception_handlers(app)
    register_application_error_handlers(app)
    register_proposal_error_handlers(app)

    errors: dict[str, ApplicationError] = {
        "rule": RuleViolation("规则失败"),
        "input": InvalidInput("输入失败"),
        "auth": AuthenticationFailed("认证失败"),
        "permission": PermissionDenied("权限失败"),
        "missing": ResourceNotFound("资源不存在"),
        "conflict": ConflictDetected("状态冲突"),
        "dependency": DependencyUnavailable("依赖不可用"),
    }

    @app.get("/application/{kind}")
    async def application_error(kind: str) -> None:
        raise errors[kind]

    @app.get("/proposal/missing")
    async def proposal_missing() -> None:
        raise ProposalNotFound()

    @app.get("/proposal/not-approved")
    async def proposal_not_approved() -> None:
        raise ProposalNotApproved()

    return TestClient(app)


@pytest.mark.parametrize(
    ("kind", "status_code", "code", "message"),
    [
        ("rule", 400, 1, "规则失败"),
        ("input", 400, 400, "输入失败"),
        ("auth", 401, 401, "认证失败"),
        ("permission", 403, 403, "权限失败"),
        ("missing", 404, 404, "资源不存在"),
        ("conflict", 409, 409, "状态冲突"),
        ("dependency", 502, 502, "依赖不可用"),
    ],
)
def test_application_errors_preserve_existing_http_contract(
    kind: str,
    status_code: int,
    code: int,
    message: str,
) -> None:
    response = _client().get(f"/application/{kind}")
    assert response.status_code == status_code
    assert response.json() == {"code": code, "msg": message, "data": None}


def test_production_bootstrap_registers_proposal_error_handler() -> None:
    assert ApplicationError in production_app.exception_handlers
    assert ProposalError in production_app.exception_handlers


def test_proposal_not_found_maps_to_404_only_at_http_boundary() -> None:
    error = ProposalNotFound()
    assert not hasattr(error, "status_code")
    assert not hasattr(error, "code")

    response = _client().get("/proposal/missing")
    assert response.status_code == 404
    assert response.json() == {"code": 404, "msg": "提案不存在", "data": None}


def test_proposal_rule_violation_preserves_existing_400_envelope() -> None:
    response = _client().get("/proposal/not-approved")
    assert response.status_code == 400
    assert response.json() == {
        "code": 1,
        "msg": "仅『已通过』的提案可转任务卡（决议须真人确认）",
        "data": None,
    }
