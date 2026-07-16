# YOUDOOGO CCE first-release preflight

This repository contains no production values and the pipeline never creates Kubernetes
Secrets or ConfigMaps. The protected `dev` branch is the only delivery ref because GitLab
currently has no approved `main`; merge-request pipelines verify only. A platform owner must
complete every item below before the first delivery pipeline can pass.

## `ai` group CI/CD variable contract

Create these as protected variables at the GitLab `ai` group so the protected `dev` branch can
use them. Do not enter examples, placeholders, test credentials, or guessed object names.

### Platform-owner supplied, masked values

| Variable | Category | Required meaning |
|---|---|---|
| `KUBECONFIG_CCE_B64` | masked + protected credential | Base64-encoded least-privilege kubeconfig for the target CCE cluster. |
| `SWR_AK` | masked + protected credential | Huawei Cloud SWR access key identifier approved for these repositories. |
| `SWR_PASSWORD` | masked + protected secret | SWR login password/secret paired with `SWR_AK`. |
| `FEISHU_APP_ID` | masked + protected group credential | Existing organization-standard Feishu application ID used by the CI notification job only. |
| `FEISHU_APP_SECRET` | masked + protected group credential | Secret for that Feishu application, used by the CI notification job only. |

The SWR username is formed only in CI as `SWR_REGION@SWR_AK`. The notification uses the Feishu
application API with `receive_id_type=chat_id`. Its destination is the shared, fixed organization
chat already used by sibling delivery pipelines; that nonsecret target is a code constant, not an
`ai` group variable. There is no repository webhook or project-specific target configuration.
These group credentials are not copied into the backend Deployment and do not enable application
login.

### Platform-approved nonsecret configuration

These names are safe to store unmasked after a platform owner supplies the real, verified value.
They are still protected because they select production infrastructure.

| Variable | Required meaning |
|---|---|
| `SWR_REGION` | Established Huawei Cloud SWR region. The current sibling standard is `cn-south-1`; confirm it applies to this CCE cluster before creating the variable. |
| `SWR_REGISTRY_OVERRIDE` | Full approved SWR registry namespace/repository root without a URL scheme. No default is assumed because the `ai` project repository ownership is not proven. |
| `KUBE_NAMESPACE` | Existing namespace dedicated or approved for YOUDOOGO workloads. |
| `KUBE_IMAGE_PULL_SECRET` | Existing Docker registry pull Secret name in `KUBE_NAMESPACE`. |
| `INGRESS_CLASS_NAME` | Existing IngressClass whose controller publishes host rules through the ELB serving `ai.youdoogo.com`. |
| `TLS_SECRET_NAME` | Existing `kubernetes.io/tls` Secret in `KUBE_NAMESPACE`, owned by the platform/certificate process and valid for `ai.youdoogo.com`. |
| `RUNTIME_SECRET_NAME` | Existing application runtime Secret in `KUBE_NAMESPACE`. |
| `RUNTIME_CONFIGMAP_NAME` | Existing application runtime ConfigMap in `KUBE_NAMESPACE`. |

All 13 names are checked by `preflight_delivery` before either image is built. The deployment
script validates Kubernetes object existence, type, required keys, host ownership, server-side
dry runs, and RBAC before mutating a workload.

## Required pre-existing CCE and SWR state

- `KUBE_NAMESPACE` already exists. CI is not allowed to create it.
- `KUBE_IMAGE_PULL_SECRET` already exists and is type `kubernetes.io/dockerconfigjson` or
  `kubernetes.io/dockercfg`; both immutable commit images are pullable from it.
- `RUNTIME_SECRET_NAME` already exists with nonempty keys `DATABASE_URL`, `REDIS_URL`,
  `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY`, and `JWT_SECRET`. Their values, dependency hosts, and
  credentials are owned outside this repository and must not be copied into GitLab logs.
- `RUNTIME_CONFIGMAP_NAME` already exists with keys `APP_ENV`, `LOG_LEVEL`, `MINIO_ENDPOINT`, and
  `MINIO_BUCKET`; `APP_ENV` must equal `production`. Optional application variables may be added
  to the same references by the runtime owner. The runtime Secret must not duplicate these four
  keys, so it cannot silently override the validated nonsecret configuration.
- Feishu OAuth login is optional and remains disabled for first release unless separately approved.
  Enabling it requires `FEISHU_APP_ID` and `FEISHU_APP_SECRET` in the referenced runtime Secret,
  plus `FEISHU_OAUTH_ENABLED=true` and the exact
  `FEISHU_REDIRECT_URL=https://ai.youdoogo.com/api/v1/auth/feishu/callback` in the referenced
  runtime ConfigMap (or the documented administrator runtime-config flow). The same callback must
  first be registered manually in Feishu Open Platform and users must be pre-bound by app-scoped
  `open_id`; the pipeline does not perform or claim those actions.
- `TLS_SECRET_NAME` already contains nonempty `tls.crt` and `tls.key` entries and its certificate
  covers `ai.youdoogo.com`. CI never creates or renews certificates.
- `INGRESS_CLASS_NAME` already exists and its controller is configured to use the ELB reached by
  public DNS. If that CCE controller requires ELB-specific annotations or an ELB ID, the platform
  owner must first establish an approved IngressClass/controller policy; this repository does not
  guess Huawei annotations or an ELB identifier.
- No other Ingress in the cluster owns `ai.youdoogo.com`. A pre-existing
  `KUBE_NAMESPACE/youdoogo` Ingress is accepted only when its class and TLS Secret already match.
- Public DNS ownership remains with the platform team: `ai.youdoogo.com` must resolve only to the
  intended ELB. The current ELB 404 is not delivery success; the pipeline must complete and both
  HTTPS smoke probes must pass.
- The kubeconfig can get/list the referenced objects and cluster Ingress inventory, perform
  server-side dry runs, and create/patch/get Jobs, Services, Deployments, and Ingresses in the
  namespace. It does not need permission to create Secrets or ConfigMaps.
- The approved SWR namespace contains or permits creation/push of `youdoogo-backend` and
  `youdoogo-frontend`, and the CCE pull Secret can read them.

## Release behavior and ownership

The pipeline pushes only immutable `ci-$CI_COMMIT_SHA` tags. It scans both images for HIGH and
CRITICAL vulnerabilities before deployment. A commit-scoped migration Job has
`backoffLimit: 0` and a ten-minute deadline. An existing failed/incomplete Job is never deleted or
retried by CI; a platform/application owner must diagnose it and explicitly decide how to recover.

The project-owned Ingress contains the single host `ai.youdoogo.com` and sends `/` traffic to the
frontend. Frontend Nginx serves the SPA and proxies `/api/` to the private backend Service. No
`nexus` ConfigMap, `nginx-extra-locations`, path key, or shared Nexus route is read or changed.

Before enabling the first release, confirm the selected Ingress controller also permits this
application's 50 MiB request bodies and 120-second upstream operations through an approved
controller policy. Before enabling Feishu OAuth, the ELB/Ingress access-log policy must also avoid
recording callback query strings for `/api/v1/auth/feishu/callback`; frontend Nginx and Uvicorn
already suppress them at their own layers. No controller-specific annotation is included without
cluster evidence.
