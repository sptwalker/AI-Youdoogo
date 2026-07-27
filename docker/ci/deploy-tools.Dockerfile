# Reusable CCE deployment toolchain. The SWR tag is immutable and is built
# only when this file changes; see build_deploy_tools in .gitlab-ci.yml.
FROM alpine:3.22.1

ARG KUBECTL_VERSION=v1.31.5
ARG KUBECTL_SHA256=fbecbfd375b3686002c2e81d51c390172f5ffba3d6b47920d55342cb03f557af

LABEL org.opencontainers.image.title="YOUDOOGO CCE deploy tools" \
      org.opencontainers.image.version="alpine3.22.1-kubectl1.31.5-r1"

RUN apk add --no-cache \
      bash \
      ca-certificates \
      curl \
      python3 \
      py3-yaml \
 && curl --fail --silent --show-error --location \
      --retry 5 --retry-delay 2 --retry-all-errors \
      --connect-timeout 15 --max-time 180 \
      --output /tmp/kubectl \
      "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/amd64/kubectl" \
 && printf '%s  %s\n' "$KUBECTL_SHA256" /tmp/kubectl | sha256sum -c - \
 && chmod 0755 /tmp/kubectl \
 && mv /tmp/kubectl /usr/local/bin/kubectl \
 && command -v bash \
 && command -v curl \
 && python3 -c 'import yaml; print(f"PyYAML {yaml.__version__}")' \
 && kubectl version --client=true

WORKDIR /workspace
