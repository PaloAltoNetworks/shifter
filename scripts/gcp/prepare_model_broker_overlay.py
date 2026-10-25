#!/usr/bin/env python3
"""Reconcile deploy-owned broker trust and render a reviewed GCP overlay."""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import secrets
import subprocess  # nosec B404 - fixed kubectl and openssl argv, with no shell.
import tempfile
from pathlib import Path
from typing import Any

from installation.model_access import compute_catalog_digest

NAMESPACE = "shifter-platform"
SIGNER_NAME = "model-access-ca-signer-v1"
BROKER_TLS_NAME = "model-broker-tls-v1"
CONTROL_TLS_NAME = "model-control-tls-v1"
TRUST_NAME = "model-access-ca-v1"
FINGERPRINT_NAME = "broker-fingerprint-v1"
MAX_TEMPLATE_BYTES = 96 * 1024
PROJECT_ID_RE = re.compile(r"[a-z][a-z0-9-]{4,28}[a-z0-9]\Z")


def _run(argv: list[str], *, input_text: str | None = None) -> str:
    result = subprocess.run(  # nosec B603 - fixed executable and argv; no shell.
        argv, input=input_text, capture_output=True, text=True, check=False
    )
    if result.returncode:
        raise RuntimeError(f"deployment command failed: {argv[0]} {argv[1]}")
    return result.stdout


def _replace_placeholders(value: Any, project_id: str) -> Any:
    if isinstance(value, dict):
        return {
            _replace_placeholders(key, project_id): _replace_placeholders(item, project_id)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_replace_placeholders(item, project_id) for item in value]
    if isinstance(value, str):
        return value.replace("__GCP_PROJECT_ID__", project_id)
    return value


def render_overlay(template: Path, *, project_id: str, ca_pem: str) -> str:
    """Bind one project and public CA to the checked-in policy, then seal it."""
    if not PROJECT_ID_RE.fullmatch(project_id):
        raise ValueError("invalid deployment project id")
    raw = template.read_bytes()
    if len(raw) > MAX_TEMPLATE_BYTES:
        raise ValueError("broker overlay template exceeds its size limit")
    policy = _replace_placeholders(json.loads(raw), project_id)
    if set(policy) != {"settings"} or set(policy["settings"]) != {
        "model_access",
        "model_broker",
        "model_broker_runtime",
    }:
        raise ValueError("broker overlay has unexpected settings")
    runtime = policy["settings"]["model_broker_runtime"]
    if runtime["guest_trust_ca_pem"] != "__GUEST_CA_PEM__":
        raise ValueError("broker overlay lacks the trust placeholder")
    runtime["guest_trust_ca_pem"] = ca_pem
    catalog = policy["settings"]["model_access"]["catalog"]
    if catalog["digest"] != "__CATALOG_DIGEST__":
        raise ValueError("broker overlay lacks the catalog digest placeholder")
    catalog["digest"] = compute_catalog_digest(catalog)
    rendered = json.dumps(policy, sort_keys=True, separators=(",", ":"))
    if "__GCP_PROJECT_ID__" in rendered or "__GUEST_CA_PEM__" in rendered or "__CATALOG_DIGEST__" in rendered:
        raise ValueError("broker overlay contains an unresolved placeholder")
    return rendered


def _kubectl(context: str, *args: str, input_text: str | None = None) -> str:
    return _run(["kubectl", "--context", context, "-n", NAMESPACE, *args], input_text=input_text)


def _get_object(context: str, kind: str, name: str) -> dict[str, Any] | None:
    result = subprocess.run(  # nosec B603 B607 - fixed kubectl argv from the workflow toolchain; no shell.
        ["kubectl", "--context", context, "-n", NAMESPACE, "get", kind, name, "-o", "json"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        if "NotFound" in result.stderr:
            return None
        raise RuntimeError(f"could not read deployment {kind}")
    return json.loads(result.stdout)


def _secret_bytes(context: str, name: str, key: str) -> bytes | None:
    obj = _get_object(context, "secret", name)
    if obj is None:
        return None
    value = obj.get("data", {}).get(key)
    if not isinstance(value, str):
        raise ValueError(f"deployment Secret {name} lacks {key}")
    return base64.b64decode(value, validate=True)


def _apply_object(context: str, *, kind: str, name: str, data: dict[str, str]) -> None:
    obj = {
        "apiVersion": "v1",
        "kind": kind,
        "metadata": {
            "name": name,
            "namespace": NAMESPACE,
            "labels": {"app.kubernetes.io/managed-by": "shifter-gcp-deploy"},
        },
        "data": data,
    }
    _kubectl(
        context,
        "apply",
        "--server-side",
        "--force-conflicts",
        "--field-manager=shifter-gcp-deploy",
        "-f",
        "-",
        input_text=json.dumps(obj),
    )


def _write_private(path: Path, content: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(content)


def _generate_ca(directory: Path) -> tuple[bytes, bytes]:
    key = directory / "ca.key"
    cert = directory / "ca.crt"
    _run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:3072",
            "-nodes",
            "-sha256",
            "-days",
            "365",
            "-keyout",
            str(key),
            "-out",
            str(cert),
            "-subj",
            "/CN=Shifter model access CA",
            "-addext",
            "basicConstraints=critical,CA:TRUE",
            "-addext",
            "keyUsage=critical,keyCertSign,cRLSign",
        ]
    )
    return cert.read_bytes(), key.read_bytes()


def _verify_ca(directory: Path, cert: bytes, key: bytes) -> None:
    _write_private(directory / "ca.crt", cert)
    _write_private(directory / "ca.key", key)
    _run(["openssl", "x509", "-in", str(directory / "ca.crt"), "-noout", "-checkend", "2592000"])
    cert_public = _run(["openssl", "x509", "-in", str(directory / "ca.crt"), "-pubkey", "-noout"])
    key_public = _run(["openssl", "pkey", "-in", str(directory / "ca.key"), "-pubout"])
    if cert_public != key_public:
        raise ValueError("broker CA certificate and key do not match")


def _generate_leaf(directory: Path, *, name: str, common_name: str, san: str) -> tuple[bytes, bytes]:
    key = directory / f"{name}.key"
    csr = directory / f"{name}.csr"
    cert = directory / f"{name}.crt"
    extensions = directory / f"{name}.ext"
    _write_private(
        extensions,
        (
            "basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\n"
            f"extendedKeyUsage=serverAuth\nsubjectAltName={san}\n"
        ).encode(),
    )
    _run(
        [
            "openssl",
            "req",
            "-new",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-sha256",
            "-keyout",
            str(key),
            "-out",
            str(csr),
            "-subj",
            f"/CN={common_name}",
        ]
    )
    _run(
        [
            "openssl",
            "x509",
            "-req",
            "-in",
            str(csr),
            "-CA",
            str(directory / "ca.crt"),
            "-CAkey",
            str(directory / "ca.key"),
            "-CAcreateserial",
            "-days",
            "30",
            "-sha256",
            "-extfile",
            str(extensions),
            "-out",
            str(cert),
        ]
    )
    _run(["openssl", "verify", "-CAfile", str(directory / "ca.crt"), str(cert)])
    return cert.read_bytes(), key.read_bytes()


def _verify_leaf(directory: Path, *, name: str, cert: bytes, key: bytes, dns_name: str, vip: str = "") -> None:
    cert_path = directory / f"{name}-existing.crt"
    key_path = directory / f"{name}-existing.key"
    _write_private(cert_path, cert)
    _write_private(key_path, key)
    _run(["openssl", "x509", "-in", str(cert_path), "-noout", "-checkend", "1209600"])
    _run(["openssl", "verify", "-CAfile", str(directory / "ca.crt"), "-verify_hostname", dns_name, str(cert_path)])
    if vip:
        _run(["openssl", "verify", "-CAfile", str(directory / "ca.crt"), "-verify_ip", vip, str(cert_path)])
    cert_public = _run(["openssl", "x509", "-in", str(cert_path), "-pubkey", "-noout"])
    key_public = _run(["openssl", "pkey", "-in", str(key_path), "-pubout"])
    if cert_public != key_public:
        raise ValueError("broker TLS certificate and key do not match")


def _secret_data(**values: bytes) -> dict[str, str]:
    return {key: base64.b64encode(value).decode("ascii") for key, value in values.items()}


def ensure_trust(context: str, *, hostname: str, vip: str) -> str:
    """Adopt the old transport objects under a stable, deploy-owned signer."""
    with tempfile.TemporaryDirectory(prefix="shifter-model-trust-") as temporary:
        directory = Path(temporary)
        ca_cert = _secret_bytes(context, SIGNER_NAME, "ca.crt")
        ca_key = _secret_bytes(context, SIGNER_NAME, "ca.key") if ca_cert is not None else None
        new_signer = ca_cert is None
        if ca_cert is None:
            ca_cert, ca_key = _generate_ca(directory)
            _apply_object(
                context, kind="Secret", name=SIGNER_NAME, data=_secret_data(**{"ca.crt": ca_cert, "ca.key": ca_key})
            )
        else:
            assert ca_key is not None
            _verify_ca(directory, ca_cert, ca_key)
        if not (directory / "ca.crt").exists():
            # A newly generated signer already wrote both files.
            raise RuntimeError("broker CA generation did not produce a certificate")
        control_name = "model-access-control.shifter-platform.svc"
        leaves = (
            (BROKER_TLS_NAME, "broker", hostname, f"DNS:{hostname},IP:{vip}", vip),
            (CONTROL_TLS_NAME, "control", control_name, f"DNS:{control_name},DNS:{control_name}.cluster.local", ""),
        )
        for resource_name, file_name, dns_name, san, address in leaves:
            existing_cert = _secret_bytes(context, resource_name, "tls.crt") if not new_signer else None
            if existing_cert is not None:
                existing_key = _secret_bytes(context, resource_name, "tls.key")
                assert existing_key is not None
                _verify_leaf(
                    directory, name=file_name, cert=existing_cert, key=existing_key, dns_name=dns_name, vip=address
                )
            else:
                cert, key = _generate_leaf(directory, name=file_name, common_name=dns_name, san=san)
                _apply_object(
                    context, kind="Secret", name=resource_name, data=_secret_data(**{"tls.crt": cert, "tls.key": key})
                )
        _apply_object(context, kind="ConfigMap", name=TRUST_NAME, data={"ca.crt": ca_cert.decode("ascii")})
        if _secret_bytes(context, FINGERPRINT_NAME, "key") is None:
            _apply_object(context, kind="Secret", name=FINGERPRINT_NAME, data=_secret_data(key=secrets.token_bytes(32)))
        return ca_cert.decode("ascii")


def read_trust(context: str) -> str:
    """The deploy job uses exactly the CA established by its prepare job."""
    ca_cert = _secret_bytes(context, SIGNER_NAME, "ca.crt")
    if ca_cert is None:
        raise ValueError("broker signer Secret is missing")
    trust = _get_object(context, "configmap", TRUST_NAME)
    if trust is None or trust.get("data", {}).get("ca.crt") != ca_cert.decode("ascii"):
        raise ValueError("broker trust ConfigMap differs from the deploy-owned signer")
    for name in (BROKER_TLS_NAME, CONTROL_TLS_NAME, FINGERPRINT_NAME):
        if _get_object(context, "secret", name) is None:
            raise ValueError("broker transport Secret is missing")
    return ca_cert.decode("ascii")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--context", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mode", choices=("ensure", "read"), required=True)
    args = parser.parse_args()
    os.umask(0o077)
    if not args.context.startswith(f"connectgateway_{args.project_id}_"):
        raise ValueError("broker overlay context does not match the deployment project")
    render_overlay(args.template, project_id=args.project_id, ca_pem="pending-deploy-trust")
    template = json.loads(args.template.read_text(encoding="utf-8"))
    broker = template["settings"]["model_broker"]
    if (
        broker["tls_secret_name"] != BROKER_TLS_NAME
        or broker["control_tls_secret_name"] != CONTROL_TLS_NAME
        or broker["trust_configmap_name"] != TRUST_NAME
        or template["settings"]["model_broker_runtime"]["fingerprint_secret_name"] != FINGERPRINT_NAME
    ):
        raise ValueError("broker overlay resource names differ from the deploy-owned trust inventory")
    ca_pem = (
        ensure_trust(args.context, hostname=broker["hostname"], vip=broker["vip"])
        if args.mode == "ensure"
        else read_trust(args.context)
    )
    rendered = render_overlay(args.template, project_id=args.project_id, ca_pem=ca_pem)
    descriptor = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(rendered + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
