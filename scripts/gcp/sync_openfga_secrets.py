#!/usr/bin/env python3
"""Deliver named policy bundles through provider-native and Kubernetes Secrets."""

import argparse
import base64
import json
import subprocess  # nosec B404
from pathlib import Path

from installation.loader import load_root_config
from installation.settings_gcp import GcpBackendSettings, GcpOpenFgaSettings

_BUNDLE_KEYS = {"server-preshared-keys", "api-token", "tls.crt", "tls.key"}


def fetch_secret(reference: str) -> dict:
    _, project, _, secret = reference.split("/")
    # Fixed operator/CI CLI; named references are validated and no shell interprets argv.
    result = subprocess.run(  # nosec B603 B607
        ["gcloud", "secrets", "versions", "access", "latest", "--project", project, "--secret", secret],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise ValueError("Named policy bundle could not be read")
    return json.loads(result.stdout)


def apply_resource(document: dict) -> None:
    # Fixed operator/CI CLI; named references are validated and no shell interprets argv.
    result = subprocess.run(  # nosec B603 B607
        ["kubectl", "apply", "--server-side", "--field-manager=shifter-policy-secrets", "-f", "-"],
        input=json.dumps(document),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise ValueError("Policy credential publication failed")


def _bundle_keys(bundle: object) -> set[str]:
    if (
        not isinstance(bundle, dict)
        or set(bundle) != _BUNDLE_KEYS
        or not all(isinstance(value, str) and value and "\0" not in value for value in bundle.values())
    ):
        raise ValueError("Policy bundle must contain only the native credential and TLS fields")
    keys = {key.strip() for key in bundle["server-preshared-keys"].split(",")}
    if not keys or any(len(key) < 32 for key in keys):
        raise ValueError("Policy authentication keys must be at least 32 characters")
    return keys


def sync(settings: object) -> None:
    policy = GcpOpenFgaSettings.model_validate(settings)
    if not policy.enabled:
        return
    runtime = fetch_secret(policy.runtime_secret_ref)
    admin = fetch_secret(policy.admin_secret_ref)
    ca = fetch_secret(policy.ca_secret_ref)
    runtime_keys, admin_keys = _bundle_keys(runtime), _bundle_keys(admin)
    if runtime_keys & admin_keys or runtime["tls.key"] == admin["tls.key"]:
        raise ValueError("Runtime and administration require separate authentication and TLS keys")
    if runtime["api-token"] not in runtime_keys or admin["api-token"] not in admin_keys:
        raise ValueError("Policy client token must match its own native server authentication keys")
    if not isinstance(ca, dict) or set(ca) != {"ca.crt"} or not isinstance(ca["ca.crt"], str) or not ca["ca.crt"]:
        raise ValueError("Policy CA publication accepts only the public CA certificate")
    for name, bundle in (("openfga-runtime", runtime), ("openfga-admin", admin)):
        apply_resource(
            {
                "apiVersion": "v1",
                "kind": "Secret",
                "metadata": {
                    "name": name,
                    "namespace": "shifter-platform",
                    "labels": {"app.kubernetes.io/part-of": "shifter"},
                },
                "type": "Opaque",
                "data": {
                    (
                        "runtime-preshared-key" if name == "openfga-runtime" and key == "api-token" else key
                    ): base64.b64encode(value.encode()).decode()
                    for key, value in bundle.items()
                },
            }
        )
    apply_resource(
        {
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "metadata": {
                "name": "openfga-ca",
                "namespace": "shifter-platform",
                "labels": {"app.kubernetes.io/part-of": "shifter"},
            },
            "data": ca,
        }
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    settings = GcpBackendSettings.from_root_settings(load_root_config(args.config).settings)
    sync(settings.openfga.model_dump())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
