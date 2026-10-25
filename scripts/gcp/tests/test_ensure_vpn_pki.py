"""The shared OpenVPN pool PKI bootstrap and renewal step (#2480)."""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

_SPEC = importlib.util.spec_from_file_location("ensure_vpn_pki", Path(__file__).parents[1] / "ensure_vpn_pki.py")
assert _SPEC is not None and _SPEC.loader is not None
pki = importlib.util.module_from_spec(_SPEC)
sys.modules["ensure_vpn_pki"] = pki
_SPEC.loader.exec_module(pki)

_NOW = datetime(2026, 10, 5, tzinfo=UTC)


class FakeGcloud:
    """Secret Manager as seen through the gcloud CLI, in memory."""

    def __init__(self) -> None:
        self.versions: dict[str, list[tuple[str, str]]] = {"issuer": [], "server": []}
        self.calls: list[list[str]] = []

    def __call__(self, args: list[str], stdin: str | None) -> subprocess.CompletedProcess[str]:
        self.calls.append(args)
        verb = args[2]
        secret = next((a.split("=", 1)[1] for a in args if a.startswith("--secret=")), args[3] if len(args) > 3 else "")
        if verb == "access":
            live = [payload for _name, payload in self.versions[secret] if payload is not None]
            if not live:
                return subprocess.CompletedProcess(args, 1, "", "ERROR: NOT_FOUND: Secret Version [latest] not found")
            return subprocess.CompletedProcess(args, 0, live[-1], "")
        if verb == "add":
            name = f"projects/p/secrets/{secret}/versions/{len(self.versions[secret]) + 1}"
            self.versions[secret].append((name, stdin))
            return subprocess.CompletedProcess(args, 0, "", "")
        if verb == "list":
            names = [name for name, payload in reversed(self.versions[secret]) if payload is not None]
            return subprocess.CompletedProcess(args, 0, "\n".join(names), "")
        if verb == "destroy":
            number = args[3]
            self.versions[secret] = [
                (name, None if name.endswith(f"/{number}") else payload) for name, payload in self.versions[secret]
            ]
            return subprocess.CompletedProcess(args, 0, "", "")
        raise AssertionError(args)


def _store(fake: FakeGcloud):
    return pki.SecretStore(project="p", run=fake)


def _latest(fake: FakeGcloud, secret: str) -> dict:
    return json.loads([payload for _name, payload in fake.versions[secret] if payload is not None][-1])


def test_first_run_creates_a_ca_and_a_server_identity_it_signs():
    fake = FakeGcloud()

    assert pki.ensure(_store(fake), "issuer", "server", _NOW) == ["created tenant CA", "issued pool server certificate"]

    issuer, server = _latest(fake, "issuer"), _latest(fake, "server")
    assert set(issuer) == {"ca", "ca_private_key", "tls_crypt"}
    assert set(server) == {"ca", "certificate", "private_key", "tls_crypt"}
    assert "ca_private_key" not in json.dumps(server)
    ca = x509.load_pem_x509_certificate(issuer["ca"].encode())
    certificate = x509.load_pem_x509_certificate(server["certificate"].encode())
    assert certificate.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value == pki.SERVER_NAME
    ca.public_key().verify(
        certificate.signature, certificate.tbs_certificate_bytes, ec.ECDSA(certificate.signature_hash_algorithm)
    )
    assert list(certificate.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value) == [
        ExtendedKeyUsageOID.SERVER_AUTH
    ]
    assert server["tls_crypt"] == issuer["tls_crypt"]
    # Key material reaches gcloud on stdin only.
    assert not any("PRIVATE KEY" in arg for call in fake.calls for arg in call)


def test_a_current_pki_is_left_alone():
    fake = FakeGcloud()
    pki.ensure(_store(fake), "issuer", "server", _NOW)

    assert pki.ensure(_store(fake), "issuer", "server", _NOW + timedelta(days=100)) == []
    assert len(fake.versions["issuer"]) == 1


def test_the_server_identity_is_renewed_before_expiry_and_old_versions_destroyed():
    fake = FakeGcloud()
    pki.ensure(_store(fake), "issuer", "server", _NOW)

    actions = pki.ensure(_store(fake), "issuer", "server", _NOW + timedelta(days=340))

    assert actions == ["issued pool server certificate"]
    enabled = [name for name, payload in fake.versions["server"] if payload is not None]
    assert enabled == ["projects/p/secrets/server/versions/2"]


def test_a_ca_too_close_to_expiry_refuses_to_continue():
    fake = FakeGcloud()
    pki.ensure(_store(fake), "issuer", "server", _NOW)

    with pytest.raises(RuntimeError, match="rotate"):
        pki.ensure(_store(fake), "issuer", "server", _NOW + pki.CA_LIFETIME - timedelta(days=100))


def test_an_unreadable_secret_fails_instead_of_minting_a_new_ca():
    def denied(args, _stdin):
        return subprocess.CompletedProcess(args, 1, "", "ERROR: PERMISSION_DENIED")

    with pytest.raises(RuntimeError, match="cannot read"):
        pki.ensure(pki.SecretStore(project="p", run=denied), "issuer", "server", _NOW)


def test_the_server_name_matches_the_name_clients_pin():
    shared = Path(__file__).parents[3] / "shifter/shifter_platform/shared/remote_access.py"
    match = re.search(r'^OPENVPN_SERVER_NAME = "([^"]+)"', shared.read_text(), re.M)
    assert match and match.group(1) == pki.SERVER_NAME


def test_the_cli_reports_whether_the_pool_must_reload(tmp_path):
    fake = FakeGcloud()
    output = tmp_path / "github-output"
    args = ["--project", "p", "--issuer-secret", "issuer", "--server-secret", "server", "--changed-output", str(output)]

    assert pki.main(args, run=fake) == 0
    assert pki.main(args, run=fake) == 0

    assert output.read_text().splitlines() == ["changed=true", "changed=false"]
