"""Offline contract tests for the first YOUDOOGO CCE delivery path."""

from __future__ import annotations

import importlib.util
import io
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
FULL_SHA = "a" * 40
IMAGE_TAG = f"ci-{FULL_SHA}"
pytestmark = pytest.mark.delivery_contract


def required_command(name: str) -> str:
    """Resolve a required delivery binary without silently skipping validation."""
    command = shutil.which(name)
    assert command is not None, (
        f"{name} is required by the verify_delivery_contract test environment"
    )
    return command


def load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def rendered_objects(tmp_path: Path) -> list[dict]:
    env = os.environ | {
        "KUBE_NAMESPACE": "youdoogo-prod",
        "KUBE_IMAGE_PULL_SECRET": "swr-pull",
        "RUNTIME_SECRET_NAME": "youdoogo-runtime",
        "RUNTIME_CONFIGMAP_NAME": "youdoogo-runtime-config",
        "INGRESS_CLASS_NAME": "cce-public",
        "IMAGE_TAG": IMAGE_TAG,
        "BACKEND_IMAGE": f"swr.example.com/approved/youdoogo-backend:{IMAGE_TAG}",
        "FRONTEND_IMAGE": f"swr.example.com/approved/youdoogo-frontend:{IMAGE_TAG}",
    }
    subprocess.run(
        ["python3", "scripts/ci/render_cce.py", "--output-dir", str(tmp_path)],
        cwd=ROOT,
        env=env,
        check=True,
    )
    objects: list[dict] = []
    for path in (tmp_path / "runtime.yaml", tmp_path / "migration-job.yaml"):
        objects.extend(document for document in yaml.safe_load_all(path.read_text()) if document)
    return objects


def object_by(objects: list[dict], kind: str, name: str) -> dict:
    return next(
        item
        for item in objects
        if item["kind"] == kind and item["metadata"]["name"] == name
    )


def test_gitlab_pipeline_policy_and_mechanics() -> None:
    pipeline = load_yaml(ROOT / ".gitlab-ci.yml")
    assert pipeline["stages"] == ["verify", "build", "scan", "deploy", "notify"]
    assert pipeline["default"]["tags"] == ["AI"]
    assert "dev" in str(pipeline["workflow"]["rules"])
    assert "merge_request_event" in str(pipeline["workflow"]["rules"])
    rule_conditions = [
        rule.get("if", "")
        for config in pipeline.values()
        if isinstance(config, dict)
        for rule in config.get("rules", [])
    ]
    assert not any('CI_COMMIT_BRANCH == "main"' in condition for condition in rule_conditions)

    text = (ROOT / ".gitlab-ci.yml").read_text(encoding="utf-8")
    assert "docker.sock" in text
    assert "docker:dind" not in text.lower()
    assert "privileged:" not in text.lower()
    service_jobs = {
        name
        for name, config in pipeline.items()
        if isinstance(config, dict) and "script" in config and "services" in config
    }
    assert service_jobs == {"verify_backend"}
    assert "name: m.daocloud.io/" not in text
    assert "TRIVY_DB_REPOSITORY: m.daocloud.io/" in text
    assert "HIGH,CRITICAL" in text
    assert "node:20-alpine" in text
    assert "${SWR_REGION}@${SWR_AK}" in text
    assert "ci-${CI_COMMIT_SHA}" in text

    backend_verify = pipeline["verify_backend"]
    assert backend_verify["services"] == [
        {"name": "redis:7-alpine", "alias": "redis", "pull_policy": "always"}
    ]
    assert backend_verify["variables"]["REDIS_URL"] == "redis://redis:6379/0"
    assert not any(
        config.get("variables", {}).get("REDIS_URL")
        for name, config in pipeline.items()
        if name != "verify_backend" and isinstance(config, dict)
    )
    assert "uv sync --frozen" in backend_verify["before_script"]
    for command in ("ruff check .", "mypy app"):
        assert f"uv run --frozen {command}" in backend_verify["script"]
    assert (
        'uv run --frozen pytest -q -m "not delivery_contract" '
        "--cov=app --cov-report=term-missing:skip-covered"
        in backend_verify["script"]
    )
    delivery_verify = pipeline["verify_delivery_contract"]
    assert "apk add --no-cache bash gettext nginx" in delivery_verify["before_script"]
    assert "command -v envsubst" in delivery_verify["before_script"]
    assert "command -v nginx" in delivery_verify["before_script"]
    assert (
        "python -m pytest -q -m delivery_contract tests/test_cce_delivery_contract.py"
        in delivery_verify["script"]
    )

    for config in pipeline.values():
        if isinstance(config, dict) and isinstance(config.get("image"), dict):
            assert config["image"]["pull_policy"] == "always"
    deploy = pipeline["deploy_cce"]
    assert deploy["retry"] == 0
    assert deploy["resource_group"] == "youdoogo-cce-production"
    assert deploy["interruptible"] is False
    assert "sha256sum -c" in str(deploy["before_script"])

    deploy_script = (ROOT / "scripts/ci/deploy-cce.sh").read_text(encoding="utf-8")
    assert "workloads_manifest" in deploy_script
    assert "ingress_manifest" in deploy_script
    assert 'kubectl apply -f "$workloads_manifest"' in deploy_script
    assert 'kubectl apply -f "$ingress_manifest"' in deploy_script
    assert 'kubectl delete job "$prior_job" -n "$KUBE_NAMESPACE" --wait=true' in deploy_script
    expected_scale = (
        'kubectl scale deployment "$BACKEND_DEPLOYMENT" '
        '-n "$KUBE_NAMESPACE" --replicas=1'
    )
    assert expected_scale in deploy_script
    assert deploy_script.index(
        'kubectl scale deployment "$BACKEND_DEPLOYMENT"'
    ) < deploy_script.index(
        'kubectl apply -f "$migration_manifest"'
    )
    assert '"delete pods"' not in deploy_script
    assert 'kubectl delete pods' not in deploy_script
    assert 'print_rollout_diagnostics()' in deploy_script
    diagnostics = deploy_script[
        deploy_script.index("print_object_events()") : deploy_script.index(
            "wait_for_deployment_rollout()"
        )
    ]
    for status_command in (
        "kubectl get deployment",
        "kubectl get replicasets",
        "kubectl get pods",
    ):
        assert status_command in diagnostics
    assert "custom-columns=" in diagnostics
    assert 'involvedObject.uid=${uid}' in diagnostics
    assert "kubectl describe" not in diagnostics
    assert deploy_script.count(
        'wait_for_deployment_rollout "$BACKEND_DEPLOYMENT"'
    ) == 2
    assert 'wait_for_deployment_rollout "$FRONTEND_DEPLOYMENT"' in deploy_script
    assert deploy_script.index('kubectl apply -f "$workloads_manifest"') < deploy_script.index(
        'kubectl apply -f "$ingress_manifest"'
    )


def test_manifests_are_host_safe_and_reference_only(tmp_path: Path) -> None:
    objects = rendered_objects(tmp_path)
    assert not {item["kind"] for item in objects} & {"Secret", "ConfigMap"}

    ingress = object_by(objects, "Ingress", "youdoogo")
    assert ingress["metadata"]["annotations"] == {
        "kubernetes.io/elb.class": "performance",
        "kubernetes.io/elb.id": "abab7533-a1c6-4138-a4bc-59d53e3446e2",
        "kubernetes.io/elb.listen-ports": '[{"HTTP":80},{"HTTPS":443}]',
        "kubernetes.io/elb.listener-master-ingress": "nexus-prod/nexus-studio",
        "kubernetes.io/elb.tls-certificate-ids": "56de20421757445ea53f5af51ecb4e10",
    }
    assert ingress["spec"]["ingressClassName"] == "cce-public"
    assert "tls" not in ingress["spec"]
    assert ingress["spec"]["rules"][0]["host"] == "ai.youdoogo.com"
    paths = ingress["spec"]["rules"][0]["http"]["paths"]
    assert paths == [
        {
            "path": "/",
            "pathType": "Prefix",
            "backend": {"service": {"name": "youdoogo-frontend", "port": {"number": 80}}},
        }
    ]
    runtime_template = (ROOT / "ops/cce/runtime.yaml.tmpl").read_text().lower()
    assert "nexus.youdoogo.com" not in runtime_template

    preflight = (ROOT / "ops/first-release-preflight.md").read_text(encoding="utf-8")
    for required_evidence in (
        "Shared CCE ELB listener binding",
        "working independent-host CCE Ingresses",
        "existing HTTPS listener",
        "listener-master",
        "controller-generated status annotations",
    ):
        assert required_evidence in preflight


def test_backend_serve_and_probe_contract(tmp_path: Path) -> None:
    objects = rendered_objects(tmp_path)
    backend = object_by(objects, "Deployment", "youdoogo-backend")
    container = backend["spec"]["template"]["spec"]["containers"][0]
    assert container["args"] == ["serve"]
    assert container["image"].endswith(f":{IMAGE_TAG}")
    for probe_name in ("startupProbe", "readinessProbe", "livenessProbe"):
        assert container[probe_name]["httpGet"]["path"] == "/api/v1/health"
    assert container["envFrom"] == [
        {"configMapRef": {"name": "youdoogo-runtime-config"}},
        {"secretRef": {"name": "youdoogo-runtime"}},
    ]
    assert backend["spec"]["strategy"]["rollingUpdate"] == {
        "maxUnavailable": 1,
        "maxSurge": 0,
    }
    frontend = object_by(objects, "Deployment", "youdoogo-frontend")
    assert frontend["spec"]["strategy"]["rollingUpdate"] == {
        "maxUnavailable": 1,
        "maxSurge": 0,
    }

    entrypoint = (ROOT / "docker/entrypoint.sh").read_text(encoding="utf-8")
    assert "migrate)" in entrypoint
    assert "serve)" in entrypoint
    assert '""' in entrypoint


def test_migration_job_is_once_only_and_bounded(tmp_path: Path) -> None:
    objects = rendered_objects(tmp_path)
    job = object_by(objects, "Job", f"youdoogo-migrate-{IMAGE_TAG}")
    assert job["spec"]["backoffLimit"] == 0
    assert job["spec"]["activeDeadlineSeconds"] == 600
    assert job["spec"]["template"]["spec"]["restartPolicy"] == "Never"
    container = job["spec"]["template"]["spec"]["containers"][0]
    assert container["args"] == ["migrate"]


def test_deploy_image_verification_ignores_terminating_rollout_pods() -> None:
    deploy = (ROOT / "scripts/ci/deploy-cce.sh").read_text(encoding="utf-8")
    assert "--field-selector=status.phase=Running" in deploy
    assert ".items[?(@.metadata.deletionTimestamp==null)]" in deploy
    assert "deployment/${deployment} uses ${actual}, expected ${expected}" in deploy


def test_frontend_same_origin_proxy_and_spa() -> None:
    nginx = (ROOT / "docker/nginx/nginx.conf").read_text(encoding="utf-8")
    dockerfile = (ROOT / "frontend/Dockerfile").read_text(encoding="utf-8")
    assert (
        "COPY docker/nginx/nginx.conf /etc/nginx/templates/default.conf.template"
        in dockerfile
    )
    assert "location /api/" in nginx
    assert "proxy_pass http://${BACKEND_HOST}:${BACKEND_PORT};" in nginx
    assert "location = /nginx-health" in nginx
    assert "try_files $uri $uri/ /index.html;" in nginx
    callback = nginx.split(
        "location = /api/v1/auth/feishu/callback {", maxsplit=1
    )[1].split("\n    }", maxsplit=1)[0]
    assert "access_log off;" in callback
    assert "proxy_pass http://${BACKEND_HOST}:${BACKEND_PORT};" in callback
    assert "proxy_set_header X-Forwarded-Proto $upstream_forwarded_proto;" in callback
    client = (ROOT / "frontend/src/api/client.ts").read_text(encoding="utf-8")
    assert "baseURL: '/api/v1'" in client


def test_frontend_build_avoids_fragile_custom_vendor_chunks() -> None:
    vite_config = (ROOT / "frontend/vite.config.ts").read_text(encoding="utf-8")
    for custom_split_marker in (
        "rolldownOptions",
        "codeSplitting",
        "antd-date-picker",
        "ant-design-pro",
    ):
        assert custom_split_marker not in vite_config


def test_frontend_nginx_template_renders_and_validates(tmp_path: Path) -> None:
    envsubst = required_command("envsubst")
    nginx = required_command("nginx")
    template = (ROOT / "docker/nginx/nginx.conf").read_text(encoding="utf-8")
    rendered = subprocess.run(
        [envsubst, "${BACKEND_HOST} ${BACKEND_PORT}"],
        input=template,
        text=True,
        capture_output=True,
        check=True,
        env=os.environ | {"BACKEND_HOST": "127.0.0.1", "BACKEND_PORT": "8000"},
    ).stdout
    rendered_path = tmp_path / "default.conf"
    rendered_path.write_text(rendered, encoding="utf-8")
    nginx_config = tmp_path / "nginx.conf"
    nginx_config.write_text(
        "\n".join(
            (
                "error_log stderr notice;",
                f"pid {tmp_path / 'nginx.pid'};",
                "events {}",
                "http {",
                "    access_log off;",
                f"    include {rendered_path};",
                "}",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    subprocess.run(
        [nginx, "-t", "-p", f"{tmp_path}/", "-c", str(nginx_config)],
        text=True,
        capture_output=True,
        check=True,
    )


def test_variable_contract_and_notification_card(monkeypatch) -> None:
    docs = (ROOT / "ops/first-release-preflight.md").read_text(encoding="utf-8")
    required = (
        "KUBECONFIG_CCE_B64",
        "SWR_REGION",
        "SWR_REGISTRY_OVERRIDE",
        "SWR_AK",
        "SWR_PASSWORD",
        "FEISHU_APP_ID",
        "FEISHU_APP_SECRET",
        "KUBE_NAMESPACE",
        "KUBE_IMAGE_PULL_SECRET",
        "INGRESS_CLASS_NAME",
        "RUNTIME_SECRET_NAME",
        "RUNTIME_CONFIGMAP_NAME",
    )
    for variable in required:
        assert f"`{variable}`" in docs

    preflight_spec = importlib.util.spec_from_file_location(
        "preflight_vars", ROOT / "scripts/ci/preflight_vars.py"
    )
    assert preflight_spec and preflight_spec.loader
    preflight_module = importlib.util.module_from_spec(preflight_spec)
    preflight_spec.loader.exec_module(preflight_module)
    assert preflight_module.REQUIRED == required

    notification_env = {
        "CI_PIPELINE_ID": "42",
        "CI_PIPELINE_URL": "https://gitlab.example.com/ai/youdoogo/-/pipelines/42",
        "CI_COMMIT_BRANCH": "dev",
        "CI_COMMIT_SHORT_SHA": "1234abcd",
        "CI_COMMIT_TITLE": "Correct notification contract",
        "GITLAB_USER_NAME": "Delivery Owner",
    }
    for name, value in notification_env.items():
        monkeypatch.setenv(name, value)

    spec = importlib.util.spec_from_file_location("notify", ROOT / "scripts/ci/notify.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    payload = module.card("success")
    title = payload["header"]["title"]["content"]
    content = payload["elements"][0]["content"]
    assert title == "✅ YOUDOOGO 流水线成功 #42"
    lines = content.splitlines()
    assert [line.split("：", 1)[0] for line in lines] == [
        "**流水线**",
        "**分支**",
        "**提交**",
        "**触发者**",
        "**完成时间**",
        "**地址**",
    ]
    assert lines[-1] == "**地址**：[YOUDOOGO](https://ai.youdoogo.com/)"

    canonical_chat_id = "oc_aae2fdb8d29cc64e86efa7ce6c0e60da"
    assert module.CHAT_ID == canonical_chat_id
    requests = []

    def fake_urlopen(request, timeout):
        requests.append((request, timeout))
        body = {"tenant_access_token": "test-token"} if len(requests) == 1 else {"code": 0}
        return io.BytesIO(json.dumps(body).encode())

    monkeypatch.setenv("FEISHU_APP_ID", "test-app-id")
    monkeypatch.setenv("FEISHU_APP_SECRET", "test-app-secret")
    monkeypatch.setattr(module.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(module.sys, "argv", ["notify.py", "success"])
    assert module.main() == 0
    assert len(requests) == 2
    message_payload = json.loads(requests[1][0].data.decode())
    assert message_payload["receive_id"] == canonical_chat_id
    assert message_payload["msg_type"] == "interactive"


def test_preflight_validates_without_printing_values() -> None:
    env = os.environ | {
        "KUBECONFIG_CCE_B64": "YXBpVmVyc2lvbjogdjEK",
        "SWR_REGION": "cn-south-1",
        "SWR_REGISTRY_OVERRIDE": "swr.example.com/approved",
        "SWR_AK": "dummy-ak",
        "SWR_PASSWORD": "dummy-password",
        "FEISHU_APP_ID": "dummy-app-id",
        "FEISHU_APP_SECRET": "dummy-app-secret",
        "KUBE_NAMESPACE": "youdoogo-prod",
        "KUBE_IMAGE_PULL_SECRET": "swr-pull",
        "INGRESS_CLASS_NAME": "cce-public",
        "RUNTIME_SECRET_NAME": "youdoogo-runtime",
        "RUNTIME_CONFIGMAP_NAME": "youdoogo-runtime-config",
    }
    valid = subprocess.run(
        ["python3", "scripts/ci/preflight_vars.py"],
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert valid.returncode == 0, valid.stderr + valid.stdout
    assert "dummy-" not in valid.stdout

    env["KUBECONFIG_CCE_B64"] = "not base64"
    invalid = subprocess.run(
        ["python3", "scripts/ci/preflight_vars.py"],
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert invalid.returncode == 1
    assert "KUBECONFIG_CCE_B64" in invalid.stdout
