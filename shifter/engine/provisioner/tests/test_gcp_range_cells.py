"""Tests for the GCE range-cell backend."""

from __future__ import annotations

import dataclasses
import ipaddress
import sys
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock, call

import pytest
from shared.range_cells import (
    RangeCellContractError,
    build_gcp_vm_range_cell_request,
    build_scenario_artifact,
    validate_gcp_vm_range_cell_result,
)
from shared.remote_access import build_openvpn_capability

from config import GCERangeCellConfig, GCERangeImageProfile
from gcp_range_cell_outputs import InstanceCredentials, instance_output
from gcp_range_cells import (
    GCEGuestSecretOps,
    GCEVertexCredentialOps,
    _build_clients,
    _ensure_instance,
    _ensure_openvpn_gateway,
    apply_range_cell,
    destroy_range_cell,
    render_range_cell_plan,
)
from gcp_vpn_identity import gcp_vpn_gateway_service_account_email
from state_helpers import _build_instance_state


class NotFound(Exception):
    """Fake Google NotFound exception."""


_POLARIS_SUBNETWORK_SELF_LINK = "projects/test-project/regions/us-central1/subnetworks/shifter-r-42-polaris"
_LINUX_UUID = "11111111-1111-4111-8111-111111111111"


def _sample_config() -> GCERangeCellConfig:
    return GCERangeCellConfig(
        project_id="test-project",
        region="us-central1",
        zone="us-central1-b",
        network_mode="vpc-per-range",
        service_account_email="range-host@test-project.iam.gserviceaccount.com",
        linux=GCERangeImageProfile(
            source_image="projects/debian-cloud/global/images/family/debian-12",
            machine_type="e2-standard-2",
            disk_size_gb=50,
        ),
        kali=GCERangeImageProfile(
            source_image="projects/kali/global/images/kali",
            machine_type="e2-standard-4",
            disk_size_gb=80,
        ),
        dc=GCERangeImageProfile(
            source_image="projects/windows-cloud/global/images/family/windows-2022",
            machine_type="e2-standard-4",
            disk_size_gb=100,
        ),
        image_key_profiles={
            "kali": {
                "polaris-vm": GCERangeImageProfile(
                    source_image="projects/shifter/global/images/polaris-vm",
                    machine_type="n2-standard-8",
                    disk_size_gb=200,
                ),
                "techvault": GCERangeImageProfile(
                    source_image="projects/shifter/global/images/techvault",
                    machine_type="n2-standard-8",
                    disk_size_gb=150,
                ),
            },
            "dc": {
                "polaris-dc": GCERangeImageProfile(
                    source_image="projects/shifter/global/images/polaris-dc",
                    machine_type="e2-standard-4",
                    disk_size_gb=100,
                )
            },
        },
        portal_network_cidrs=("10.40.0.0/20",),
    )


def _scenario_payload() -> dict:
    return {
        "scenario_id": "scenario-a",
        "user_id": 7,
        "subnets": [
            {
                "name": "polaris",
                "uuid": "subnet-uuid",
                "instances": [
                    {
                        "uuid": _LINUX_UUID,
                        "name": "kali",
                        "role": "attacker",
                        "os_type": "kali",
                    },
                    {
                        "uuid": "dc-uuid",
                        "name": "dc01",
                        "role": "dc",
                        "os_type": "windows",
                    },
                ],
            }
        ],
        "participant_access": [
            {"target_ref": _LINUX_UUID, "channel": "ssh"},
            {"target_ref": _LINUX_UUID, "channel": "rdp"},
        ],
    }


def _variables(
    *,
    payload: dict | None = None,
    bindings: list[dict] | None = None,
    remote_access: bool = False,
) -> dict:
    scenario_payload = deepcopy(payload if payload is not None else _scenario_payload())
    if bindings is None:
        bindings = [
            {
                "subnet_ref": subnet.get("uuid") or f"missing-{index}",
                "cidr": f"10.50.{index + 2}.0/28",
            }
            for index, subnet in enumerate(scenario_payload.get("subnets", []))
        ]
    return build_gcp_vm_range_cell_request(
        request_id="req-123",
        range_id=42,
        scenario_artifact=build_scenario_artifact(
            {"spec_schema": "range_spec", "spec_version": "1", "payload": scenario_payload}
        ),
        network_bindings=bindings,
        access_declarations=scenario_payload.get("participant_access", []),
        remote_access=(
            build_openvpn_capability(_LINUX_UUID, datetime.now(UTC) + timedelta(days=5)) if remote_access else None
        ),
    )


def _mock_clients(*, exists: bool = False) -> SimpleNamespace:
    def get_side_effect(**_kwargs):
        if exists:
            return object()
        raise NotFound()

    def service():
        svc = MagicMock()
        svc.get.side_effect = get_side_effect
        svc.insert.return_value = SimpleNamespace(name="op")
        svc.delete.return_value = SimpleNamespace(name="op")
        return svc

    op_service = MagicMock()
    op_service.wait.return_value = SimpleNamespace(status="DONE")
    return SimpleNamespace(
        networks=service(),
        subnetworks=service(),
        firewalls=service(),
        addresses=service(),
        instances=service(),
        global_operations=op_service,
        region_operations=op_service,
        zone_operations=op_service,
        google_exceptions=SimpleNamespace(NotFound=NotFound),
    )


def _mock_secret_ops(mocker) -> tuple[GCEGuestSecretOps, SimpleNamespace]:
    mocks = SimpleNamespace(
        ensure_ssh=mocker.Mock(return_value=("projects/test/secrets/host-ssh", "ssh-ed25519 HOST")),
        ensure_participant_ssh=mocker.Mock(
            return_value=("projects/test/secrets/participant-ssh", "ssh-ed25519 PARTICIPANT")
        ),
        ensure_rdp_password=mocker.Mock(return_value=("projects/test/secrets/rdp", "Password-1")),
        delete_ssh=mocker.Mock(),
        delete_participant_ssh=mocker.Mock(),
        delete_rdp_password=mocker.Mock(),
    )
    return (
        GCEGuestSecretOps(
            ensure_ssh=mocks.ensure_ssh,
            ensure_participant_ssh=mocks.ensure_participant_ssh,
            ensure_rdp_password=mocks.ensure_rdp_password,
            delete_ssh=mocks.delete_ssh,
            delete_participant_ssh=mocks.delete_participant_ssh,
            delete_rdp_password=mocks.delete_rdp_password,
        ),
        mocks,
    )


def _mock_vertex_ops(mocker) -> tuple[GCEVertexCredentialOps, SimpleNamespace]:
    mocks = SimpleNamespace(ensure=mocker.Mock(return_value="projects/test/secrets/vertex"), delete=mocker.Mock())
    return GCEVertexCredentialOps(ensure=mocks.ensure, delete=mocks.delete), mocks


def _vertex_config() -> GCERangeCellConfig:
    base = _sample_config()
    return GCERangeCellConfig(
        project_id=base.project_id,
        region=base.region,
        zone=base.zone,
        network_mode=base.network_mode,
        service_account_email=base.service_account_email,
        linux=base.linux,
        kali=base.kali,
        dc=base.dc,
        image_key_profiles=base.image_key_profiles,
        portal_network_cidrs=base.portal_network_cidrs,
        vertex_service_account_email="range-vertex@test-project.iam.gserviceaccount.com",
    )


def _shared_vpc_config() -> GCERangeCellConfig:
    base = _sample_config()
    return GCERangeCellConfig(
        project_id=base.project_id,
        region=base.region,
        zone=base.zone,
        network_mode="shared-vpc",
        network_id="projects/test-project/global/networks/shared-range",
        service_account_email=base.service_account_email,
        linux=base.linux,
        kali=base.kali,
        dc=base.dc,
        image_key_profiles=base.image_key_profiles,
        portal_network_cidrs=base.portal_network_cidrs,
    )


def test_render_range_cell_plan_shared_vpc_uses_existing_network():
    plan = render_range_cell_plan("req-123", _variables(), _shared_vpc_config())

    assert plan["manage_network"] is False
    assert plan["network"]["name"] == "shared-range"
    assert plan["network"]["self_link"] == "projects/test-project/global/networks/shared-range"
    # Per-range subnets are still created, but inside the shared VPC.
    assert plan["subnets"][0]["resource_name"] == "shifter-r-42-polaris"
    assert plan["subnets"][0]["network_link"] == "projects/test-project/global/networks/shared-range"


def test_render_range_cell_plan_vpc_per_range_mints_own_network():
    plan = render_range_cell_plan("req-123", _variables(), _sample_config())

    # vpc-per-range mode: the range owns (creates/deletes) its own VPC.
    assert plan["manage_network"] is True
    assert plan["network"]["name"] == "shifter-range-42"
    assert plan["network"]["self_link"] == "projects/test-project/global/networks/shifter-range-42"


def test_render_range_cell_plan_private_google_access_adds_egress_hole():
    config = dataclasses.replace(_sample_config(), private_google_access=True)

    plan = render_range_cell_plan("req-123", _variables(), config)

    firewall_names = {fw["name"] for fw in plan["firewalls"]}
    assert "shifter-r-42-egress-googleapis" in firewall_names


def test_render_range_cell_plan_private_google_access_adds_target_only_vpn_gateway():
    config = dataclasses.replace(_shared_vpc_config(), private_google_access=True)

    plan = render_range_cell_plan("req-123", _variables(remote_access=True), config)

    gateway = plan["vpn_gateway"]
    assert gateway["target_ref"] == _LINUX_UUID
    assert gateway["target_ip"] == "10.50.2.3"
    assert gateway["service_account_email"] == gcp_vpn_gateway_service_account_email("test-project", 42, "req-123")
    assert gateway["private_ip"] not in plan["subnets"][0]["ip_assignments"].values()
    firewalls = {rule["name"]: rule for rule in plan["firewalls"]}
    vpn_sources = [ipaddress.ip_network(cidr) for cidr in firewalls["shifter-r-42-vpn-in"]["source_ranges"]]
    assert any(ipaddress.ip_address("8.8.8.8") in cidr for cidr in vpn_sources)
    assert all(not cidr.overlaps(ipaddress.ip_network("10.0.0.0/8")) for cidr in vpn_sources)
    assert firewalls["shifter-r-42-vpn-in"]["allowed"] == [{"IPProtocol": "udp", "ports": ["1194"]}]
    assert firewalls["shifter-r-42-vpn-health"]["source_ranges"] == ["10.40.0.0/20"]
    assert firewalls["shifter-r-42-vpn-health"]["allowed"] == [{"IPProtocol": "tcp", "ports": ["1195"]}]
    assert firewalls["shifter-r-42-vpn-target"]["destination_ranges"] == ["10.50.2.3/32"]
    assert firewalls["shifter-r-42-vpn-deny"]["denied"] == [{"IPProtocol": "all"}]


def test_topology_without_capability_does_not_create_a_vpn_gateway():
    config = dataclasses.replace(_shared_vpc_config(), private_google_access=True)

    plan = render_range_cell_plan("req-123", _variables(), config)

    assert "vpn_gateway" not in plan


def test_gcp_gateway_result_stays_pending_until_external_service_probe():
    config = dataclasses.replace(_shared_vpc_config(), private_google_access=True)
    plan = render_range_cell_plan("req-123", _variables(remote_access=True), config)
    clients = _mock_clients(exists=True)
    clients.addresses.get.side_effect = None
    clients.addresses.get.return_value = object()
    clients.instances.get.side_effect = None
    clients.instances.get.return_value = SimpleNamespace(
        network_interfaces=[SimpleNamespace(access_configs=[SimpleNamespace(nat_i_p="203.0.113.10")])]
    )

    gateway = _ensure_openvpn_gateway(plan, clients, config)

    assert gateway == {
        "endpoint": "203.0.113.10",
        "port": 1194,
        "health_endpoint": plan["vpn_gateway"]["private_ip"],
        "health_port": 1195,
        "target_ref": _LINUX_UUID,
        "ready": False,
    }


def test_render_range_cell_plan_rejects_subnet_without_uuid():
    payload = _scenario_payload()
    del payload["subnets"][0]["uuid"]
    variables = _variables(payload=payload)
    config = _sample_config()

    with pytest.raises(RuntimeError, match="requires name and uuid"):
        render_range_cell_plan("req-123", variables, config)


def test_render_range_cell_plan_rejects_subnet_without_cidr_when_images_required():
    variables = _variables(bindings=[])
    config = _sample_config()

    with pytest.raises(RuntimeError, match="requires a network binding"):
        render_range_cell_plan("req-123", variables, config)


def test_apply_shared_vpc_skips_network_create(mocker):
    clients = _mock_clients(exists=False)
    secret_ops, _ = _mock_secret_ops(mocker)
    vertex_ops, _ = _mock_vertex_ops(mocker)

    apply_range_cell(
        "req-123",
        _variables(),
        config=_shared_vpc_config(),
        clients=clients,
        secret_ops=secret_ops,
        vertex_ops=vertex_ops,
    )

    clients.networks.insert.assert_not_called()
    clients.subnetworks.insert.assert_called()


def test_destroy_shared_vpc_skips_network_delete(mocker):
    clients = _mock_clients(exists=True)
    secret_ops, _ = _mock_secret_ops(mocker)
    vertex_ops, _ = _mock_vertex_ops(mocker)

    destroy_range_cell(
        "req-123",
        _variables(),
        config=_shared_vpc_config(),
        clients=clients,
        secret_ops=secret_ops,
        vertex_ops=vertex_ops,
    )

    clients.networks.delete.assert_not_called()
    clients.subnetworks.delete.assert_called()


def test_apply_mints_per_range_vertex_key_when_configured(mocker):
    clients = _mock_clients(exists=True)
    secret_ops, _ = _mock_secret_ops(mocker)
    vertex_ops, vertex_mocks = _mock_vertex_ops(mocker)

    apply_range_cell(
        "req-123",
        _variables(),
        config=_vertex_config(),
        clients=clients,
        secret_ops=secret_ops,
        vertex_ops=vertex_ops,
    )

    vertex_mocks.ensure.assert_called_once_with(
        42,
        "range-vertex@test-project.iam.gserviceaccount.com",
        "test-project",
        "range-host@test-project.iam.gserviceaccount.com",
    )


def test_apply_skips_vertex_key_when_not_configured(mocker):
    clients = _mock_clients(exists=True)
    secret_ops, _ = _mock_secret_ops(mocker)
    vertex_ops, vertex_mocks = _mock_vertex_ops(mocker)

    apply_range_cell(
        "req-123",
        _variables(),
        config=_sample_config(),
        clients=clients,
        secret_ops=secret_ops,
        vertex_ops=vertex_ops,
    )

    vertex_mocks.ensure.assert_not_called()


def test_destroy_deletes_per_range_vertex_key(mocker):
    clients = _mock_clients(exists=True)
    secret_ops, _ = _mock_secret_ops(mocker)
    vertex_ops, vertex_mocks = _mock_vertex_ops(mocker)

    destroy_range_cell(
        "req-123",
        _variables(),
        config=_vertex_config(),
        clients=clients,
        secret_ops=secret_ops,
        vertex_ops=vertex_ops,
    )

    vertex_mocks.delete.assert_called_once_with(42, "test-project")


def test_render_range_cell_plan_uses_vpc_per_range_and_deterministic_ips():
    plan = render_range_cell_plan("req-123", _variables(), _sample_config())

    assert plan["network"]["name"] == "shifter-range-42"
    assert plan["subnets"][0]["resource_name"] == "shifter-r-42-polaris"
    assert plan["subnets"][0]["ip_assignments"] == {
        _LINUX_UUID: "10.50.2.3",
        "dc-uuid": "10.50.2.4",
    }
    assert [instance["private_ip"] for instance in plan["instances"]] == ["10.50.2.3", "10.50.2.4"]
    assert {firewall["name"] for firewall in plan["firewalls"]} >= {
        "shifter-r-42-polaris-ingress",
        "shifter-r-42-mgmt",
        "shifter-r-42-egress-internal",
        "shifter-r-42-egress-deny",
    }


def _firewall_by_name(plan: dict, suffix: str) -> dict:
    return next(fw for fw in plan["firewalls"] if fw["name"] == f"shifter-r-42-{suffix}")


def test_dedicated_access_cidrs_split_participant_ingress_from_management():
    # Issue #1349: with a dedicated access-workload source, participant ingress
    # (SSH/RDP) is its own rule sourced only from the access ranges, and range
    # management ingress is a separate rule on portal_network_cidrs -- participant
    # access is never a management wildcard.
    config = dataclasses.replace(
        _sample_config(),
        portal_network_cidrs=("10.40.0.0/20",),
        access_network_cidrs=("10.41.0.0/24",),
    )
    plan = render_range_cell_plan("req-123", _variables(), config)

    access = _firewall_by_name(plan, "access")
    assert access["source_ranges"] == ["10.41.0.0/24"]
    assert access["allowed"] == [{"IPProtocol": "tcp", "ports": ["22", "3389"]}]

    mgmt = _firewall_by_name(plan, "mgmt")
    assert mgmt["source_ranges"] == ["10.40.0.0/20"]
    # Management ingress carries host SSH + the Docker-host mgmt port, never RDP.
    assert "3389" not in mgmt["allowed"][0]["ports"]
    assert "22" in mgmt["allowed"][0]["ports"]
    assert str(config.host_mgmt_ssh_port) in mgmt["allowed"][0]["ports"]

    # Participant RDP is not reachable from the broad management source range.
    assert all(
        "10.40.0.0/20" not in fw["source_ranges"]
        for fw in plan["firewalls"]
        if "3389" in fw.get("allowed", [{}])[0].get("ports", [])
    )


def test_range_cell_firewalls_do_not_allow_cross_range_private_traffic():
    first_variables = _variables()
    second_variables = deepcopy(first_variables)
    second_variables["operation"]["range_id"] = 43
    second_variables["network_bindings"][0]["cidr"] = "10.50.3.0/28"

    first = render_range_cell_plan("req-123", first_variables, _sample_config())
    second = render_range_cell_plan("req-123", second_variables, _sample_config())

    first_allowed = [rule for rule in first["firewalls"] if "allowed" in rule]
    second_cidr = second["subnets"][0]["cidr"]
    assert all(second_cidr not in rule.get("source_ranges", []) for rule in first_allowed)
    assert all(second_cidr not in rule.get("destination_ranges", []) for rule in first_allowed)
    assert {tag for rule in first["firewalls"] for tag in rule["target_tags"]}.isdisjoint(
        {tag for rule in second["firewalls"] for tag in rule["target_tags"]}
    )


def test_range_cell_firewalls_are_deterministic_from_cell_identity():
    variables = _variables()
    config = dataclasses.replace(_sample_config(), egress_allow_cidrs=("10.60.0.10/32",))

    first = render_range_cell_plan("req-123", variables, config)
    second = render_range_cell_plan("req-123", deepcopy(variables), config)

    assert first["firewalls"] == second["firewalls"]
    assert all(rule["target_tags"][0].startswith("shifter-range-42") for rule in first["firewalls"])


@pytest.mark.parametrize("field", ["portal_network_cidrs", "access_network_cidrs", "egress_allow_cidrs"])
def test_range_cell_firewalls_reject_universal_allow_cidrs(field):
    config = dataclasses.replace(_sample_config(), **{field: ("0.0.0.0/0",)})
    variables = _variables()

    with pytest.raises(RuntimeError, match=r"must not include 0\.0\.0\.0/0"):
        render_range_cell_plan("req-123", variables, config)


@pytest.mark.parametrize(
    ("field", "cidr", "message"),
    [
        ("portal_network_cidrs", "10.40.0.1/20", "invalid network"),
        ("access_network_cidrs", "10.40.0.1/20", "invalid network"),
        ("egress_allow_cidrs", "2001:db8::/64", "only IPv4"),
    ],
)
def test_range_cell_firewalls_reject_malformed_boundary_cidrs(field, cidr, message):
    config = dataclasses.replace(_sample_config(), **{field: (cidr,)})
    variables = _variables()

    with pytest.raises(RuntimeError, match=message):
        render_range_cell_plan("req-123", variables, config)


def test_range_cell_firewalls_deduplicate_explicit_egress_cidrs():
    config = dataclasses.replace(_sample_config(), egress_allow_cidrs=("10.60.0.0/24", "10.60.0.0/24"))

    plan = render_range_cell_plan("req-123", _variables(), config)
    egress = next(rule for rule in plan["firewalls"] if rule["name"].endswith("-egress-allow"))

    assert egress["destination_ranges"] == ["10.60.0.0/24"]


def test_range_cell_rule_count_is_bounded_per_cell_not_per_instance():
    payload = _scenario_payload()
    base_instances = payload["subnets"][0]["instances"]
    payload["subnets"][0]["instances"] = [deepcopy(base_instances[index % 2]) for index in range(50)]
    for index, instance in enumerate(payload["subnets"][0]["instances"]):
        instance["uuid"] = f"instance-{index}"
        instance["name"] = f"guest-{index}"
    payload["participant_access"] = []

    plan = render_range_cell_plan(
        "req-123",
        _variables(payload=payload, bindings=[{"subnet_ref": "subnet-uuid", "cidr": "10.50.2.0/24"}]),
        _sample_config(),
    )

    assert len(plan["instances"]) == 50
    assert len(plan["firewalls"]) == len(plan["subnets"]) + 3


def test_base_firewall_templates_stay_at_three_rules_for_101_single_subnet_cells():
    config = dataclasses.replace(_shared_vpc_config(), portal_network_cidrs=())
    names: set[str] = set()
    rule_count = 0
    for offset in range(101):
        variables = _variables()
        variables["operation"]["range_id"] = offset + 1
        variables["network_bindings"][0]["cidr"] = f"10.50.{offset // 16}.{(offset % 16) * 16}/28"
        firewalls = render_range_cell_plan("req-123", variables, config)["firewalls"]
        rule_count += len(firewalls)
        names.update(rule["name"] for rule in firewalls)

    assert rule_count == 303
    assert len(names) == rule_count


def test_only_polaris_docker_host_requires_the_host_service_account():
    payload = _scenario_payload()
    payload["subnets"][0]["instances"][0]["ami_key"] = "polaris-vm"

    plan = render_range_cell_plan("req-123", _variables(payload=payload), _sample_config())
    by_name = {instance["name"]: instance for instance in plan["instances"]}

    assert by_name["kali"]["attach_service_account"] is True
    assert by_name["dc01"]["attach_service_account"] is False


def test_instance_output_reports_service_account_only_for_polaris_host():
    payload = _scenario_payload()
    payload["subnets"][0]["instances"][0]["ami_key"] = "polaris-vm"
    config = _sample_config()
    plan = render_range_cell_plan("req-123", _variables(payload=payload), config)
    by_name = {instance["name"]: instance for instance in plan["instances"]}
    credentials = InstanceCredentials(
        host_ssh_secret_ref="projects/test/secrets/host-ssh",
        participant_ssh_secret_ref=None,
        rdp_password_secret_ref=None,
        ssh_public_key="ssh-ed25519 HOST",
    )

    host_output = instance_output(plan, by_name["kali"], credentials, config)
    native_output = instance_output(plan, by_name["dc01"], credentials, config)

    assert host_output["gcp_service_account_email"] == config.service_account_email
    assert native_output["gcp_service_account_email"] == ""


def test_render_plan_destroy_tolerates_missing_subnet_cidr():
    # Auto-cleanup after a provision that failed before CIDR allocation renders
    # the destroy plan with require_images=False; the subnet is deleted by
    # resource name, so an empty CIDR must not raise.
    variables = _variables(bindings=[])
    plan = render_range_cell_plan("req-123", variables, _sample_config(), require_images=False)
    subnet = plan["subnets"][0]
    assert subnet["cidr"] == ""
    assert subnet["ip_assignments"] == {}
    assert subnet["resource_name"]


def test_render_plan_provision_requires_subnet_cidr():
    variables = _variables(bindings=[])
    config = _sample_config()
    with pytest.raises(RuntimeError, match="requires a network binding"):
        render_range_cell_plan("req-123", variables, config)


def test_render_plan_requires_subnet_name_and_uuid():
    # name/uuid identify the subnet for both provision and destroy, so they are
    # required in either mode.
    payload = _scenario_payload()
    payload["subnets"][0]["uuid"] = ""
    variables = _variables(payload=payload, bindings=[])
    config = _sample_config()
    with pytest.raises(RuntimeError, match="requires name and uuid"):
        render_range_cell_plan("req-123", variables, config, require_images=False)


def test_render_plan_translates_polaris_vm_to_docker_host_access():
    """A polaris-vm Docker host uses the host login user + management sshd port.

    The Kali participant container publishes the host's :22/:3389, so the
    provisioner must drive the host sshd on the management port as the host
    login user, not the participant "kali" user.
    """
    payload = _scenario_payload()
    kali = payload["subnets"][0]["instances"][0]
    kali["ami_key"] = "polaris-vm"
    kali["instance_type"] = "m5.2xlarge"  # AWS shape; must NOT reach GCE.
    variables = _variables(payload=payload)

    config = GCERangeCellConfig(
        project_id="test-project",
        region="us-central1",
        zone="us-central1-b",
        network_mode="vpc-per-range",
        service_account_email="range-host@test-project.iam.gserviceaccount.com",
        kali=GCERangeImageProfile(
            source_image="projects/shifter/global/images/polaris-vm",
            machine_type="n2-standard-8",
            disk_size_gb=200,
        ),
        dc=GCERangeImageProfile(
            source_image="projects/shifter/global/images/polaris-dc",
            machine_type="e2-standard-4",
            disk_size_gb=100,
        ),
        image_key_profiles={
            "kali": {
                "polaris-vm": GCERangeImageProfile(
                    source_image="projects/shifter/global/images/polaris-vm",
                    machine_type="n2-standard-8",
                    disk_size_gb=200,
                )
            }
        },
        host_mgmt_ssh_port=2222,
    )

    plan = render_range_cell_plan("req-123", variables, config)
    host = plan["instances"][0]

    # Participant reaches the Kali container as "kali" on :22; the provisioner
    # drives the Ubuntu host sshd as "ubuntu" on the management port.
    assert host["ssh_username"] == "kali"
    assert host["host_ssh_username"] == "ubuntu"
    assert host["ssh_port"] == 2222
    # AWS instance_type is ignored; machine size comes from the GCE profile.
    assert host["profile"].machine_type == "n2-standard-8"
    assert host["image_key"] == "polaris-vm"
    assert len(host["image_profile_fingerprint"]) == 24


def test_existing_keyed_instance_rejects_profile_drift_before_secret_mutation(mocker):
    payload = _scenario_payload()
    payload["subnets"][0]["instances"][0]["ami_key"] = "polaris-vm"
    config = _sample_config()
    plan = render_range_cell_plan("req-123", _variables(payload=payload), config)
    instance = plan["instances"][0]
    clients = _mock_clients(exists=False)
    clients.instances.get.side_effect = None
    clients.instances.get.return_value = SimpleNamespace(
        labels={"image-key": "polaris-vm", "image-profile": "wrong-profile"}
    )
    secret_ops, secret_mocks = _mock_secret_ops(mocker)

    with pytest.raises(RuntimeError, match="image-profile binding"):
        _ensure_instance(plan, clients, config, instance, secret_ops)

    secret_mocks.ensure_ssh.assert_not_called()


def test_render_plan_resolves_distinct_images_for_same_role_by_ami_key():
    payload = _scenario_payload()
    polaris = payload["subnets"][0]["instances"][0]
    polaris["ami_key"] = "polaris-vm"
    techvault = deepcopy(polaris)
    techvault.update(
        {
            "uuid": "33333333-3333-4333-8333-333333333333",
            "name": "techvault",
            "ami_key": "techvault",
        }
    )
    payload["subnets"][0]["instances"].append(techvault)
    config = dataclasses.replace(
        _sample_config(),
        image_key_profiles={
            "kali": {
                "polaris-vm": GCERangeImageProfile(
                    source_image="projects/test/global/images/family/shifter-polaris-vm",
                    machine_type="e2-standard-8",
                    disk_size_gb=210,
                ),
                "techvault": GCERangeImageProfile(
                    source_image="projects/test/global/images/family/shifter-techvault",
                    machine_type="n2-standard-8",
                    disk_size_gb=150,
                ),
            }
        },
    )

    plan = render_range_cell_plan("req-123", _variables(payload=payload), config)
    by_name = {instance["name"]: instance for instance in plan["instances"]}

    assert by_name["kali"]["profile"].source_image.endswith("shifter-polaris-vm")
    assert by_name["kali"]["profile"].disk_size_gb == 210
    assert by_name["techvault"]["profile"].source_image.endswith("shifter-techvault")
    assert by_name["techvault"]["profile"].disk_size_gb == 150


def test_mgmt_firewall_opens_host_management_ssh_port():
    """The management ingress rule opens SSH, RDP, and the Docker-host mgmt port."""
    config = GCERangeCellConfig(
        project_id="test-project",
        region="us-central1",
        zone="us-central1-b",
        network_mode="vpc-per-range",
        service_account_email="range-host@test-project.iam.gserviceaccount.com",
        kali=GCERangeImageProfile(source_image="projects/shifter/global/images/polaris-vm"),
        dc=GCERangeImageProfile(source_image="projects/shifter/global/images/polaris-dc"),
        portal_network_cidrs=("10.40.0.0/20",),
        host_mgmt_ssh_port=2222,
    )
    plan = render_range_cell_plan("req-123", _variables(), config)
    mgmt = next(fw for fw in plan["firewalls"] if fw["name"] == "shifter-r-42-mgmt")

    assert mgmt["allowed"] == [{"IPProtocol": "tcp", "ports": ["22", "3389", "2222"]}]


def test_instance_resource_installs_key_for_host_login_user():
    """GCE ssh-keys metadata installs the key for the host user the provisioner drives.

    Regression: for a Docker-host guest the provisioner connects as the host
    user (ubuntu), not the participant user (kali) whose key the container's
    authorized_keys carries; installing the key for kali would leave host setup
    unable to SSH in.
    """
    from gcp_range_cell_resources import instance_resource

    payload = _scenario_payload()
    payload["subnets"][0]["instances"][0]["ami_key"] = "polaris-vm"
    variables = _variables(payload=payload)
    plan = render_range_cell_plan("req-123", variables, _vertex_config())
    host = plan["instances"][0]

    body = instance_resource(plan, host, _vertex_config(), ssh_public_key="ssh-ed25519 AAAA")
    ssh_keys = next(item for item in body["metadata"]["items"] if item["key"] == "ssh-keys")

    assert ssh_keys["value"] == "ubuntu:ssh-ed25519 AAAA"
    assert body["labels"]["image-key"] == "polaris-vm"
    assert body["labels"]["image-profile"] == host["image_profile_fingerprint"]


def test_windows_dc_instance_gets_boot_firewall_script():
    """The Windows DC gets a per-boot startup script (firewall off + sshd) so the
    provisioner's SSH reaches it even if promotion re-enables the firewall; the
    Linux host does not."""
    from gcp_range_cell_resources import instance_resource

    plan = render_range_cell_plan("req-123", _variables(), _vertex_config())
    by_name = {inst["name"]: inst for inst in plan["instances"]}

    dc_body = instance_resource(plan, by_name["dc01"], _vertex_config(), ssh_public_key="ssh-ed25519 AAAA")
    dc_meta = {item["key"]: item["value"] for item in dc_body["metadata"]["items"]}
    assert "windows-startup-script-ps1" in dc_meta
    assert "Set-NetFirewallProfile" in dc_meta["windows-startup-script-ps1"]
    assert "sshd" in dc_meta["windows-startup-script-ps1"]

    host_body = instance_resource(plan, by_name["kali"], _vertex_config(), ssh_public_key="ssh-ed25519 AAAA")
    host_meta = {item["key"]: item["value"] for item in host_body["metadata"]["items"]}
    assert "windows-startup-script-ps1" not in host_meta


def test_instance_resource_injects_ssh_host_key_per_os():
    """The provisioner-issued SSH host key is installed via the guest startup
    script (Windows: ProgramData\\ssh; Linux: /etc/ssh) and its public half is
    surfaced in metadata so the setup runner can seed known_hosts."""
    from gcp_range_cell_resources import HOST_PUBLIC_KEY_METADATA_KEY, instance_resource

    plan = render_range_cell_plan("req-123", _variables(), _vertex_config())
    by_name = {inst["name"]: inst for inst in plan["instances"]}

    dc_body = instance_resource(
        plan,
        by_name["dc01"],
        _vertex_config(),
        ssh_public_key="ssh-ed25519 AAAA",
        host_private_key_b64="UFJJVg==",
        host_public_key="ssh-ed25519 HOSTKEY dc",
    )
    dc_meta = {item["key"]: item["value"] for item in dc_body["metadata"]["items"]}
    assert dc_meta[HOST_PUBLIC_KEY_METADATA_KEY] == "ssh-ed25519 HOSTKEY dc"
    assert "ssh_host_ed25519_key" in dc_meta["windows-startup-script-ps1"]
    assert "UFJJVg==" in dc_meta["windows-startup-script-ps1"]
    # Windows OpenSSH ignores ssh-keys metadata for admins, so the provisioner's
    # public key must be authorized via administrators_authorized_keys.
    assert "administrators_authorized_keys" in dc_meta["windows-startup-script-ps1"]
    assert "ssh-ed25519 AAAA" in dc_meta["windows-startup-script-ps1"]

    host_body = instance_resource(
        plan,
        by_name["kali"],
        _vertex_config(),
        ssh_public_key="ssh-ed25519 AAAA",
        host_private_key_b64="TElOVVg=",
        host_public_key="ssh-ed25519 HOSTKEY kali",
    )
    host_meta = {item["key"]: item["value"] for item in host_body["metadata"]["items"]}
    assert host_meta[HOST_PUBLIC_KEY_METADATA_KEY] == "ssh-ed25519 HOSTKEY kali"
    assert "/etc/ssh/ssh_host_ed25519_key" in host_meta["startup-script"]
    assert "TElOVVg=" in host_meta["startup-script"]


def test_apply_emits_gcp_host_public_key(mocker):
    """A created instance surfaces gcp_host_public_key so the factory can seed
    known_hosts for StrictHostKeyChecking."""
    clients = _mock_clients(exists=False)
    secret_ops, _ = _mock_secret_ops(mocker)
    vertex_ops, _ = _mock_vertex_ops(mocker)

    output = apply_range_cell(
        "req-123",
        _variables(),
        config=_sample_config(),
        clients=clients,
        secret_ops=secret_ops,
        vertex_ops=vertex_ops,
    )

    for instance in output["instances"]:
        assert instance["gcp_host_public_key"].startswith("ssh-ed25519 ")


def test_apply_emits_closed_lifecycle_membership_and_access_result(mocker):
    clients = _mock_clients(exists=False)
    secret_ops, _ = _mock_secret_ops(mocker)
    vertex_ops, _ = _mock_vertex_ops(mocker)

    output = apply_range_cell(
        "req-123",
        _variables(),
        config=_sample_config(),
        clients=clients,
        secret_ops=secret_ops,
        vertex_ops=vertex_ops,
    )

    result = validate_gcp_vm_range_cell_result(output["range_cell"])
    assert result["cell"] == {
        "cell_id": "gcp:test-project:us-central1:42",
        "provider": "gcp",
        "backend": "gce",
        "lifecycle_state": "ready",
        "subnet_refs": ["subnet-uuid"],
    }
    assert {member["authored_ref"] for member in result["members"]} == {_LINUX_UUID, "dc-uuid"}
    assert {(record["target_ref"], record["channel"]) for record in result["access"]} == {
        (_LINUX_UUID, "ssh"),
        (_LINUX_UUID, "rdp"),
    }
    assert result["access"][0]["credential_ref"] == "projects/test/secrets/participant-ssh"
    assert "host-ssh" not in repr(result)
    assert "Password-1" not in repr(result)


def test_generated_host_credentials_do_not_authorize_participant_access(mocker):
    clients = _mock_clients(exists=False)
    secret_ops, secret_mocks = _mock_secret_ops(mocker)
    payload = _scenario_payload()
    payload["participant_access"] = []

    output = apply_range_cell(
        "req-123",
        _variables(payload=payload),
        config=_sample_config(),
        clients=clients,
        secret_ops=secret_ops,
    )

    result = validate_gcp_vm_range_cell_result(output["range_cell"])
    assert result["access"] == []
    assert all(instance["ssh_key_secret_arn"] == "" for instance in output["instances"])
    assert all(instance["gcp_host_ssh_key_secret_ref"] for instance in output["instances"])
    secret_mocks.ensure_participant_ssh.assert_not_called()


def test_contract_validation_precedes_every_gce_client_mutation(mocker):
    clients = _mock_clients(exists=False)
    secret_ops, secret_mocks = _mock_secret_ops(mocker)
    vertex_ops, vertex_mocks = _mock_vertex_ops(mocker)
    malformed = _variables() | {"unexpected": True}
    config = _sample_config()

    with pytest.raises(RangeCellContractError, match="unexpected field"):
        apply_range_cell(
            "req-123",
            malformed,
            config=config,
            clients=clients,
            secret_ops=secret_ops,
            vertex_ops=vertex_ops,
        )

    clients.networks.insert.assert_not_called()
    clients.subnetworks.insert.assert_not_called()
    clients.firewalls.insert.assert_not_called()
    clients.addresses.insert.assert_not_called()
    clients.instances.insert.assert_not_called()
    secret_mocks.ensure_ssh.assert_not_called()
    secret_mocks.ensure_participant_ssh.assert_not_called()
    secret_mocks.ensure_rdp_password.assert_not_called()
    vertex_mocks.ensure.assert_not_called()


def test_outer_access_cannot_expand_digest_bound_scenario_authorization(mocker):
    clients = _mock_clients(exists=False)
    secret_ops, secret_mocks = _mock_secret_ops(mocker)
    variables = _variables()
    variables["access_declarations"] = [{"target_ref": "dc-uuid", "channel": "ssh"}]
    config = _sample_config()

    with pytest.raises(RangeCellContractError, match="do not match the digest-bound scenario artifact"):
        apply_range_cell(
            "req-123",
            variables,
            config=config,
            clients=clients,
            secret_ops=secret_ops,
        )

    clients.instances.insert.assert_not_called()
    secret_mocks.ensure_ssh.assert_not_called()
    secret_mocks.ensure_participant_ssh.assert_not_called()


@pytest.mark.parametrize(
    ("instances", "message"),
    [
        (["not-an-object"], "canonical validation"),
        ([{"name": "missing-ref", "role": "victim", "os_type": "ubuntu"}], "requires a uuid"),
        (
            [
                {"name": "first", "uuid": "duplicate", "role": "victim", "os_type": "ubuntu"},
                {"name": "second", "uuid": "duplicate", "role": "victim", "os_type": "ubuntu"},
            ],
            "duplicate authored instance uuid",
        ),
    ],
)
def test_scenario_adapter_rejects_invalid_membership_before_provider_mutation(mocker, instances, message):
    clients = _mock_clients(exists=False)
    secret_ops, secret_mocks = _mock_secret_ops(mocker)
    vertex_ops, vertex_mocks = _mock_vertex_ops(mocker)
    payload = _scenario_payload()
    payload["subnets"][0]["instances"] = instances
    payload["participant_access"] = []
    config = _sample_config()

    def apply_invalid_payload():
        variables = _variables(payload=payload)
        apply_range_cell(
            "req-123",
            variables,
            config=config,
            clients=clients,
            secret_ops=secret_ops,
            vertex_ops=vertex_ops,
        )

    with pytest.raises(RangeCellContractError, match=message):
        apply_invalid_payload()

    clients.networks.insert.assert_not_called()
    clients.subnetworks.insert.assert_not_called()
    clients.firewalls.insert.assert_not_called()
    clients.addresses.insert.assert_not_called()
    clients.instances.insert.assert_not_called()
    secret_mocks.ensure_ssh.assert_not_called()
    secret_mocks.ensure_participant_ssh.assert_not_called()
    secret_mocks.ensure_rdp_password.assert_not_called()
    vertex_mocks.ensure.assert_not_called()


def test_render_plan_carries_private_google_access_flag():
    """Private Google Access flows from config into the subnet resource body."""
    from gcp_range_cell_resources import subnetwork_resource

    config = GCERangeCellConfig(
        project_id="test-project",
        region="us-central1",
        zone="us-central1-b",
        network_mode="vpc-per-range",
        service_account_email="range-host@test-project.iam.gserviceaccount.com",
        kali=GCERangeImageProfile(source_image="projects/shifter/global/images/polaris-vm"),
        dc=GCERangeImageProfile(source_image="projects/shifter/global/images/polaris-dc"),
        private_google_access=True,
    )
    plan = render_range_cell_plan("req-123", _variables(), config)

    assert plan["private_google_access"] is True
    body = subnetwork_resource(plan, plan["subnets"][0])
    assert body["private_ip_google_access"] is True
    assert body["ip_cidr_range"] == "10.50.2.0/28"

    # PGA couples an egress-allow to the private.googleapis.com VIP so guests can
    # reach Vertex / GCS / Secret Manager while the egress-deny blocks the
    # general internet.
    gapi = next(fw for fw in plan["firewalls"] if fw["name"].endswith("-egress-googleapis"))
    assert gapi["direction"] == "EGRESS"
    assert gapi["destination_ranges"] == ["199.36.153.8/30"]
    assert gapi["allowed"] == [{"IPProtocol": "tcp", "ports": ["443"]}]


def test_render_plan_omits_googleapis_egress_without_private_google_access():
    """Without Private Google Access the range opens no Google-API egress hole."""
    plan = render_range_cell_plan("req-123", _variables(), _vertex_config())
    assert not any(fw["name"].endswith("-egress-googleapis") for fw in plan["firewalls"])


def test_resource_bodies_use_proto_field_names():
    """Compute resource bodies use google-cloud-compute proto (snake_case) field
    names, including the proto-plus quirks I_p_protocol and network_i_p, so the
    clients can construct the messages."""
    from gcp_range_cell_resources import firewall_resource, instance_resource, network_resource

    plan = render_range_cell_plan("req-123", _variables(), _vertex_config())

    net = network_resource(plan)
    assert "auto_create_subnetworks" in net
    assert net["routing_config"] == {"routing_mode": "REGIONAL"}

    mgmt = next(fw for fw in plan["firewalls"] if fw["name"].endswith("-mgmt"))
    fw_body = firewall_resource(plan, mgmt)
    assert fw_body["allowed"] == [{"I_p_protocol": "tcp", "ports": ["22", "3389", "2222"]}]
    assert "target_tags" in fw_body

    host = plan["instances"][0]
    body = instance_resource(plan, host, _vertex_config(), ssh_public_key="ssh-ed25519 AAAA")
    assert "machine_type" in body
    assert body["network_interfaces"][0]["network_i_p"] == host["private_ip"]
    assert isinstance(body["disks"][0]["initialize_params"]["disk_size_gb"], int)


def test_render_plan_keeps_native_guest_on_default_ssh_port():
    """Without a Docker-host ami_key, guests keep the participant user on :22."""
    plan = render_range_cell_plan("req-123", _variables(), _sample_config())
    host, dc = plan["instances"]

    assert host["ssh_username"] == "kali"
    assert host["host_ssh_username"] == "kali"
    assert host["ssh_port"] == 22
    assert dc["ssh_username"] == "Administrator"
    assert dc["host_ssh_username"] == "Administrator"
    assert dc["ssh_port"] == 22


def test_apply_range_cell_is_idempotent_when_resources_exist(mocker):
    clients = _mock_clients(exists=True)
    secret_ops, _mocks = _mock_secret_ops(mocker)
    expected_plan = render_range_cell_plan("req-123", _variables(), _sample_config())

    output = apply_range_cell(
        "req-123",
        _variables(),
        config=_sample_config(),
        clients=clients,
        secret_ops=secret_ops,
    )

    validate_gcp_vm_range_cell_result(output.pop("range_cell"))

    assert output == {
        "subnets": {
            "polaris": {
                "uuid": "subnet-uuid",
                "subnet_id": "shifter-r-42-polaris",
                "subnet_cidr": "10.50.2.0/28",
                "gcp_network_name": "shifter-range-42",
                "gcp_network_self_link": "projects/test-project/global/networks/shifter-range-42",
                "gcp_subnetwork_name": "shifter-r-42-polaris",
                "gcp_subnetwork_self_link": _POLARIS_SUBNETWORK_SELF_LINK,
                "gcp_region": "us-central1",
                "gcp_gateway_reserved": True,
                "gcp_instance_ip_assignments": {
                    _LINUX_UUID: "10.50.2.3",
                    "dc-uuid": "10.50.2.4",
                },
            }
        },
        "instances": [
            {
                "uuid": _LINUX_UUID,
                "name": "kali",
                "asset_type": "gce_vm",
                "role": "attacker",
                "os": "kali",
                "subnet_name": "polaris",
                "instance_id": "shifter-r-42-polaris-kali",
                "private_ip": "10.50.2.3",
                "participant_access_channels": ["ssh", "rdp"],
                "ssh_key_secret_arn": "projects/test/secrets/participant-ssh",
                "ssh_username": "kali",
                "public_key": "ssh-ed25519 HOST\nssh-ed25519 PARTICIPANT",
                "gcp_host_public_key": "",
                "gcp_host_ssh_key_secret_ref": "projects/test/secrets/host-ssh",
                "gcp_host_ssh_username": "kali",
                "gcp_host_ssh_port": 22,
                "gcp_project_id": "test-project",
                "gcp_region": "us-central1",
                "gcp_zone": "us-central1-b",
                "gcp_network_name": "shifter-range-42",
                "gcp_network_self_link": "projects/test-project/global/networks/shifter-range-42",
                "gcp_subnetwork_name": "shifter-r-42-polaris",
                "gcp_subnetwork_self_link": _POLARIS_SUBNETWORK_SELF_LINK,
                "gcp_instance_name": "shifter-r-42-polaris-kali",
                "gcp_address_name": "shifter-r-42-polaris-kali-ip",
                "gcp_network_tags": ["shifter-range-42", "shifter-range-42-polaris", "shifter-role-attacker"],
                "gcp_image_key": "default",
                "gcp_image_profile_fingerprint": expected_plan["instances"][0]["image_profile_fingerprint"],
                "gcp_source_image": "projects/kali/global/images/kali",
                "gcp_service_account_email": "",
                "rdp_password_secret_arn": "projects/test/secrets/rdp",
                "gcp_bootstrap_rdp_password_secret_ref": "projects/test/secrets/rdp",
            },
            {
                "uuid": "dc-uuid",
                "name": "dc01",
                "asset_type": "gce_vm",
                "role": "dc",
                "os": "windows",
                "subnet_name": "polaris",
                "instance_id": "shifter-r-42-polaris-dc01",
                "private_ip": "10.50.2.4",
                "participant_access_channels": [],
                "ssh_key_secret_arn": "",
                "ssh_username": "Administrator",
                "public_key": "ssh-ed25519 HOST",
                "gcp_host_public_key": "",
                "gcp_host_ssh_key_secret_ref": "projects/test/secrets/host-ssh",
                "gcp_host_ssh_username": "Administrator",
                "gcp_host_ssh_port": 22,
                "gcp_project_id": "test-project",
                "gcp_region": "us-central1",
                "gcp_zone": "us-central1-b",
                "gcp_network_name": "shifter-range-42",
                "gcp_network_self_link": "projects/test-project/global/networks/shifter-range-42",
                "gcp_subnetwork_name": "shifter-r-42-polaris",
                "gcp_subnetwork_self_link": _POLARIS_SUBNETWORK_SELF_LINK,
                "gcp_instance_name": "shifter-r-42-polaris-dc01",
                "gcp_address_name": "shifter-r-42-polaris-dc01-ip",
                "gcp_network_tags": ["shifter-range-42", "shifter-range-42-polaris", "shifter-role-dc"],
                "gcp_image_key": "default",
                "gcp_image_profile_fingerprint": expected_plan["instances"][1]["image_profile_fingerprint"],
                "gcp_source_image": "projects/windows-cloud/global/images/family/windows-2022",
                "gcp_service_account_email": "",
            },
        ],
    }
    clients.networks.insert.assert_not_called()
    clients.subnetworks.insert.assert_not_called()
    clients.firewalls.insert.assert_not_called()
    clients.addresses.insert.assert_not_called()
    clients.instances.insert.assert_not_called()


def test_apply_range_cell_cleans_up_on_failure(mocker):
    clients = _mock_clients(exists=False)
    clients.instances.insert.side_effect = RuntimeError("insert failed")
    secret_ops, _mocks = _mock_secret_ops(mocker)
    cleanup = mocker.Mock()
    variables = _variables()
    config = _sample_config()

    with pytest.raises(RuntimeError, match="insert failed"):
        apply_range_cell(
            "req-123",
            variables,
            config=config,
            clients=clients,
            secret_ops=secret_ops,
            cleanup_range_cell=cleanup,
        )

    cleanup.assert_called_once_with("req-123", variables)


def test_apply_range_cell_cleans_up_when_access_output_contains_a_secret_value(mocker):
    clients = _mock_clients(exists=False)
    secret_ops, secret_mocks = _mock_secret_ops(mocker)
    secret_mocks.ensure_participant_ssh.return_value = ("inline-secret-value", "ssh-ed25519 AAAA")
    cleanup = mocker.Mock()
    variables = _variables()
    config = _sample_config()

    with pytest.raises(RangeCellContractError, match="GCP Secret Manager reference"):
        apply_range_cell(
            "req-123",
            variables,
            config=config,
            clients=clients,
            secret_ops=secret_ops,
            cleanup_range_cell=cleanup,
        )

    cleanup.assert_called_once_with("req-123", variables)


def test_build_clients_uses_google_compute_default_classes(mocker, monkeypatch):
    compute_module = ModuleType("google.cloud.compute_v1")
    network = object()
    subnetwork = object()
    firewall = object()
    address = object()
    instance = object()
    global_operations = object()
    region_operations = object()
    zone_operations = object()
    compute_module.NetworksClient = mocker.Mock(return_value=network)
    compute_module.SubnetworksClient = mocker.Mock(return_value=subnetwork)
    compute_module.FirewallsClient = mocker.Mock(return_value=firewall)
    compute_module.AddressesClient = mocker.Mock(return_value=address)
    compute_module.InstancesClient = mocker.Mock(return_value=instance)
    compute_module.GlobalOperationsClient = mocker.Mock(return_value=global_operations)
    compute_module.RegionOperationsClient = mocker.Mock(return_value=region_operations)
    compute_module.ZoneOperationsClient = mocker.Mock(return_value=zone_operations)
    exceptions_module = ModuleType("google.api_core.exceptions")
    exceptions_module.NotFound = NotFound
    monkeypatch.setitem(sys.modules, "google", ModuleType("google"))
    monkeypatch.setitem(sys.modules, "google.cloud", ModuleType("google.cloud"))
    monkeypatch.setitem(sys.modules, "google.cloud.compute_v1", compute_module)
    monkeypatch.setitem(sys.modules, "google.api_core", ModuleType("google.api_core"))
    monkeypatch.setitem(sys.modules, "google.api_core.exceptions", exceptions_module)

    clients = _build_clients()

    assert clients.networks is network
    assert clients.subnetworks is subnetwork
    assert clients.firewalls is firewall
    assert clients.addresses is address
    assert clients.instances is instance
    assert clients.global_operations is global_operations
    assert clients.region_operations is region_operations
    assert clients.zone_operations is zone_operations
    assert clients.google_exceptions is exceptions_module


def test_apply_range_cell_raises_on_completed_operation_error(mocker):
    clients = _mock_clients(exists=False)
    clients.global_operations.wait.return_value = {
        "error": {"errors": [{"code": "QUOTA_EXCEEDED", "message": "too many networks"}]}
    }
    secret_ops, _mocks = _mock_secret_ops(mocker)
    cleanup = mocker.Mock()
    variables = _variables()
    config = _sample_config()

    with pytest.raises(RuntimeError, match="QUOTA_EXCEEDED: too many networks"):
        apply_range_cell(
            "req-123",
            variables,
            config=config,
            clients=clients,
            secret_ops=secret_ops,
            cleanup_range_cell=cleanup,
        )

    cleanup.assert_called_once_with("req-123", variables)


def test_destroy_range_cell_deletes_every_resource(mocker):
    clients = _mock_clients(exists=True)
    secret_ops, mocks = _mock_secret_ops(mocker)
    vertex_ops, _vertex_mocks = _mock_vertex_ops(mocker)
    order = MagicMock()
    order.attach_mock(clients.instances.delete, "delete_instance")
    order.attach_mock(clients.addresses.delete, "delete_address")
    order.attach_mock(clients.firewalls.delete, "delete_firewall")
    order.attach_mock(clients.subnetworks.delete, "delete_subnetwork")
    order.attach_mock(clients.networks.delete, "delete_network")

    destroy_range_cell(
        "req-123",
        _variables(),
        config=_sample_config(),
        clients=clients,
        secret_ops=secret_ops,
        vertex_ops=vertex_ops,
    )

    assert clients.instances.delete.call_count == 2
    assert clients.addresses.delete.call_count == 2
    assert clients.firewalls.delete.call_count == 4
    assert clients.subnetworks.delete.call_count == 1
    clients.networks.delete.assert_called_once()
    assert mocks.delete_ssh.call_count == 2
    assert mocks.delete_participant_ssh.call_count == 2
    assert mocks.delete_rdp_password.call_count == 2
    assert order.mock_calls == [
        call.delete_instance(project="test-project", zone="us-central1-b", instance="shifter-r-42-polaris-dc01"),
        call.delete_address(project="test-project", region="us-central1", address="shifter-r-42-polaris-dc01-ip"),
        call.delete_instance(project="test-project", zone="us-central1-b", instance="shifter-r-42-polaris-kali"),
        call.delete_address(project="test-project", region="us-central1", address="shifter-r-42-polaris-kali-ip"),
        call.delete_firewall(project="test-project", firewall="shifter-r-42-egress-deny"),
        call.delete_firewall(project="test-project", firewall="shifter-r-42-egress-internal"),
        call.delete_firewall(project="test-project", firewall="shifter-r-42-mgmt"),
        call.delete_firewall(project="test-project", firewall="shifter-r-42-polaris-ingress"),
        call.delete_subnetwork(project="test-project", region="us-central1", subnetwork="shifter-r-42-polaris"),
        call.delete_network(project="test-project", network="shifter-range-42"),
    ]


def test_gce_output_preserves_provider_metadata_for_db_state(mocker):
    clients = _mock_clients(exists=True)
    secret_ops, _mocks = _mock_secret_ops(mocker)

    output = apply_range_cell(
        "req-123",
        _variables(),
        config=_sample_config(),
        clients=clients,
        secret_ops=secret_ops,
    )

    state = _build_instance_state(output["instances"][0], provider="gcp")

    assert state["asset_type"] == "gce_vm"
    assert state["provider_metadata"]["gcp"]["instance_name"] == "shifter-r-42-polaris-kali"
    assert state["provider_metadata"]["gcp"]["network_name"] == "shifter-range-42"
    assert state["provider_metadata"]["gcp"]["network_tags"] == [
        "shifter-range-42",
        "shifter-range-42-polaris",
        "shifter-role-attacker",
    ]
    assert state["provider_metadata"]["gcp"]["image_key"] == "default"
    assert len(state["provider_metadata"]["gcp"]["image_profile_fingerprint"]) == 24
    assert state["provider_metadata"]["gcp"]["source_image"] == "projects/kali/global/images/kali"
