"""Participant OpenVPN profiles minted against the tenant CA (#2030, #2480)."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from cryptography import x509
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
from shared.remote_access import build_openvpn_capability, validate_openvpn_profile_for_endpoint

from tests.conftest import MemoryVpnSecretOps, build_vpn_issuer_payload
from vpn_access import (
    OpenVpnPoolEndpoint,
    cleanup_openvpn_access,
    load_issuer,
    mint_openvpn_profile,
    openvpn_pool_endpoint,
)

_TARGET = "provision.node.kali#0"
_MEMBERS = (_TARGET, "provision.node.dc#0")
_ENDPOINT = OpenVpnPoolEndpoint(host="203.0.113.7", port=1194)


def _capability(*, target=_TARGET, days=5):
    return build_openvpn_capability(target, datetime.now(UTC) + timedelta(days=days))


def _block(profile: str, name: str) -> str:
    return re.search(rf"<{name}>\n(.*?)</{name}>", profile, re.S).group(1)


class TestMintProfile:
    def test_profile_carries_a_client_certificate_for_this_generation_only(self, vpn_secret_ops):
        generation = uuid4()
        capability = _capability()

        realization = mint_openvpn_profile(str(generation), 42, _MEMBERS, capability, vpn_secret_ops, _ENDPOINT)

        assert realization == {
            "generation": str(generation),
            "target_ref": _TARGET,
            "endpoint": "203.0.113.7",
            "port": 1194,
            "secret_ref": f"profile:42:{generation}",
        }
        profile = vpn_secret_ops.profiles[(42, str(generation))]
        validate_openvpn_profile_for_endpoint(profile, "203.0.113.7", 1194)
        assert "verify-x509-name shifter-openvpn-server name\n" in profile
        assert "remote-cert-tls server\n" in profile
        certificate = x509.load_pem_x509_certificate(_block(profile, "cert").encode())
        issuer = load_issuer(vpn_secret_ops.issuer)
        assert certificate.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value == f"participant-{generation}"
        assert certificate.issuer == issuer.ca_certificate.subject
        issuer.ca_certificate.public_key().verify(
            certificate.signature, certificate.tbs_certificate_bytes, ec.ECDSA(certificate.signature_hash_algorithm)
        )
        usage = certificate.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value
        assert list(usage) == [ExtendedKeyUsageOID.CLIENT_AUTH]
        teardown = datetime.fromisoformat(str(capability["teardown_at"]).replace("Z", "+00:00"))
        assert abs((certificate.not_valid_after_utc - teardown).total_seconds()) <= 1
        # The CA signing key never leaves the issuer secret.
        assert "ca_private_key" not in profile
        assert _block(profile, "ca") == issuer.ca_pem

    def test_refuses_a_target_that_is_not_exactly_one_member(self, vpn_secret_ops):
        with pytest.raises(ValueError, match="exactly one range member"):
            mint_openvpn_profile(
                str(uuid4()), 42, _MEMBERS, _capability(target="provision.node.x#0"), vpn_secret_ops, _ENDPOINT
            )
        assert vpn_secret_ops.profiles == {}

    def test_refuses_a_deadline_past_the_ca_lifetime(self):
        ops = MemoryVpnSecretOps(build_vpn_issuer_payload(valid_days=2))
        with pytest.raises(ValueError, match="CA expires before"):
            mint_openvpn_profile(str(uuid4()), 42, _MEMBERS, _capability(days=5), ops, _ENDPOINT)
        assert ops.profiles == {}

    def test_refuses_an_unbounded_deadline_before_reading_the_issuer(self, vpn_secret_ops):
        capability = {
            "version": "openvpn-capability-v1",
            "channel": "openvpn",
            "target_ref": _TARGET,
            "teardown_at": (datetime.now(UTC) + timedelta(days=398)).isoformat().replace("+00:00", "Z"),
        }
        with pytest.raises(ValueError, match="397-day maximum"):
            mint_openvpn_profile(str(uuid4()), 42, _MEMBERS, capability, vpn_secret_ops, _ENDPOINT)

    def test_cleanup_deletes_only_the_generation_profile(self, vpn_secret_ops):
        generation = uuid4()
        mint_openvpn_profile(str(generation), 42, _MEMBERS, _capability(), vpn_secret_ops, _ENDPOINT)

        cleanup_openvpn_access(42, str(generation), vpn_secret_ops)

        assert vpn_secret_ops.profiles == {}
        assert vpn_secret_ops.deleted == [(42, str(generation))]


class TestIssuer:
    @pytest.mark.parametrize(
        "mutate",
        [
            lambda value: {**value, "extra": "x"},
            lambda value: {key: value[key] for key in ("ca", "tls_crypt")},
            lambda value: {**value, "tls_crypt": "not a key"},
            lambda value: {**value, "ca_private_key": json.loads(build_vpn_issuer_payload())["ca_private_key"]},
        ],
        ids=["extra-key", "missing-key", "bad-tls-crypt", "mismatched-key"],
    )
    def test_rejects_a_defective_issuer(self, mutate):
        value = json.loads(build_vpn_issuer_payload())
        with pytest.raises(ValueError):
            load_issuer(json.dumps(mutate(value)))

    def test_rejects_non_json(self):
        with pytest.raises(ValueError, match="invalid shape"):
            load_issuer("not json")


class TestPoolEndpoint:
    def test_unset_means_no_pool(self, monkeypatch):
        monkeypatch.delenv("RANGE_OPENVPN_ENDPOINT", raising=False)
        assert openvpn_pool_endpoint() is None

    def test_static_ip_is_the_endpoint(self, monkeypatch):
        monkeypatch.setenv("RANGE_OPENVPN_ENDPOINT", "203.0.113.7")
        assert openvpn_pool_endpoint() == _ENDPOINT

    def test_a_hostname_is_refused(self, monkeypatch):
        monkeypatch.setenv("RANGE_OPENVPN_ENDPOINT", "vpn.example.com")
        with pytest.raises(ValueError, match="static IP"):
            openvpn_pool_endpoint()
