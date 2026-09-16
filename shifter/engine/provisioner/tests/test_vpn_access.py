"""Provider-neutral OpenVPN credential and binding lifecycle tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from cryptography import x509
from shared.remote_access import build_openvpn_capability, parse_openvpn_binding, validate_openvpn_profile


class MemorySecretOps:
    """Secret-store double that exposes only references to the caller."""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.deleted: list[tuple[int, str]] = []

    def read_or_create_issuer(self, range_id, generation, payload_factory):
        ref = f"issuer:{range_id}:{generation}"
        if ref not in self.values:
            self.values[ref] = payload_factory()
        return self.values[ref]

    def put_server(self, range_id, generation, payload):
        self.values[f"server:{range_id}:{generation}"] = payload

    def put_profile(self, range_id, generation, payload):
        ref = f"profile:{range_id}:{generation}"
        self.values[ref] = payload
        return ref

    def delete_generation(self, range_id, generation, *, delete_identity=True):
        self.deleted.append((range_id, str(generation)))
        prefix = f":{range_id}:{generation}"
        self.values = {key: value for key, value in self.values.items() if not key.endswith(prefix)}


def _variables(*, target_count=1):
    instances = [
        {
            "uuid": str(uuid4()),
            "name": f"kali-{index}",
            "role": "attacker",
            "os_type": "kali",
        }
        for index in range(target_count)
    ]
    return {
        "range_id": 42,
        "user_id": 7,
        "subnets": [{"name": "attack", "instances": instances}],
    }


def _capability(variables, *, teardown_at=None, target_ref=None):
    instances = variables["subnets"][0]["instances"]
    selected = target_ref or (instances[0]["uuid"] if instances else uuid4())
    return build_openvpn_capability(selected, teardown_at or datetime.now(UTC) + timedelta(days=5))


def _prepare(generation, variables, ops, *, capability=None):
    from vpn_access import prepare_openvpn_access

    return prepare_openvpn_access(
        str(generation),
        42,
        7,
        variables,
        capability or _capability(variables),
        ops,
    )


def test_prepare_and_finalize_emit_a_ref_only_binding_and_valid_profile():
    from vpn_access import finalize_openvpn_access, verify_openvpn_gateway

    generation = uuid4()
    variables = _variables()
    ops = MemorySecretOps()

    preparation = _prepare(generation, variables, ops)
    gateway = verify_openvpn_gateway(
        {
            "endpoint": "vpn.example.test",
            "port": 1194,
            "health_endpoint": "10.20.30.40",
            "health_port": 1195,
            "target_ref": variables["subnets"][0]["instances"][0]["uuid"],
            "ready": False,
        },
        readiness_probe=lambda endpoint, port: endpoint == "10.20.30.40" and port == 1195,
    )
    binding_dict = finalize_openvpn_access(
        preparation,
        gateway,
        ops,
    )

    binding = parse_openvpn_binding(binding_dict)
    profile = ops.values[binding.secret_ref]
    assert validate_openvpn_profile(profile, binding) == profile.encode()
    assert set(binding_dict) == {
        "version",
        "channel",
        "generation",
        "owner_user_id",
        "target_ref",
        "endpoint",
        "port",
        "profile_version",
        "secret_ref",
        "ready",
    }
    assert "profile" not in binding_dict
    assert "key" not in binding_dict


def test_prepare_is_idempotent_for_one_range_generation():

    generation = uuid4()
    variables = _variables()
    ops = MemorySecretOps()
    capability = _capability(variables)

    first = _prepare(generation, variables, ops, capability=capability)
    second = _prepare(generation, variables, ops, capability=capability)

    assert first == second
    assert len(ops.values) == 2


def test_prepare_rejects_a_capability_without_exactly_one_matching_target():
    ops = MemorySecretOps()
    variables = _variables(target_count=0)
    zero_generation = uuid4()
    with pytest.raises(ValueError, match="exactly one"):
        _prepare(zero_generation, variables, ops)
    duplicated = _variables(target_count=1)
    duplicated["subnets"][0]["instances"].append(dict(duplicated["subnets"][0]["instances"][0]))
    duplicate_generation = uuid4()
    with pytest.raises(ValueError, match="exactly one"):
        _prepare(duplicate_generation, duplicated, ops)
    assert ops.values == {}


def test_finalize_rejects_wrong_target_or_unready_gateway():
    from vpn_access import finalize_openvpn_access

    variables = _variables()
    ops = MemorySecretOps()
    preparation = _prepare(uuid4(), variables, ops)

    wrong_target_gateway = {
        "endpoint": "vpn.example.test",
        "port": 1194,
        "target_ref": str(uuid4()),
        "ready": True,
    }
    with pytest.raises(ValueError, match="target"):
        finalize_openvpn_access(preparation, wrong_target_gateway, ops)
    unready_gateway = {
        "endpoint": "vpn.example.test",
        "port": 1194,
        "target_ref": variables["subnets"][0]["instances"][0]["uuid"],
        "ready": False,
    }
    with pytest.raises(ValueError, match="ready"):
        finalize_openvpn_access(preparation, unready_gateway, ops)


def test_gateway_verification_fails_closed_when_service_probe_does_not_pass():
    from vpn_access import verify_openvpn_gateway

    gateway = {
        "endpoint": "vpn.example.test",
        "port": 1194,
        "health_port": 1195,
        "target_ref": str(uuid4()),
        "ready": False,
    }
    with pytest.raises(ValueError, match="service did not become ready"):
        verify_openvpn_gateway(gateway, readiness_probe=lambda _endpoint, _port: False)


def test_gateway_verification_rejects_missing_endpoint_before_probe():
    from vpn_access import verify_openvpn_gateway

    probed = False

    def probe(_endpoint, _port):
        nonlocal probed
        probed = True
        return True

    with pytest.raises(ValueError, match="endpoint is invalid"):
        verify_openvpn_gateway(
            {"endpoint": "", "port": 1194, "health_port": 1195, "ready": False},
            readiness_probe=probe,
        )

    assert probed is False


def test_aws_gateway_stays_pending_until_service_and_policy_probe():
    module = Path(__file__).parents[1] / "terraform" / "modules" / "range"
    outputs = (module / "outputs.tf").read_text(encoding="utf-8")
    resources = (module / "vpn.tf").read_text(encoding="utf-8")
    bootstrap = (module / "templates" / "openvpn_gateway_aws.py.tpl").read_text(encoding="utf-8")

    assert "health_port     = 1195" in outputs
    assert "health_endpoint = aws_instance.vpn_gateway[0].private_ip" in outputs
    assert "ready           = false" in outputs
    assert "cidr_blocks = [var.vpn_public_client_cidr]" in resources
    assert "instance.instance_uuid == var.openvpn_access.target_ref" in resources
    assert 'instance.role == "attacker"' not in resources
    assert "cidr_blocks       = [var.portal_vpc_cidr]" in resources
    assert 'resource "aws_lb_listener" "vpn_health"' not in resources
    assert 'protocol            = "TCP"' in resources
    assert 'port                = "1195"' in resources
    assert "shifter-openvpn-health.service" in bootstrap
    assert 'systemctl", "is-active", "--quiet", "openvpn-server@server"' in bootstrap
    assert '"iptables", "-C", "FORWARD", "-i", "tun0"' in bootstrap
    assert 'self.request.sendall(b"ready\\n")' in bootstrap


def test_engine_provisioner_and_gateway_allow_private_health_probe_path():
    repo = Path(__file__).parents[4]
    gateway_security = (
        repo / "shifter" / "engine" / "provisioner" / "terraform" / "modules" / "range" / "vpn.tf"
    ).read_text(encoding="utf-8")
    provisioner_security = (
        repo / "platform" / "terraform" / "modules" / "engine-provisioner" / "security.tf"
    ).read_text(encoding="utf-8")

    gateway_ingress = gateway_security.split('resource "aws_security_group_rule" "vpn_gateway_health_from_portal"', 1)[
        1
    ].split("\n}", 1)[0]
    provisioner_egress = provisioner_security.split(
        'resource "aws_security_group_rule" "ecs_openvpn_health_to_range"', 1
    )[1].split("\n}", 1)[0]

    assert "from_port         = 1195" in gateway_ingress
    assert "to_port           = 1195" in gateway_ingress
    assert "cidr_blocks       = [var.portal_vpc_cidr]" in gateway_ingress
    assert 'type              = "egress"' in provisioner_egress
    assert "from_port         = 1195" in provisioner_egress
    assert "to_port           = 1195" in provisioner_egress
    assert 'protocol          = "tcp"' in provisioner_egress
    assert "cidr_blocks       = [var.range_vpc_cidr]" in provisioner_egress


def test_aws_gateway_bootstrap_uses_the_baked_runtime_without_package_egress():
    module = Path(__file__).parents[1] / "terraform" / "modules" / "range"
    bootstrap = (module / "templates" / "openvpn_gateway_aws.py.tpl").read_text(encoding="utf-8")

    assert "package_update:" not in bootstrap
    assert "\npackages:" not in bootstrap
    assert "apt-get" not in bootstrap
    assert "import boto3" in bootstrap
    assert "  - [python3, /usr/local/sbin/configure-shifter-openvpn.py]" in bootstrap


def test_aws_gateway_secrets_client_uses_the_module_region():
    module = Path(__file__).parents[1] / "terraform" / "modules" / "range"
    bootstrap = (module / "templates" / "openvpn_gateway_aws.py.tpl").read_text(encoding="utf-8")
    resources = (module / "vpn.tf").read_text(encoding="utf-8")

    assert 'boto3.client("secretsmanager", region_name="${region}")' in bootstrap
    assert "region       = substr(var.availability_zone, 0, length(var.availability_zone) - 1)" in resources


def test_aws_gateway_server_uses_ecdh_without_a_static_dh_file():
    module = Path(__file__).parents[1] / "terraform" / "modules" / "range"
    bootstrap = (module / "templates" / "openvpn_gateway_aws.py.tpl").read_text(encoding="utf-8")

    assert "\n      dh none\n" in bootstrap
    assert "dh /etc/openvpn" not in bootstrap


def test_server_payload_excludes_client_and_ca_signing_keys():

    generation = uuid4()
    ops = MemorySecretOps()
    variables = _variables()
    teardown_at = datetime.now(UTC) + timedelta(days=5)
    _prepare(generation, variables, ops, capability=_capability(variables, teardown_at=teardown_at))

    server = json.loads(ops.values[f"server:42:{generation}"])
    assert set(server) == {"ca", "certificate", "private_key", "tls_crypt"}
    assert "client" not in json.dumps(server).lower()
    issuer = json.loads(ops.values[f"issuer:42:{generation}"])
    assert issuer["generation"] == str(generation)

    ca = x509.load_pem_x509_certificate(issuer["ca"].encode())
    server_certificate = x509.load_pem_x509_certificate(server["certificate"].encode())
    now = datetime.now(UTC)
    assert server_certificate.not_valid_after_utc <= ca.not_valid_after_utc
    assert timedelta(days=4) < server_certificate.not_valid_after_utc - now <= timedelta(days=5, seconds=1)
    assert abs((server_certificate.not_valid_after_utc - teardown_at).total_seconds()) <= 1


def test_prepare_rejects_an_unbounded_deadline_before_writing_secrets():
    variables = _variables()
    ops = MemorySecretOps()
    generation = uuid4()
    unbounded_teardown = (datetime.now(UTC) + timedelta(days=398)).isoformat().replace("+00:00", "Z")
    capability = {
        "version": "openvpn-capability-v1",
        "channel": "openvpn",
        "target_ref": variables["subnets"][0]["instances"][0]["uuid"],
        "teardown_at": unbounded_teardown,
    }

    with pytest.raises(ValueError, match="397-day maximum"):
        _prepare(generation, variables, ops, capability=capability)

    assert ops.values == {}


def test_cleanup_deletes_every_secret_for_the_generation():
    from vpn_access import cleanup_openvpn_access

    generation = uuid4()
    ops = MemorySecretOps()
    _prepare(generation, _variables(), ops)

    cleanup_openvpn_access(42, str(generation), ops)

    assert ops.deleted == [(42, str(generation))]
    assert ops.values == {}


def test_completed_generation_replay_keeps_the_same_issuer_and_runtime_material():
    from vpn_access import finalize_openvpn_access

    generation = uuid4()
    variables = _variables()
    ops = MemorySecretOps()
    capability = _capability(variables)
    preparation = _prepare(generation, variables, ops, capability=capability)
    first_binding = finalize_openvpn_access(
        preparation,
        {
            "endpoint": "vpn.example.test",
            "port": 1194,
            "target_ref": variables["subnets"][0]["instances"][0]["uuid"],
            "ready": True,
        },
        ops,
    )
    first_profile = ops.values[f"profile:42:{generation}"]

    replay = _prepare(generation, variables, ops, capability=capability)
    replay_binding = finalize_openvpn_access(
        replay,
        {
            "endpoint": "vpn.example.test",
            "port": 1194,
            "target_ref": variables["subnets"][0]["instances"][0]["uuid"],
            "ready": True,
        },
        ops,
    )

    assert replay == preparation
    assert replay_binding == first_binding
    assert ops.values[f"profile:42:{generation}"] == first_profile
    assert f"issuer:42:{generation}" in ops.values
    assert f"server:42:{generation}" in ops.values
    assert f"profile:42:{generation}" in ops.values
