"""Closed remote-access binding and OpenVPN profile validation."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from shared.remote_access import (
    OpenVpnBindingError,
    build_openvpn_capability,
    parse_openvpn_binding,
    parse_openvpn_capability,
    validate_openvpn_profile,
)


def test_capability_builder_binds_one_target_to_a_bounded_teardown_deadline():
    target = uuid4()
    teardown_at = datetime.now(UTC) + timedelta(days=5)

    parsed = parse_openvpn_capability(build_openvpn_capability(target, teardown_at))

    assert parsed.target_ref == target
    assert parsed.teardown_at >= teardown_at


def test_capability_builder_rejects_an_unbounded_credential_window():
    target = uuid4()
    unbounded_teardown = datetime.now(UTC) + timedelta(days=398)
    with pytest.raises(OpenVpnBindingError, match="397-day maximum"):
        build_openvpn_capability(target, unbounded_teardown)


def _binding(**overrides):
    value = {
        "version": "openvpn-binding-v1",
        "channel": "openvpn",
        "generation": str(uuid4()),
        "owner_user_id": 7,
        "target_ref": str(uuid4()),
        "endpoint": "vpn.example.test",
        "port": 1194,
        "profile_version": "openvpn-profile-v1",
        "secret_ref": "arn:aws:secretsmanager:eu-central-1:123:secret:range-vpn",
        "ready": True,
    }
    value.update(overrides)
    return value


def _profile(endpoint="vpn.example.test", port=1194):
    return (
        "client\n"
        "dev tun\n"
        "proto udp\n"
        f"remote {endpoint} {port}\n"
        "nobind\n"
        "persist-key\n"
        "persist-tun\n"
        "remote-cert-tls server\n"
        "auth-nocache\n"
        "verb 3\n"
        "<ca>\nTEST-CA\n</ca>\n"
        "<cert>\nTEST-CERT\n</cert>\n"
        "<key>\nTEST-CLIENT-KEY\n</key>\n"
        "<tls-crypt>\nTEST-TLS-CRYPT\n</tls-crypt>\n"
    )


def test_binding_parser_accepts_only_the_closed_generation_bound_shape():
    parsed = parse_openvpn_binding(_binding())
    assert parsed.channel == "openvpn"
    assert parsed.owner_user_id == 7
    assert parsed.ready is True


@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        ({"provider": "aws"}, "unknown"),
        ({"ready": "yes"}, "ready"),
        ({"secret_ref": "line-one\nline-two"}, "secret_ref"),
        ({"port": 0}, "port"),
    ],
)
def test_binding_parser_rejects_open_or_unsafe_shapes(overrides, match):
    value = _binding(**overrides)
    with pytest.raises(OpenVpnBindingError, match=match):
        parse_openvpn_binding(value)


def test_profile_validator_accepts_a_bounded_inline_credential_for_the_binding():
    binding = parse_openvpn_binding(_binding())
    assert validate_openvpn_profile(_profile(), binding).startswith(b"client\n")


@pytest.mark.parametrize(
    "unsafe_line",
    [
        "script-security 2",
        "up /tmp/hook",
        "plugin malicious.so",
        "redirect-gateway def1",
        "route 10.0.0.0 255.0.0.0",
        "management 127.0.0.1 7505",
    ],
)
def test_profile_validator_rejects_client_code_execution_and_route_expansion(unsafe_line):
    binding = parse_openvpn_binding(_binding())
    profile = _profile() + f"{unsafe_line}\n"
    with pytest.raises(OpenVpnBindingError, match="directive"):
        validate_openvpn_profile(profile, binding)


def test_profile_validator_rejects_an_endpoint_that_does_not_match_the_binding():
    binding = parse_openvpn_binding(_binding())
    profile = _profile(endpoint="other.example.test")
    with pytest.raises(OpenVpnBindingError, match="remote"):
        validate_openvpn_profile(profile, binding)
