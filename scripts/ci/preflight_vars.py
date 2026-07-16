#!/usr/bin/env python3
"""Fail closed when the protected dev delivery contract is incomplete."""

from __future__ import annotations

import base64
import binascii
import os
import re

REQUIRED = (
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
DNS_LABEL = re.compile(r"^[a-z0-9](?:[-a-z0-9]*[a-z0-9])?$")
DNS_SUBDOMAIN = re.compile(r"^[a-z0-9](?:[-a-z0-9.]*[a-z0-9])?$")
SWR_PATH = re.compile(r"^[a-z0-9.-]+(?::[0-9]+)?/[a-z0-9._/-]+$")


def main() -> int:
    missing = [name for name in REQUIRED if not os.environ.get(name)]
    if missing:
        print("ERROR: required ai group CI/CD variables are missing:")
        for name in missing:
            print(f"- {name}")
        return 1

    errors: list[str] = []
    namespace = os.environ["KUBE_NAMESPACE"]
    if len(namespace) > 63 or not DNS_LABEL.fullmatch(namespace):
        errors.append("KUBE_NAMESPACE is not a Kubernetes DNS label")
    for name in (
        "KUBE_IMAGE_PULL_SECRET",
        "INGRESS_CLASS_NAME",
        "TLS_SECRET_NAME",
        "RUNTIME_SECRET_NAME",
        "RUNTIME_CONFIGMAP_NAME",
    ):
        value = os.environ[name]
        if len(value) > 253 or not DNS_SUBDOMAIN.fullmatch(value):
            errors.append(f"{name} is not a Kubernetes DNS name")
    if not DNS_LABEL.fullmatch(os.environ["SWR_REGION"]):
        errors.append("SWR_REGION has invalid characters")
    registry = os.environ["SWR_REGISTRY_OVERRIDE"].rstrip("/")
    if not SWR_PATH.fullmatch(registry):
        errors.append("SWR_REGISTRY_OVERRIDE must be a registry namespace without a URL scheme")
    try:
        if not base64.b64decode(os.environ["KUBECONFIG_CCE_B64"], validate=True):
            errors.append("KUBECONFIG_CCE_B64 decodes to empty content")
    except (binascii.Error, ValueError):
        errors.append("KUBECONFIG_CCE_B64 is not valid base64")
    if errors:
        print("ERROR: nonsecret delivery configuration is invalid:")
        for error in errors:
            print(f"- {error}")
        return 1
    print("Delivery variable contract is present (values were not printed).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
