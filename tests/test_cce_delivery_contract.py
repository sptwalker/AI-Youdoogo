"""Offline contract tests for the first YOUDOOGO CCE delivery path."""

from __future__ import annotations

import importlib.util
import io
import json
import os
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
FULL_SHA = "a" * 40
IMAGE_TAG = f"ci-{FULL_SHA}"


def load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def rendered_objects(tmp_path: Path) -> list[dict]:
    env = os.environ | {
        "KUBE_NAMESPACE": "youdoogo-prod",
        "KUBE_IMAGE_PULL_SECRET": "swr-pull",
        "RUNTIME_SECRET_NAME": "youdoogo-runtime",
        "RUNTIME_CONFIGMAP_NAME": "youdoogo-runtime-config",
        "INGRESS_CLASS_NAME": "cce-public",
        "TLS_SECRET_NAME": "ai-youdoogo-com-tls",
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
    assert not any(
        "services" in config
        for config in pipeline.values()
        if isinstance(config, dict) and "script" in config
    )
    assert "m.daocloud.io/" in text
    assert "HIGH,CRITICAL" in text
    assert "${SWR_REGION}@${SWR_AK}" in text
    assert "ci-${CI_COMMIT_SHA}" in text

    for config in pipeline.values():
        if isinstance(config, dict) and isinstance(config.get("image"), dict):
            assert config["image"]["pull_policy"] == "always"
    deploy = pipeline["deploy_cce"]
    assert deploy["retry"] == 0
    assert deploy["resource_group"] == "youdoogo-cce-production"
    assert deploy["interruptible"] is False
    assert "sha256sum -c" in str(deploy["before_script"])


def test_manifests_are_host_safe_and_reference_only(tmp_path: Path) -> None:
    objects = rendered_objects(tmp_path)
    assert not {item["kind"] for item in objects} & {"Secret", "ConfigMap"}

    ingress = object_by(objects, "Ingress", "youdoogo")
    assert ingress["spec"]["ingressClassName"] == "cce-public"
    assert ingress["spec"]["tls"] == [
        {"hosts": ["ai.youdoogo.com"], "secretName": "ai-youdoogo-com-tls"}
    ]
    assert ingress["spec"]["rules"][0]["host"] == "ai.youdoogo.com"
    paths = ingress["spec"]["rules"][0]["http"]["paths"]
    assert paths == [
        {
            "path": "/",
            "pathType": "Prefix",
            "backend": {"service": {"name": "youdoogo-frontend", "port": {"number": 80}}},
        }
    ]
    assert "nexus" not in (ROOT / "ops/cce/runtime.yaml.tmpl").read_text().lower()


def test_backend_serve_and_probe_contract(tmp_path: Path) -> None:
    objects = rendered_objects(tmp_path)
    backend = object_by(objects, "Deployment", "youdoogo-backend")
    container = backend["spec"]["template"]["spec"]["containers"][0]
    assert container["args"] == ["serve"]
    assert container["image"].endswith(f":{IMAGE_TAG}")
    for probe_name in ("startupProbe", "readinessProbe", "livenessProbe"):
        assert container[probe_name]["httpGet"]["path"] == "/api/v1/health"
    assert "/api/v1/health/deps" not in str(backend)
    assert container["envFrom"] == [
        {"configMapRef": {"name": "youdoogo-runtime-config"}},
        {"secretRef": {"name": "youdoogo-runtime"}},
    ]

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


def test_frontend_same_origin_proxy_and_spa() -> None:
    nginx = (ROOT / "docker/nginx/nginx.conf").read_text(encoding="utf-8")
    assert "location /api/" in nginx
    assert "proxy_pass http://${BACKEND_HOST}:${BACKEND_PORT};" in nginx
    assert "try_files $uri $uri/ /index.html;" in nginx
    client = (ROOT / "frontend/src/api/client.ts").read_text(encoding="utf-8")
    assert "baseURL: '/api/v1'" in client


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
        "TLS_SECRET_NAME",
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
        "TLS_SECRET_NAME": "ai-youdoogo-com-tls",
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
