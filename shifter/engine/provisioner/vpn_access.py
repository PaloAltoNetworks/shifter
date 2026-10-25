"""Participant OpenVPN profiles for the shared server pool (#2030, #2480).

One tenant VPN CA signs every participant certificate. The provisioner is the
only process that reads the CA signing key. For each range generation it mints
one client certificate that expires at the access deadline, stores the profile
in the provider secret manager, and returns only the closed, owner-free
realization assembled here.

A certificate alone grants nothing: the pool servers ask the portal to
authorize every connection, and the portal admits only a current generation of
a READY range.
"""

from __future__ import annotations

import ipaddress
import json
import os
from collections.abc import Collection
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.types import CertificatePublicKeyTypes
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
from shared.remote_access import (
    OPENVPN_SERVER_NAME,
    parse_openvpn_capability,
    parse_openvpn_realization,
    validate_openvpn_capability_window,
    validate_openvpn_profile_for_endpoint,
)

_ISSUER_KEYS = frozenset({"ca", "ca_private_key", "tls_crypt"})
_TLS_CRYPT_MARKERS = ("-----BEGIN OpenVPN Static key V1-----", "-----END OpenVPN Static key V1-----")
_DEFAULT_PORT = 1194


class VpnSecretOps(Protocol):
    """Small provider-secret port used by the profile lifecycle."""

    def read_issuer(self) -> str:
        """Return the tenant issuer payload (CA certificate, CA key, tls-crypt key)."""

    def put_profile(self, range_id: int, generation: UUID, payload: str) -> str:
        """Store the participant profile and return its opaque provider reference."""

    def delete_profile(self, range_id: int, generation: UUID) -> None:
        """Delete the generation's participant profile idempotently."""


@dataclass(frozen=True)
class OpenVpnIssuer:
    """The tenant CA and the pool-wide tls-crypt key, held only in memory."""

    ca_certificate: x509.Certificate
    ca_private_key: ec.EllipticCurvePrivateKey
    ca_pem: str
    tls_crypt: str


@dataclass(frozen=True)
class OpenVpnPoolEndpoint:
    """The public address every participant profile connects to."""

    host: str
    port: int


def openvpn_pool_endpoint() -> OpenVpnPoolEndpoint | None:
    """Return the configured pool address, or None when the pool is not deployed."""
    host = os.environ.get("RANGE_OPENVPN_ENDPOINT", "").strip()
    if not host:
        return None
    try:
        ipaddress.ip_address(host)
    except ValueError as exc:
        raise ValueError("RANGE_OPENVPN_ENDPOINT must be the pool's static IP address") from exc
    return OpenVpnPoolEndpoint(host=host, port=_DEFAULT_PORT)


def _public_key_der(public_key: CertificatePublicKeyTypes) -> bytes:
    """Return the DER SubjectPublicKeyInfo used to compare a key with its certificate."""
    return public_key.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)


def load_issuer(payload: str) -> OpenVpnIssuer:
    """Parse and verify the tenant issuer payload, failing closed on any defect."""
    try:
        value = json.loads(payload)
    except ValueError as exc:
        raise ValueError("OpenVPN issuer secret has an invalid shape") from exc
    if not isinstance(value, dict) or set(value) != _ISSUER_KEYS or not all(isinstance(v, str) for v in value.values()):
        raise ValueError("OpenVPN issuer secret has an invalid shape")
    try:
        certificate = x509.load_pem_x509_certificate(value["ca"].encode())
        key = serialization.load_pem_private_key(value["ca_private_key"].encode(), password=None)
    except ValueError as exc:
        raise ValueError("OpenVPN issuer secret contains invalid key material") from exc
    constraints = certificate.extensions.get_extension_for_class(x509.BasicConstraints).value
    if not isinstance(key, ec.EllipticCurvePrivateKey) or not constraints.ca:
        raise ValueError("OpenVPN issuer secret must hold an EC certificate authority")
    if _public_key_der(certificate.public_key()) != _public_key_der(key.public_key()):
        raise ValueError("OpenVPN issuer key does not match its certificate")
    tls_crypt = value["tls_crypt"]
    if not all(marker in tls_crypt for marker in _TLS_CRYPT_MARKERS):
        raise ValueError("OpenVPN issuer tls-crypt key is invalid")
    return OpenVpnIssuer(ca_certificate=certificate, ca_private_key=key, ca_pem=value["ca"], tls_crypt=tls_crypt)


def _client_certificate(
    issuer: OpenVpnIssuer, generation: UUID, not_after: datetime
) -> tuple[x509.Certificate, ec.EllipticCurvePrivateKey]:
    """Sign one participant client certificate that expires at the access deadline."""
    key = ec.generate_private_key(ec.SECP256R1())
    now = datetime.now(UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, f"participant-{generation}")]))
        .issuer_name(issuer.ca_certificate.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(not_after)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=True,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.CLIENT_AUTH]), critical=False)
        .sign(private_key=issuer.ca_private_key, algorithm=hashes.SHA256())
    )
    return certificate, key


def _render_profile(
    issuer: OpenVpnIssuer,
    certificate: x509.Certificate,
    key: ec.EllipticCurvePrivateKey,
    endpoint: OpenVpnPoolEndpoint,
) -> str:
    """Render the participant .ovpn profile with inlined credentials."""
    client_pem = certificate.public_bytes(serialization.Encoding.PEM).decode("ascii")
    key_pem = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode("ascii")
    return (
        "client\n"
        "dev tun\n"
        "proto udp\n"
        f"remote {endpoint.host} {endpoint.port}\n"
        "resolv-retry infinite\n"
        "nobind\n"
        "persist-key\n"
        "persist-tun\n"
        "remote-cert-tls server\n"
        f"verify-x509-name {OPENVPN_SERVER_NAME} name\n"
        "auth-nocache\n"
        "verb 3\n"
        "auth SHA256\n"
        "cipher AES-256-GCM\n"
        "data-ciphers AES-256-GCM:AES-128-GCM\n"
        "tls-version-min 1.2\n"
        f"<ca>\n{issuer.ca_pem}</ca>\n"
        f"<cert>\n{client_pem}</cert>\n"
        f"<key>\n{key_pem}</key>\n"
        f"<tls-crypt>\n{issuer.tls_crypt}</tls-crypt>\n"
    )


def mint_openvpn_profile(
    request_uuid: str,
    range_id: int,
    member_refs: Collection[str],
    remote_access_capability: dict[str, object],
    secret_ops: VpnSecretOps,
    endpoint: OpenVpnPoolEndpoint,
) -> dict[str, object]:
    """Mint and store the generation's profile for the exact authorized target.

    ``member_refs`` are the realized range's member keys; the capability must
    name exactly one of them. The returned realization is owner-free; the Engine
    binds the range owner it is authoritative for.
    """
    capability = parse_openvpn_capability(remote_access_capability)
    validate_openvpn_capability_window(capability)
    if list(member_refs).count(capability.target_ref) != 1:
        raise ValueError("OpenVPN capability must identify exactly one range member")
    issuer = load_issuer(secret_ops.read_issuer())
    if issuer.ca_certificate.not_valid_after_utc < capability.teardown_at:
        raise ValueError("The tenant OpenVPN CA expires before the authorized access deadline")
    generation = UUID(request_uuid)
    certificate, key = _client_certificate(issuer, generation, capability.teardown_at)
    profile = _render_profile(issuer, certificate, key, endpoint)
    validate_openvpn_profile_for_endpoint(profile, endpoint.host, endpoint.port)
    return parse_openvpn_realization(
        {
            "generation": str(generation),
            "target_ref": capability.target_ref,
            "endpoint": endpoint.host,
            "port": endpoint.port,
            "secret_ref": secret_ops.put_profile(range_id, generation, profile),
        }
    )


def cleanup_openvpn_access(range_id: int, request_uuid: str, secret_ops: VpnSecretOps) -> None:
    """Delete the generation's participant profile."""
    secret_ops.delete_profile(range_id, UUID(request_uuid))


__all__ = [
    "OpenVpnIssuer",
    "OpenVpnPoolEndpoint",
    "VpnSecretOps",
    "cleanup_openvpn_access",
    "load_issuer",
    "mint_openvpn_profile",
    "openvpn_pool_endpoint",
]
