#!/usr/bin/env bash
set -Eeuo pipefail

INGRESS_NAME="youdoogo"
BACKEND_DEPLOYMENT="youdoogo-backend"
FRONTEND_DEPLOYMENT="youdoogo-frontend"

required=(
  KUBE_NAMESPACE KUBE_IMAGE_PULL_SECRET RUNTIME_SECRET_NAME RUNTIME_CONFIGMAP_NAME
  INGRESS_CLASS_NAME PUBLIC_HOST IMAGE_TAG BACKEND_IMAGE FRONTEND_IMAGE
)
for name in "${required[@]}"; do
  if [[ -z "${!name:-}" ]]; then
    echo "ERROR: required environment variable ${name} is missing" >&2
    exit 1
  fi
done

for command in kubectl python3 curl; do
  if ! command -v "$command" >/dev/null 2>&1; then
    echo "ERROR: ${command} is required" >&2
    exit 1
  fi
done

render_dir="$(mktemp -d)"
trap 'rm -rf "$render_dir"' EXIT
python3 scripts/ci/render_cce.py --output-dir "$render_dir"
runtime_manifest="$render_dir/runtime.yaml"
workloads_manifest="$render_dir/workloads.yaml"
ingress_manifest="$render_dir/ingress.yaml"
migration_manifest="$render_dir/migration-job.yaml"
python3 - "$runtime_manifest" "$workloads_manifest" "$ingress_manifest" <<'PY'
from pathlib import Path
import sys
import yaml

source, workloads_path, ingress_path = map(Path, sys.argv[1:])
documents = [doc for doc in yaml.safe_load_all(source.read_text(encoding="utf-8")) if doc]
workloads = [doc for doc in documents if doc.get("kind") in {"Service", "Deployment"}]
ingresses = [doc for doc in documents if doc.get("kind") == "Ingress"]
if len(workloads) != 4 or len(ingresses) != 1:
    raise SystemExit("ERROR: runtime template must contain four workloads and one Ingress")
workloads_path.write_text(yaml.safe_dump_all(workloads, sort_keys=False), encoding="utf-8")
ingress_path.write_text(yaml.safe_dump_all(ingresses, sort_keys=False), encoding="utf-8")
PY
migration_job="youdoogo-migrate-${IMAGE_TAG}"

print_object_events() {
  local kind="$1" name="$2" uid
  uid="$(kubectl get "$kind" "$name" -n "$KUBE_NAMESPACE" -o jsonpath='{.metadata.uid}' 2>/dev/null || true)"
  [[ -z "$uid" ]] && return
  echo "[diagnostic] events for ${kind}/${name}" >&2
  kubectl get events -n "$KUBE_NAMESPACE" \
    --field-selector "involvedObject.uid=${uid}" --sort-by=.metadata.creationTimestamp >&2 || true
}

print_rollout_diagnostics() {
  local deployment="$1" selector rs_inventory pod_inventory
  selector="app.kubernetes.io/name=${deployment}"

  echo "[diagnostic] deployment/${deployment} status" >&2
  kubectl get deployment "$deployment" -n "$KUBE_NAMESPACE" \
    -o 'custom-columns=NAME:.metadata.name,GENERATION:.metadata.generation,OBSERVED:.status.observedGeneration,DESIRED:.spec.replicas,UPDATED:.status.updatedReplicas,READY:.status.readyReplicas,AVAILABLE:.status.availableReplicas,UNAVAILABLE:.status.unavailableReplicas,CONDITIONS:.status.conditions[*].type,REASONS:.status.conditions[*].reason' \
    >&2 || true

  echo "[diagnostic] ReplicaSets for deployment/${deployment}" >&2
  kubectl get replicasets -n "$KUBE_NAMESPACE" -l "$selector" \
    -o 'custom-columns=NAME:.metadata.name,DESIRED:.spec.replicas,CURRENT:.status.replicas,READY:.status.readyReplicas,AVAILABLE:.status.availableReplicas' \
    >&2 || true

  echo "[diagnostic] Pods for deployment/${deployment}" >&2
  kubectl get pods -n "$KUBE_NAMESPACE" -l "$selector" \
    -o 'custom-columns=NAME:.metadata.name,PHASE:.status.phase,READY:.status.containerStatuses[*].ready,WAITING:.status.containerStatuses[*].state.waiting.reason,CONDITION_REASONS:.status.conditions[*].reason,RESTARTS:.status.containerStatuses[*].restartCount,NODE:.spec.nodeName' \
    >&2 || true

  print_object_events deployment "$deployment"
  rs_inventory="$(kubectl get replicasets -n "$KUBE_NAMESPACE" -l "$selector" \
    -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}' 2>/dev/null || true)"
  while IFS= read -r replica_set; do
    [[ -z "$replica_set" ]] && continue
    print_object_events replicaset "$replica_set"
  done <<<"$rs_inventory"
  pod_inventory="$(kubectl get pods -n "$KUBE_NAMESPACE" -l "$selector" \
    -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}' 2>/dev/null || true)"
  while IFS= read -r pod; do
    [[ -z "$pod" ]] && continue
    print_object_events pod "$pod"
  done <<<"$pod_inventory"
}

wait_for_deployment_rollout() {
  local deployment="$1" status
  if kubectl rollout status "deployment/${deployment}" -n "$KUBE_NAMESPACE" --timeout=5m; then
    return 0
  else
    status=$?
  fi
  echo "ERROR: deployment/${deployment} rollout did not complete" >&2
  print_rollout_diagnostics "$deployment"
  return "$status"
}

echo "[preflight] checking namespace and referenced objects"
kubectl get namespace "$KUBE_NAMESPACE" >/dev/null

pull_secret_type="$(kubectl get secret "$KUBE_IMAGE_PULL_SECRET" -n "$KUBE_NAMESPACE" -o jsonpath='{.type}')"
if [[ "$pull_secret_type" != "kubernetes.io/dockerconfigjson" && "$pull_secret_type" != "kubernetes.io/dockercfg" ]]; then
  echo "ERROR: ${KUBE_IMAGE_PULL_SECRET} is not a Docker registry pull Secret" >&2
  exit 1
fi

kubectl get secret "$RUNTIME_SECRET_NAME" -n "$KUBE_NAMESPACE" >/dev/null
kubectl get configmap "$RUNTIME_CONFIGMAP_NAME" -n "$KUBE_NAMESPACE" >/dev/null

for key in DATABASE_URL REDIS_URL MINIO_ACCESS_KEY MINIO_SECRET_KEY JWT_SECRET; do
  present="$(kubectl get secret "$RUNTIME_SECRET_NAME" -n "$KUBE_NAMESPACE" -o go-template="{{if index .data \"${key}\"}}present{{end}}")"
  if [[ "$present" != "present" ]]; then
    echo "ERROR: runtime Secret ${RUNTIME_SECRET_NAME} lacks required key ${key}" >&2
    exit 1
  fi
done

for key in APP_ENV LOG_LEVEL MINIO_ENDPOINT MINIO_BUCKET; do
  present="$(kubectl get configmap "$RUNTIME_CONFIGMAP_NAME" -n "$KUBE_NAMESPACE" -o go-template="{{if index .data \"${key}\"}}present{{end}}")"
  if [[ "$present" != "present" ]]; then
    echo "ERROR: runtime ConfigMap ${RUNTIME_CONFIGMAP_NAME} lacks required key ${key}" >&2
    exit 1
  fi
done
for key in APP_ENV LOG_LEVEL MINIO_ENDPOINT MINIO_BUCKET; do
  present="$(kubectl get secret "$RUNTIME_SECRET_NAME" -n "$KUBE_NAMESPACE" -o go-template="{{if index .data \"${key}\"}}present{{end}}")"
  if [[ "$present" == "present" ]]; then
    echo "ERROR: runtime Secret must not override ConfigMap key ${key}" >&2
    exit 1
  fi
done

production_env="$(kubectl get configmap "$RUNTIME_CONFIGMAP_NAME" -n "$KUBE_NAMESPACE" -o go-template='{{if eq (index .data "APP_ENV") "production"}}production{{end}}')"
if [[ "$production_env" != "production" ]]; then
  echo "ERROR: runtime ConfigMap APP_ENV must be production" >&2
  exit 1
fi

# CCE uses the verified ELB certificate-ID annotation; no Kubernetes TLS Secret
# or IngressClass object is required for the `cce` controller path.

echo "[preflight] checking for conflicting host ownership"
ingress_inventory="$(kubectl get ingress --all-namespaces -o jsonpath='{range .items[*]}{.metadata.namespace}{"\t"}{.metadata.name}{"\t"}{range .spec.rules[*]}{.host}{" "}{end}{"\n"}{end}')"
while IFS=$'\t' read -r namespace name hosts; do
  [[ -z "$namespace" ]] && continue
  for host in $hosts; do
    if [[ "$host" == "$PUBLIC_HOST" && ( "$namespace" != "$KUBE_NAMESPACE" || "$name" != "$INGRESS_NAME" ) ]]; then
      echo "ERROR: ${PUBLIC_HOST} is already owned by Ingress ${namespace}/${name}" >&2
      exit 1
    fi
  done
done <<<"$ingress_inventory"

if kubectl get ingress "$INGRESS_NAME" -n "$KUBE_NAMESPACE" >/dev/null 2>&1; then
  existing_class="$(kubectl get ingress "$INGRESS_NAME" -n "$KUBE_NAMESPACE" -o jsonpath='{.spec.ingressClassName}')"
  if [[ "$existing_class" != "$INGRESS_CLASS_NAME" ]]; then
    echo "ERROR: existing project Ingress class differs from required input" >&2
    exit 1
  fi
fi

for check in \
  "create jobs.batch" "create services" "create deployments.apps" "create ingresses.networking.k8s.io" \
  "patch jobs.batch" "patch services" "patch deployments.apps" "patch ingresses.networking.k8s.io" \
  "delete jobs.batch"; do
  verb="${check%% *}"
  resource="${check#* }"
  if [[ "$(kubectl auth can-i "$verb" "$resource" -n "$KUBE_NAMESPACE")" != "yes" ]]; then
    echo "ERROR: kubeconfig cannot ${verb} ${resource} in ${KUBE_NAMESPACE}" >&2
    exit 1
  fi
done

public_status="$(curl --silent --show-error --head --output /dev/null \
  --proto '=https' --tlsv1.2 \
  --connect-timeout 10 --max-time 20 --write-out '%{http_code}' \
  "https://${PUBLIC_HOST}/")"
if [[ "$public_status" == "000" ]]; then
  echo "ERROR: ${PUBLIC_HOST} did not complete a trusted HTTPS handshake" >&2
  exit 1
fi

kubectl apply --dry-run=server -f "$migration_manifest" >/dev/null
kubectl apply --dry-run=server -f "$workloads_manifest" >/dev/null
# Validate the Ingress only after its referenced Services have been created;
# CCE admission rejects an otherwise valid first-release Ingress before then.

echo "[migrate] reclaiming terminal YOUDOOGO migration Pods before creating a new Job"
while IFS= read -r prior_job; do
  [[ -z "$prior_job" || "$prior_job" == "$migration_job" ]] && continue
  prior_active="$(kubectl get job "$prior_job" -n "$KUBE_NAMESPACE" -o jsonpath='{.status.active}')"
  prior_succeeded="$(kubectl get job "$prior_job" -n "$KUBE_NAMESPACE" -o jsonpath='{.status.succeeded}')"
  prior_failed="$(kubectl get job "$prior_job" -n "$KUBE_NAMESPACE" -o jsonpath='{.status.failed}')"
  if [[ -z "$prior_active" && ( "$prior_succeeded" == "1" || ( -n "$prior_failed" && "$prior_failed" != "0" ) ) ]]; then
    kubectl delete job "$prior_job" -n "$KUBE_NAMESPACE" --wait=true
  fi
done < <(kubectl get jobs -n "$KUBE_NAMESPACE" \
  -l app.kubernetes.io/name=youdoogo-migration,app.kubernetes.io/part-of=youdoogo \
  -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}')

echo "[migrate] reserving one YOUDOOGO backend slot for the bounded migration Job"
current_backend_replicas="$(kubectl get deployment "$BACKEND_DEPLOYMENT" -n "$KUBE_NAMESPACE" -o jsonpath='{.spec.replicas}')"
if [[ "$current_backend_replicas" =~ ^[2-9][0-9]*$ ]]; then
  # This cluster is at its pod limit. Keep one serving backend replica while
  # temporarily freeing exactly one project-owned pod slot for migration.
  kubectl scale deployment "$BACKEND_DEPLOYMENT" -n "$KUBE_NAMESPACE" --replicas=1
  wait_for_deployment_rollout "$BACKEND_DEPLOYMENT"
fi

echo "[migrate] ensuring exactly one bounded Job for ${IMAGE_TAG}"
if kubectl get job "$migration_job" -n "$KUBE_NAMESPACE" >/dev/null 2>&1; then
  succeeded="$(kubectl get job "$migration_job" -n "$KUBE_NAMESPACE" -o jsonpath='{.status.succeeded}')"
  if [[ "$succeeded" != "1" ]]; then
    echo "ERROR: migration Job already exists without success; it will not be retried automatically" >&2
    exit 1
  fi
  echo "[migrate] existing successful Job retained"
else
  kubectl apply -f "$migration_manifest"
  for _ in $(seq 1 120); do
    succeeded="$(kubectl get job "$migration_job" -n "$KUBE_NAMESPACE" -o jsonpath='{.status.succeeded}')"
    failed="$(kubectl get job "$migration_job" -n "$KUBE_NAMESPACE" -o jsonpath='{.status.failed}')"
    if [[ "$succeeded" == "1" ]]; then
      break
    fi
    if [[ -n "$failed" && "$failed" != "0" ]]; then
      echo "ERROR: migration Job failed and backoffLimit is zero" >&2
      exit 1
    fi
    sleep 5
  done
  succeeded="$(kubectl get job "$migration_job" -n "$KUBE_NAMESPACE" -o jsonpath='{.status.succeeded}')"
  if [[ "$succeeded" != "1" ]]; then
    echo "ERROR: migration Job did not complete within 10 minutes" >&2
    exit 1
  fi
fi

echo "[deploy] applying project-owned Services and Deployments"
kubectl apply -f "$workloads_manifest"
wait_for_deployment_rollout "$BACKEND_DEPLOYMENT"
wait_for_deployment_rollout "$FRONTEND_DEPLOYMENT"

echo "[deploy] applying project-owned Ingress after its Services exist"
kubectl apply --dry-run=server -f "$ingress_manifest" >/dev/null
kubectl apply -f "$ingress_manifest"

verify_deployment_image() {
  local deployment="$1" container="$2" expected="$3" actual version
  actual="$(kubectl get deployment "$deployment" -n "$KUBE_NAMESPACE" -o jsonpath="{.spec.template.spec.containers[?(@.name=='${container}')].image}")"
  if [[ "$actual" != "$expected" ]]; then
    echo "ERROR: deployment/${deployment} uses ${actual}, expected ${expected}" >&2
    exit 1
  fi
  version="$(kubectl get deployment "$deployment" -n "$KUBE_NAMESPACE" -o jsonpath="{.spec.template.metadata.labels.app\.kubernetes\.io/version}")"
  if [[ -z "$version" ]]; then
    echo "ERROR: deployment/${deployment} has no version label" >&2
    exit 1
  fi
  mapfile -t pod_images < <(
    kubectl get pods -n "$KUBE_NAMESPACE" \
      -l "app.kubernetes.io/name=${deployment},app.kubernetes.io/version=${version}" \
      --field-selector=status.phase=Running \
      -o jsonpath="{range .items[*]}{.spec.containers[?(@.name=='${container}')].image}{\"\\n\"}{end}"
  )
  if [[ "${#pod_images[@]}" -eq 0 ]]; then
    echo "ERROR: deployment/${deployment} has no pods" >&2
    exit 1
  fi
  for pod_image in "${pod_images[@]}"; do
    if [[ "$pod_image" != "$expected" ]]; then
      echo "ERROR: a ${deployment} pod is not using the immutable expected image" >&2
      exit 1
    fi
  done
}

verify_deployment_image "$BACKEND_DEPLOYMENT" backend "$BACKEND_IMAGE"
verify_deployment_image "$FRONTEND_DEPLOYMENT" frontend "$FRONTEND_IMAGE"

scripts/ci/smoke-youdoogo.sh
