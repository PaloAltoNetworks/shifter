#!/usr/bin/env python3
"""Render the generated GKE edge manifest from Terraform outputs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

_ALLOWED_YAML_SUFFIXES = {".yaml", ".yml"}
_MANAGED_CERTIFICATE_OUTPUT_KEY = "managed_tls_enabled"
_PUBLIC_HOSTNAME_OUTPUT_KEY = "public_hostname"
_PUBLIC_INGRESS_IP_NAME_OUTPUT_KEY = "public_ingress_ip_name"
_REPO_ROOT = Path(__file__).resolve().parents[2]
_TERRAFORM_OUTPUT_PATH = Path("/tmp/gcp-terraform-outputs.json")
_EDGE_MANIFEST_RELATIVE_PATHS = {
    "gcp-dev": Path("platform/k8s/gcp/overlays/gcp-dev/platform-edge.generated.yaml"),
    "gcp-prod": Path("platform/k8s/gcp/overlays/gcp-prod/platform-edge.generated.yaml"),
}


def _validated_output_path(path: Path) -> Path:
    resolved = path.resolve()
    repo_root = _REPO_ROOT.resolve()
    if repo_root not in resolved.parents:
        raise ValueError(f"Output path must stay inside the repository: {resolved}")
    if resolved.suffix not in _ALLOWED_YAML_SUFFIXES:
        raise ValueError(f"Output path must be a YAML file: {resolved}")
    resolved.parent.mkdir(parents=True, exist_ok=True)
    return resolved


def _output_path_for_environment(environment: str) -> Path:
    try:
        relative_path = _EDGE_MANIFEST_RELATIVE_PATHS[environment]
    except KeyError as exc:
        raise ValueError(f"Unsupported environment for edge manifest output: {environment}") from exc
    return _validated_output_path(_REPO_ROOT / relative_path)


def _value(outputs: dict[str, object], key: str):
    try:
        return outputs[key]["value"]
    except KeyError as exc:
        raise KeyError(f"Missing Terraform output: {key}") from exc


def render_manifest(outputs: dict[str, object]) -> str:
    public_hostname = _value(outputs, _PUBLIC_HOSTNAME_OUTPUT_KEY).strip()
    managed_tls_enabled = bool(_value(outputs, _MANAGED_CERTIFICATE_OUTPUT_KEY))
    ingress_ip_name = _value(outputs, _PUBLIC_INGRESS_IP_NAME_OUTPUT_KEY)

    manifest_parts: list[str] = []
    if public_hostname and managed_tls_enabled:
        manifest_parts.append(
            "\n".join(
                [
                    "apiVersion: networking.gke.io/v1beta1",
                    "kind: FrontendConfig",
                    "metadata:",
                    "  name: platform-frontend-config",
                    "  namespace: shifter-platform",
                    "spec:",
                    "  redirectToHttps:",
                    "    enabled: true",
                    "    responseCodeName: TEMPORARY_REDIRECT",
                ]
            )
        )
        manifest_parts.append(
            "\n".join(
                [
                    "apiVersion: networking.gke.io/v1",
                    "kind: ManagedCertificate",
                    "metadata:",
                    "  name: platform-managed-cert",
                    "  namespace: shifter-platform",
                    "spec:",
                    "  domains:",
                    f"    - {public_hostname}",
                ]
            )
        )

    annotations = [
        "    kubernetes.io/ingress.class: gce",
        f"    kubernetes.io/ingress.global-static-ip-name: {ingress_ip_name}",
    ]
    if public_hostname and managed_tls_enabled:
        annotations.append("    networking.gke.io/managed-certificates: platform-managed-cert")
        annotations.append("    networking.gke.io/v1beta1.FrontendConfig: platform-frontend-config")

    rules = [
        "  rules:",
        *([f"    - host: {public_hostname}"] if public_hostname else ["    -"]),
        "      http:",
        "        paths:",
        "          - path: /guacamole",
        "            pathType: Prefix",
        "            backend:",
        "              service:",
        "                name: guacamole-client",
        "                port:",
        "                  number: 8080",
        "          - path: /",
        "            pathType: Prefix",
        "            backend:",
        "              service:",
        "                name: portal-web",
        "                port:",
        "                  number: 8000",
    ]

    manifest_parts.append(
        "\n".join(
            [
                "apiVersion: networking.k8s.io/v1",
                "kind: Ingress",
                "metadata:",
                "  name: platform-external",
                "  namespace: shifter-platform",
                "  annotations:",
                *annotations,
                "spec:",
                "  defaultBackend:",
                "    service:",
                "      name: portal-web",
                "      port:",
                "        number: 8000",
                *rules,
            ]
        )
    )

    return "\n---\n".join(manifest_parts) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--environment", required=True, choices=sorted(_EDGE_MANIFEST_RELATIVE_PATHS))
    args = parser.parse_args()

    outputs = json.loads(_TERRAFORM_OUTPUT_PATH.read_text())
    rendered = render_manifest(outputs)
    output_path = _output_path_for_environment(args.environment)
    output_path.write_text(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
