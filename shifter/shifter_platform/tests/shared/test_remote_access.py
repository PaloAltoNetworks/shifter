"""Closed remote-access binding and OpenVPN profile validation."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from shared.remote_access import (
    TERMINAL_TARGET_PATH_RE,
    OpenVpnBindingError,
    bind_openvpn_realization,
    build_openvpn_capability,
    is_raes_member_target,
    parse_openvpn_binding,
    parse_openvpn_capability,
    parse_openvpn_realization,
    raes_member_target_ref,
    validate_openvpn_profile,
    validate_openvpn_profile_for_endpoint,
)


@pytest.mark.parametrize(
    "path",
    [
        "/ws/terminal/00000000-0000-0000-0000-000000000000/",
        "/ws/terminal/provision.node.attack-workstation#0/",
    ],
)
def test_terminal_target_path_accepts_closed_instance_identifiers(path):
    assert TERMINAL_TARGET_PATH_RE.fullmatch(path)


@pytest.mark.parametrize(
    "path",
    [
        "/ws/terminal/provision.node.attack-workstation#1/",
        "/ws/terminal/provision.node.attack-workstation/",
        "/ws/terminal/provision.node.attack/workstation#0/",
        "/ws/terminal/../provision.node.attack-workstation#0/",
    ],
)
def test_terminal_target_path_rejects_noncanonical_member_identifiers(path):
    assert not TERMINAL_TARGET_PATH_RE.fullmatch(path)


def test_capability_builder_binds_one_target_to_a_bounded_teardown_deadline():
    target = uuid4()
    teardown_at = datetime.now(UTC) + timedelta(days=5)

    parsed = parse_openvpn_capability(build_openvpn_capability(target, teardown_at))

    assert parsed.target_ref == str(target)
    assert parsed.teardown_at >= teardown_at


def test_capability_and_binding_accept_an_exact_raes_member_target():
    member = "provision.node.a14-kali#0"
    capability = build_openvpn_capability(member, datetime.now(UTC) + timedelta(days=5))

    assert parse_openvpn_capability(capability).target_ref == member
    assert parse_openvpn_binding(_binding(target_ref=member)).target_ref == member


@pytest.mark.parametrize(
    "target",
    [
        "provision.node.a14-kali#1",
        "provision.node.a14-kali",
        "provision.node.a14/kali#0",
        "kali",
        "",
        None,
    ],
)
def test_capability_and_binding_reject_targets_outside_the_closed_grammar(target):
    with pytest.raises(OpenVpnBindingError, match="target_ref"):
        build_openvpn_capability(target, datetime.now(UTC) + timedelta(days=5))
    with pytest.raises(OpenVpnBindingError, match="target_ref"):
        parse_openvpn_binding(_binding(target_ref=target))


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
        "verify-x509-name shifter-openvpn-server name\n"
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


@pytest.mark.parametrize(
    "pin",
    ["", "verify-x509-name some-other-server name\n", "verify-x509-name shifter-openvpn-server subject\n"],
    ids=["missing", "other-name", "other-type"],
)
def test_profile_validator_requires_the_pool_server_name_pin(pin):
    profile = _profile().replace("verify-x509-name shifter-openvpn-server name\n", pin)
    with pytest.raises(OpenVpnBindingError):
        validate_openvpn_profile(profile, parse_openvpn_binding(_binding()))


def test_profile_validator_rejects_an_endpoint_that_does_not_match_the_binding():
    binding = parse_openvpn_binding(_binding())
    profile = _profile(endpoint="other.example.test")
    with pytest.raises(OpenVpnBindingError, match="remote"):
        validate_openvpn_profile(profile, binding)


def _realization(**overrides):
    value = {
        "generation": str(uuid4()),
        "target_ref": "provision.node.kali#0",
        "endpoint": "34.1.2.3",
        "port": 1194,
        "secret_ref": "projects/p/secrets/profile",
    }
    value.update(overrides)
    return value


def test_a_realization_binds_to_the_owner_the_caller_is_authoritative_for():
    realization = _realization()
    binding = bind_openvpn_realization(realization, 42)

    parsed = parse_openvpn_binding(binding)
    assert (parsed.owner_user_id, parsed.target_ref, parsed.ready) == (42, "provision.node.kali#0", True)
    assert {key: binding[key] for key in realization} == parse_openvpn_realization(realization)


@pytest.mark.parametrize(
    ("value", "match"),
    [
        (_realization(owner_user_id=7), "unknown"),
        ({key: val for key, val in _realization().items() if key != "secret_ref"}, "missing"),
        (_realization(generation="not-a-uuid"), "generation"),
        (_realization(endpoint="bad endpoint"), "endpoint"),
    ],
)
def test_the_realization_parser_is_closed_and_owner_free(value, match):
    with pytest.raises(OpenVpnBindingError, match=match):
        parse_openvpn_realization(value)


def test_binding_a_realization_requires_a_positive_owner():
    with pytest.raises(OpenVpnBindingError, match="owner_user_id"):
        bind_openvpn_realization(_realization(), 0)


def test_raes_member_targets_are_the_single_instance_of_a_declared_node():
    assert raes_member_target_ref("provision.node.kali") == "provision.node.kali#0"
    assert is_raes_member_target("provision.node.kali#0") is True
    assert is_raes_member_target(str(uuid4())) is False
    with pytest.raises(OpenVpnBindingError, match="target_ref"):
        raes_member_target_ref("kali")


def test_the_endpoint_validator_admits_only_the_bound_remote():
    profile = _profile(endpoint="34.1.2.3", port=1194)
    assert validate_openvpn_profile_for_endpoint(profile, "34.1.2.3", 1194) == profile.encode()
    with pytest.raises(OpenVpnBindingError, match="remote"):
        validate_openvpn_profile_for_endpoint(profile, "34.9.9.9", 1194)
