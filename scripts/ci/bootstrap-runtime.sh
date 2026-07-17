#!/usr/bin/env bash
# Bootstrap YOUDOOGO-owned stateful dependencies. Secrets are generated only on
# first creation, passed by stdin to kubectl, and never written to disk or stdout.
set -Eeuo pipefail

namespace="${KUBE_NAMESPACE:-nexus-prod}"
secret_name="${RUNTIME_SECRET_NAME:-youdoogo-runtime}"
config_name="${RUNTIME_CONFIGMAP_NAME:-youdoogo-runtime-config}"
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
template="$root/ops/cce/dependencies.yaml.tmpl"

for command in kubectl python3 openssl; do
  command -v "$command" >/dev/null || { echo "ERROR: $command is required" >&2; exit 1; }
done
[[ -f "$template" ]] || { echo "ERROR: dependency template is missing" >&2; exit 1; }
kubectl get namespace "$namespace" >/dev/null

if kubectl get secret "$secret_name" -n "$namespace" >/dev/null 2>&1; then
  for key in DATABASE_URL REDIS_URL MINIO_ACCESS_KEY MINIO_SECRET_KEY JWT_SECRET POSTGRES_PASSWORD; do
    kubectl get secret "$secret_name" -n "$namespace" -o go-template="{{if index .data \"${key}\"}}present{{end}}" | grep -qx present || {
      echo "ERROR: existing runtime Secret lacks $key; refusing to rotate or overwrite" >&2
      exit 1
    }
  done
  echo "[bootstrap] existing runtime Secret accepted without reading values"
else
  export BOOTSTRAP_POSTGRES_PASSWORD="$(openssl rand -hex 32)"
  export BOOTSTRAP_MINIO_ACCESS_KEY="youdoogo$(openssl rand -hex 8)"
  export BOOTSTRAP_MINIO_SECRET_KEY="$(openssl rand -hex 32)"
  export BOOTSTRAP_JWT_SECRET="$(openssl rand -hex 48)"
  export BOOTSTRAP_DATABASE_URL="postgresql+asyncpg://youdoogo:${BOOTSTRAP_POSTGRES_PASSWORD}@youdoogo-postgres:5432/youdoogo"
  export BOOTSTRAP_REDIS_URL="redis://youdoogo-redis:6379/0"
  export BOOTSTRAP_NAMESPACE="$namespace" BOOTSTRAP_SECRET_NAME="$secret_name"
  python3 - <<'PY' | kubectl apply --dry-run=server -f - >/dev/null
import base64
import json
import os

keys = {
    "POSTGRES_PASSWORD": os.environ["BOOTSTRAP_POSTGRES_PASSWORD"],
    "DATABASE_URL": os.environ["BOOTSTRAP_DATABASE_URL"],
    "REDIS_URL": os.environ["BOOTSTRAP_REDIS_URL"],
    "MINIO_ACCESS_KEY": os.environ["BOOTSTRAP_MINIO_ACCESS_KEY"],
    "MINIO_SECRET_KEY": os.environ["BOOTSTRAP_MINIO_SECRET_KEY"],
    "JWT_SECRET": os.environ["BOOTSTRAP_JWT_SECRET"],
}
payload = {
    "apiVersion": "v1", "kind": "Secret",
    "metadata": {"name": os.environ["BOOTSTRAP_SECRET_NAME"], "namespace": os.environ["BOOTSTRAP_NAMESPACE"]},
    "type": "Opaque",
    "data": {key: base64.b64encode(value.encode()).decode() for key, value in keys.items()},
}
print(json.dumps(payload))
PY
  python3 - <<'PY' | kubectl apply -f - >/dev/null
import base64
import json
import os

keys = {
    "POSTGRES_PASSWORD": os.environ["BOOTSTRAP_POSTGRES_PASSWORD"],
    "DATABASE_URL": os.environ["BOOTSTRAP_DATABASE_URL"],
    "REDIS_URL": os.environ["BOOTSTRAP_REDIS_URL"],
    "MINIO_ACCESS_KEY": os.environ["BOOTSTRAP_MINIO_ACCESS_KEY"],
    "MINIO_SECRET_KEY": os.environ["BOOTSTRAP_MINIO_SECRET_KEY"],
    "JWT_SECRET": os.environ["BOOTSTRAP_JWT_SECRET"],
}
payload = {
    "apiVersion": "v1", "kind": "Secret",
    "metadata": {"name": os.environ["BOOTSTRAP_SECRET_NAME"], "namespace": os.environ["BOOTSTRAP_NAMESPACE"]},
    "type": "Opaque",
    "data": {key: base64.b64encode(value.encode()).decode() for key, value in keys.items()},
}
print(json.dumps(payload))
PY
  unset BOOTSTRAP_POSTGRES_PASSWORD BOOTSTRAP_MINIO_ACCESS_KEY BOOTSTRAP_MINIO_SECRET_KEY BOOTSTRAP_JWT_SECRET BOOTSTRAP_DATABASE_URL BOOTSTRAP_REDIS_URL BOOTSTRAP_NAMESPACE BOOTSTRAP_SECRET_NAME
  echo "[bootstrap] generated and created runtime Secret"
fi

rendered="$(mktemp)"
trap 'rm -f "$rendered"' EXIT
python3 - "$template" "$rendered" "$namespace" <<'PY'
from pathlib import Path
import sys

source = Path(sys.argv[1])
target = Path(sys.argv[2])
namespace = sys.argv[3]
content = source.read_text(encoding="utf-8").replace("__NAMESPACE__", namespace)
if "__NAMESPACE__" in content:
    raise SystemExit("unresolved placeholder")
target.write_text(content, encoding="utf-8")
PY
kubectl apply --dry-run=server -f "$rendered" >/dev/null
kubectl apply -f "$rendered" >/dev/null
for statefulset in youdoogo-postgres youdoogo-redis youdoogo-minio; do
  kubectl rollout status "statefulset/${statefulset}" -n "$namespace" --timeout=10m
done
for key in APP_ENV LOG_LEVEL MINIO_ENDPOINT MINIO_BUCKET; do
  kubectl get configmap "$config_name" -n "$namespace" -o go-template="{{if index .data \"${key}\"}}present{{end}}" | grep -qx present
done
echo "[bootstrap] dedicated YOUDOOGO dependencies are ready"
