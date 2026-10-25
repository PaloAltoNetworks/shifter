#!/usr/bin/env python3
"""Create and renew the shared OpenVPN pool's PKI directly in Secret Manager (#2480).

Terraform creates the empty secrets and their IAM; private keys never enter
Terraform state. This deploy step:

* creates the tenant CA and the pool tls-crypt key once, in the issuer secret
  (readable only by the provisioner, which signs participant certificates);
* issues the pool server certificate from that CA, in the server secret
  (readable only by the pool), and renews it before it expires or when the CA
  changes. Superseded server versions are destroyed.

Key material is passed to ``gcloud`` on stdin, never argv, and is never printed.
"""

from __future__ import annotations

import argparse
import json
import subprocess  # nosec B404 - only the fixed gcloud CLI is invoked, with argv and no shell.
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

#: Must equal ``shared.remote_access.OPENVPN_SERVER_NAME``: clients pin it.
SERVER_NAME = "shifter-openvpn-server"
CA_NAME = "shifter-openvpn-ca"
CA_LIFETIME = timedelta(days=3650)
SERVER_LIFETIME = timedelta(days=365)
SERVER_RENEW_BEFORE = timedelta(days=30)
#: A participant certificate may live 397 days; the CA must outlive every one.
CA_MINIMUM_REMAINING = timedelta(days=398)

Runner = Callable[[list[str], str | None], subprocess.CompletedProcess[str]]


def _gcloud(args: list[str], stdin: str | None = None) -> subprocess.CompletedProcess[str]:
    # Closed argv built in this module, no shell; key material only on stdin. gcloud
    # comes from the operator/CI toolchain PATH (setup-gcloud), not from input.
    return subprocess.run(  # nosec B603 B607
        ["gcloud", *args], input=stdin, text=True, capture_output=True, check=False
    )


@dataclass(frozen=True)
class SecretStore:
    """Latest-version reads and version writes for one project."""

    project: str
    run: Runner = _gcloud

    def latest(self, secret: str) -> str | None:
        result = self.run(
            ["secrets", "versions", "access", "latest", f"--secret={secret}", f"--project={self.project}"], None
        )
        if result.returncode == 0:
            return result.stdout
        if "NOT_FOUND" in result.stderr or "not found" in result.stderr.lower():
            return None
        raise RuntimeError(f"cannot read {secret}: gcloud exited {result.returncode}")

    def add(self, secret: str, payload: str) -> None:
        result = self.run(["secrets", "versions", "add", secret, f"--project={self.project}", "--data-file=-"], payload)
        if result.returncode != 0:
            raise RuntimeError(f"cannot write {secret}: gcloud exited {result.returncode}")

    def destroy_superseded(self, secret: str) -> None:
        listed = self.run(
            [
                "secrets", "versions", "list", secret, f"--project={self.project}",
                "--filter=state:ENABLED", "--sort-by=~createTime", "--format=value(name)",
            ],
            None,
        )  # fmt: skip
        if listed.returncode != 0:
            raise RuntimeError(f"cannot list {secret}: gcloud exited {listed.returncode}")
        for version in listed.stdout.split()[1:]:
            self.run(
                [
                    "secrets",
                    "versions",
                    "destroy",
                    version.rsplit("/", 1)[-1],
                    f"--secret={secret}",
                    f"--project={self.project}",
                    "--quiet",
                ],
                None,
            )


def _pem_key(key: ec.EllipticCurvePrivateKey) -> str:
    return key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()


def _pem_certificate(certificate: x509.Certificate) -> str:
    return certificate.public_bytes(serialization.Encoding.PEM).decode()


def _tls_crypt_key() -> str:
    import secrets as random

    body = random.token_hex(256)
    lines = "\n".join(body[index : index + 32] for index in range(0, len(body), 32))
    return f"-----BEGIN OpenVPN Static key V1-----\n{lines}\n-----END OpenVPN Static key V1-----\n"


def _usage(*, ca: bool) -> x509.KeyUsage:
    return x509.KeyUsage(
        digital_signature=True,
        content_commitment=False,
        key_encipherment=False,
        data_encipherment=False,
        key_agreement=not ca,
        key_cert_sign=ca,
        crl_sign=ca,
        encipher_only=False,
        decipher_only=False,
    )


def new_issuer(now: datetime) -> dict[str, str]:
    """Return a new tenant CA, its key and the pool tls-crypt key."""
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, CA_NAME)])
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + CA_LIFETIME)
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(_usage(ca=True), critical=True)
        .sign(key, hashes.SHA256())
    )
    return {"ca": _pem_certificate(certificate), "ca_private_key": _pem_key(key), "tls_crypt": _tls_crypt_key()}


def new_server(issuer: dict[str, str], now: datetime) -> dict[str, str]:
    """Return a pool server identity signed by the tenant CA."""
    ca = x509.load_pem_x509_certificate(issuer["ca"].encode())
    ca_key = serialization.load_pem_private_key(issuer["ca_private_key"].encode(), password=None)
    if not isinstance(ca_key, ec.EllipticCurvePrivateKey):
        raise ValueError("the tenant CA key must be an EC key")
    key = ec.generate_private_key(ec.SECP256R1())
    certificate = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, SERVER_NAME)]))
        .issuer_name(ca.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + SERVER_LIFETIME)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(_usage(ca=False), critical=True)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .sign(ca_key, hashes.SHA256())
    )
    return {
        "ca": issuer["ca"],
        "certificate": _pem_certificate(certificate),
        "private_key": _pem_key(key),
        "tls_crypt": issuer["tls_crypt"],
    }


def _server_is_current(server: dict[str, str] | None, issuer: dict[str, str], now: datetime) -> bool:
    """Return whether the stored server identity is from this CA and not due for renewal."""
    if not server or server.get("ca") != issuer["ca"] or server.get("tls_crypt") != issuer["tls_crypt"]:
        return False
    certificate = x509.load_pem_x509_certificate(server["certificate"].encode())
    return certificate.not_valid_after_utc - now > SERVER_RENEW_BEFORE


def ensure(store: SecretStore, issuer_secret: str, server_secret: str, now: datetime | None = None) -> list[str]:
    """Create or renew the PKI; return the actions taken (no key material)."""
    moment = now or datetime.now(UTC)
    actions: list[str] = []
    stored = store.latest(issuer_secret)
    if stored is None:
        issuer = new_issuer(moment)
        store.add(issuer_secret, json.dumps(issuer))
        actions.append("created tenant CA")
    else:
        issuer = json.loads(stored)
    ca = x509.load_pem_x509_certificate(issuer["ca"].encode())
    if ca.not_valid_after_utc - moment < CA_MINIMUM_REMAINING:
        raise RuntimeError("the tenant OpenVPN CA expires within 398 days; rotate it before minting more profiles")
    stored_server = store.latest(server_secret)
    if not _server_is_current(json.loads(stored_server) if stored_server else None, issuer, moment):
        store.add(server_secret, json.dumps(new_server(issuer, moment)))
        store.destroy_superseded(server_secret)
        actions.append("issued pool server certificate")
    return actions


def main(argv: list[str] | None = None, run: Runner = _gcloud) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--project", required=True)
    parser.add_argument("--issuer-secret", required=True)
    parser.add_argument("--server-secret", required=True)
    parser.add_argument(
        "--changed-output", help="append changed=true|false here (a GitHub step output) so the pool can be rolled"
    )
    args = parser.parse_args(argv)
    actions = ensure(SecretStore(args.project, run), args.issuer_secret, args.server_secret)
    print("OpenVPN PKI: " + ("; ".join(actions) if actions else "current"))
    if args.changed_output:
        with open(args.changed_output, "a", encoding="utf-8") as output:
            output.write(f"changed={'true' if actions else 'false'}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
