#!/usr/bin/env python3
"""Render project-owned CCE templates from non-secret CI configuration."""

from __future__ import annotations

import argparse
import os
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
TEMPLATES = {
    "runtime.yaml.tmpl": "runtime.yaml",
    "migration-job.yaml.tmpl": "migration-job.yaml",
}
DNS_LABEL = re.compile(r"^[a-z0-9](?:[-a-z0-9]*[a-z0-9])?$")
DNS_SUBDOMAIN = re.compile(r"^[a-z0-9](?:[-a-z0-9.]*[a-z0-9])?$")
IMAGE = re.compile(r"^[A-Za-z0-9._:/-]+$")


def required(name: str) -> str:
    """Read a required non-secret renderer input."""
    value = os.environ.get(name, "")
    if not value:
        raise SystemExit(f"ERROR: required environment variable {name} is missing")
    if any(char in value for char in ("\n", "\r", "\x00")):
        raise SystemExit(f"ERROR: {name} contains an invalid control character")
    return value


def validate_name(name: str, value: str, *, subdomain: bool = True) -> None:
    """Validate a Kubernetes DNS label/subdomain before template substitution."""
    pattern = DNS_SUBDOMAIN if subdomain else DNS_LABEL
    maximum = 253 if subdomain else 63
    if len(value) > maximum or not pattern.fullmatch(value):
        raise SystemExit(f"ERROR: {name} is not a valid Kubernetes DNS name")


def inputs() -> dict[str, str]:
    """Return validated placeholder values without accepting arbitrary YAML fragments."""
    namespace = required("KUBE_NAMESPACE")
    image_pull_secret = required("KUBE_IMAGE_PULL_SECRET")
    runtime_secret = required("RUNTIME_SECRET_NAME")
    runtime_configmap = required("RUNTIME_CONFIGMAP_NAME")
    ingress_class = required("INGRESS_CLASS_NAME")
    tls_secret = required("TLS_SECRET_NAME")
    image_tag = required("IMAGE_TAG")
    backend_image = required("BACKEND_IMAGE")
    frontend_image = required("FRONTEND_IMAGE")

    validate_name("KUBE_NAMESPACE", namespace, subdomain=False)
    for name, value in (
        ("KUBE_IMAGE_PULL_SECRET", image_pull_secret),
        ("RUNTIME_SECRET_NAME", runtime_secret),
        ("RUNTIME_CONFIGMAP_NAME", runtime_configmap),
        ("INGRESS_CLASS_NAME", ingress_class),
        ("TLS_SECRET_NAME", tls_secret),
        ("IMAGE_TAG", image_tag),
    ):
        validate_name(name, value)

    for name, value in (("BACKEND_IMAGE", backend_image), ("FRONTEND_IMAGE", frontend_image)):
        if not IMAGE.fullmatch(value) or not value.endswith(f":{image_tag}"):
            raise SystemExit(f"ERROR: {name} must be a safe immutable image tagged {image_tag}")

    return {
        "__NAMESPACE__": namespace,
        "__IMAGE_PULL_SECRET__": image_pull_secret,
        "__RUNTIME_SECRET_NAME__": runtime_secret,
        "__RUNTIME_CONFIGMAP_NAME__": runtime_configmap,
        "__INGRESS_CLASS_NAME__": ingress_class,
        "__TLS_SECRET_NAME__": tls_secret,
        "__IMAGE_TAG__": image_tag,
        "__BACKEND_IMAGE__": backend_image,
        "__FRONTEND_IMAGE__": frontend_image,
    }


def render(output_dir: Path) -> None:
    """Render and parse all YAML documents, failing on unresolved placeholders."""
    replacements = inputs()
    output_dir.mkdir(parents=True, exist_ok=True)
    for source_name, target_name in TEMPLATES.items():
        content = (ROOT / "ops" / "cce" / source_name).read_text(encoding="utf-8")
        for placeholder, value in replacements.items():
            content = content.replace(placeholder, value)
        if re.search(r"__[A-Z0-9_]+__", content):
            raise SystemExit(f"ERROR: unresolved placeholder in {source_name}")
        documents = [doc for doc in yaml.safe_load_all(content) if doc]
        if not documents:
            raise SystemExit(f"ERROR: {source_name} rendered no Kubernetes objects")
        for document in documents:
            if document.get("kind") in {"Secret", "ConfigMap"}:
                raise SystemExit(
                    "ERROR: delivery templates must reference, not create, runtime data"
                )
        (output_dir / target_name).write_text(content, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    render(args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
