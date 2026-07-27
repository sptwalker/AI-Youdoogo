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
| `INGRESS_CLASS_NAME` | Existing CCE controller class used by the approved shared ELB listener (`cce`). |
| `RUNTIME_SECRET_NAME` | Existing application runtime Secret in `KUBE_NAMESPACE`; first-release bootstrap creates it once. |
| `RUNTIME_CONFIGMAP_NAME` | Existing application runtime ConfigMap in `KUBE_NAMESPACE`; first-release bootstrap creates it. |

The 12 existing delivery variables are checked by `preflight_delivery` before either application
image is built. The deploy-tools image reuses the existing `SWR_REGION`, `SWR_AK`,
`SWR_PASSWORD`, and `SWR_REGISTRY_OVERRIDE` configuration; no additional registry variable or
second copy of the SWR credential is required. The deployment script validates Kubernetes object
existence, type, required keys, host ownership, server-side dry runs, and RBAC before mutating a
workload.

## Deploy-tools image bootstrap and release

The deploy job uses the immutable SWR tag
`youdoogo-deploy-tools:alpine3.22.1-kubectl1.31.5-r1`. Its Dockerfile pins Alpine 3.22.1 and
kubectl v1.31.5, verifies the kubectl binary with the repository's approved SHA256, and installs
bash, CA certificates, curl, Python 3, and PyYAML once at image-build time.

Before merging the first change, the platform owner must confirm that the approved SWR namespace
permits push and pull of `youdoogo-deploy-tools`. The first dev push containing
`docker/ci/deploy-tools.Dockerfile` runs `build_deploy_tools` in the `bootstrap` stage. That job
uses the existing SWR login/buildx flow to publish the fixed tag before `deploy_cce` is eligible to
start, so the rollout does not assume a pre-existing tool image.

The build job serializes publication with a dedicated resource group and never overwrites the
remote tag. On a retry, it pulls the existing image and verifies the OCI version label, required
commands, PyYAML import, kubectl client, and approved kubectl SHA256 before succeeding. For a real
toolchain change, update the Dockerfile, its OCI version label, and `.gitlab-ci.yml`'s
`DEPLOY_TOOLS_TAG` together; never reuse a published tag. If an unchanged tag is accidentally
removed from SWR, run the optional `bootstrap_deploy_tools` job from a dev delivery pipeline to
rebuild it. Platform policy should also deny tag overwrite for this repository where SWR supports
it.

## Required pre-existing CCE and SWR state

### Shared CCE ELB listener binding

The project Ingress carries the user-managed ELB class, ELB ID, listener ports, listener-master
Ingress, and TLS certificate-ID annotations verified from working independent-host CCE Ingresses
on the same production controller. This binds `ai.youdoogo.com` to the existing HTTPS listener;
without it CCE leaves the host unregistered and the ELB returns its own 404.

These annotations are operational metadata, not application configuration. If ownership of the
shared ELB or listener changes, obtain the replacement values from the listener owner, update the
template and delivery contract together, and review the change before delivery. Do not copy
controller-generated status annotations, another host's routing rules, DNS ownership, or
certificate material.

- The first-release operator runs `KUBE_NAMESPACE=nexus-prod RUNTIME_SECRET_NAME=youdoogo-runtime`
  `RUNTIME_CONFIGMAP_NAME=youdoogo-runtime-config bash scripts/ci/bootstrap-runtime.sh` with a
  production kubeconfig before enabling CI. It creates only YOUDOOGO-owned Postgres, Redis, MinIO,
  `csi-disk` PVCs, ConfigMap, and a one-time generated runtime Secret; it never reads, reuses, or
  overwrites another application's credentials.
- `KUBE_IMAGE_PULL_SECRET` already exists and is type `kubernetes.io/dockerconfigjson` or
  `kubernetes.io/dockercfg`; both immutable commit images are pullable from it.
- `RUNTIME_SECRET_NAME` is generated once by `scripts/ci/bootstrap-runtime.sh`; it contains nonempty
  keys `DATABASE_URL`, `REDIS_URL`, `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY`, `JWT_SECRET`, and the
  private database bootstrap password. The script refuses to overwrite an existing Secret and never
  prints values. These credentials are not stored in GitLab variables.
- `RUNTIME_CONFIGMAP_NAME` is created by the same bootstrap with `APP_ENV=production`, `LOG_LEVEL`,
  `MINIO_ENDPOINT`, and `MINIO_BUCKET`. The runtime Secret must not duplicate these four keys, so it
  cannot silently override validated nonsecret configuration.
- Feishu OAuth login is optional and remains disabled for first release unless separately approved.
  Enabling it requires `FEISHU_APP_ID` and `FEISHU_APP_SECRET` in the referenced runtime Secret,
  plus `FEISHU_OAUTH_ENABLED=true` and the exact
  `FEISHU_REDIRECT_URL=https://ai.youdoogo.com/api/v1/auth/feishu/callback` in the referenced
  runtime ConfigMap (or the documented administrator runtime-config flow). The same callback must
  first be registered manually in Feishu Open Platform and users must be pre-bound by app-scoped
  `open_id`; the pipeline does not perform or claim those actions.
- HTTPS is supplied by the shared ELB's verified `kubernetes.io/elb.tls-certificate-ids` annotation;
  no `kubernetes.io/tls` Secret is created, mounted, or required by this project.
- `INGRESS_CLASS_NAME` is the existing `cce` controller path backed by that ELB. The controller has
  no cluster `IngressClass` object, so CI validates the rendered Ingress class and shared ELB
  annotations instead of requiring a nonexistent object.
- No other Ingress in the cluster owns `ai.youdoogo.com`. A pre-existing
  `KUBE_NAMESPACE/youdoogo` Ingress is accepted only when its class matches the approved input.
- Public DNS ownership remains with the platform team: `ai.youdoogo.com` must resolve only to the
  intended ELB. The current ELB 404 is not delivery success; the pipeline must complete and both
  HTTPS smoke probes must pass.
- The kubeconfig can get/list the referenced objects and cluster Ingress inventory, perform
  server-side dry runs, and create/patch/get Jobs, Services, Deployments, and Ingresses in the
  namespace. It does not need permission to create Secrets or ConfigMaps.
- The approved SWR namespace contains or permits creation/push of `youdoogo-backend`,
  `youdoogo-frontend`, and `youdoogo-deploy-tools`. GitLab Runner can pull the deploy-tools image
  with the protected SWR variables, and the CCE pull Secret can read both application images.

## Release behavior and ownership

The pipeline pushes application images only as immutable `ci-$CI_COMMIT_SHA` tags and publishes
the deployment toolchain under its separately versioned immutable tag. It scans both application
images for HIGH and CRITICAL vulnerabilities before deployment. A commit-scoped migration Job has
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
