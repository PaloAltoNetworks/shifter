"""Tests for the GCE range-cell backend."""

from __future__ import annotations

import dataclasses
import ipaddress
import sys
from copy import deepcopy
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock, call

import pytest
from shared.range_cells import (
    RangeCellContractError,
    build_gcp_vm_range_cell_request,
    build_scenario_artifact,
    validate_gcp_vm_range_cell_result,
)
from shared.range_instantiation_policy import PREREQUISITE_DENIAL_CODE, UNSUPPORTED_CAPABILITY_CODE

from cloud.exceptions import CloudError
from config import (
    GCE_BOOTSTRAP_PRECONFIGURED_MACHINE_HOST,
    GCE_BOOTSTRAP_PREPROMOTED_DC,
    GCE_PARTICIPANT_READINESS_CONTRACT_V1,
    GCERangeCellConfig,
    GCERangeImageProfile,
)
from gcp_range_cell_firewall import build_firewall_plan
from gcp_range_cell_outputs import InstanceCredentials, instance_output
from gcp_range_cells import (
    GCEGuestSecretOps,
    GCEVertexCredentialOps,
    _build_clients,
    _ensure_firewall,
    _ensure_instance,
    _ensure_router_nat,
    _ensure_subnetwork,
    _insert_instance,
    apply_range_cell,
    destroy_range_cell,
    render_range_cell_plan,
)
from gcp_range_host_identity import gcp_range_host_pool_service_account_email
from state_helpers import _build_instance_state


@pytest.fixture(autouse=True)
def _stub_range_data(monkeypatch):
    """apply/destroy read the range row for placement. Stub that DB read so the
    GCE backend tests stay DB-free."""
    stub = MagicMock(return_value={})
    monkeypatch.setattr("gcp_range_cells.get_range_data_by_request_id", stub, raising=False)
    monkeypatch.setattr("gcp_range_cell_destroy.get_range_data_by_request_id", stub, raising=False)
    # Shared NAT holds a database advisory lock; keep these Compute lifecycle
    # tests at the external DB boundary, not a first-party service mock.
    monkeypatch.setenv("DB_HOST", "localhost")
    monkeypatch.setenv("DB_USER", "test")
    monkeypatch.setenv("DB_NAME", "test")
    monkeypatch.setenv("DB_PASSWORD", "test-only")
    monkeypatch.setattr("provisioner_db.psycopg.connect", lambda **_kwargs: MagicMock())
    return stub


class NotFound(Exception):
    """Fake Google NotFound exception."""


_EXAMPLE_SUBNETWORK_SELF_LINK = "projects/test-project/regions/us-central1/subnetworks/shifter-r-42-example"
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
                "example-vm": GCERangeImageProfile(
                    source_image="projects/shifter/global/images/example-vm",
                    machine_type="n2-standard-8",
                    disk_size_gb=200,
                    bootstrap_capability="standard",
                ),
                "custom-stack": GCERangeImageProfile(
                    source_image="projects/shifter/global/images/custom-stack",
                    machine_type="n2-standard-8",
                    disk_size_gb=150,
                    bootstrap_capability="unsupported-container-stack",
                ),
            },
            "dc": {
                "example-dc": GCERangeImageProfile(
                    source_image="projects/shifter/global/images/example-dc",
                    machine_type="e2-standard-4",
                    disk_size_gb=100,
                    bootstrap_capability=GCE_BOOTSTRAP_PREPROMOTED_DC,
                    domain_dns_name="example.test",
                    domain_netbios_name="EXAMPLE",
                )
            },
        },
        portal_network_cidrs=("10.40.0.0/20",),
    )


def test_preprovisioned_firewall_mode_skips_per_range_rules(monkeypatch):
    monkeypatch.setenv("GCP_RANGE_PREPROVISIONED_FIREWALLS", "true")

    assert build_firewall_plan(42, [], _sample_config()) == []


def _scenario_payload() -> dict:
    return {
        "scenario_id": "scenario-a",
        "user_id": 7,
        "subnets": [
            {
                "name": "example",
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
    egress_mode: str = "status-quo",
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
        egress_mode=egress_mode,
    )


def test_cyberscript_status_quo_plan_owns_a_router_nat():
    """The cyberscript GCE plan builder honors the pinned egress mode (PLAT-238)."""
    plan = render_range_cell_plan("req-123", _variables(egress_mode="status-quo"), _sample_config())
    assert plan.get("router_nat") is not None
    assert plan["router_nat"]["subnetwork_self_links"] == [subnet["self_link"] for subnet in plan["subnets"]]


def test_cyberscript_none_plan_has_no_router_nat_and_no_web_egress():
    plan = render_range_cell_plan("req-123", _variables(egress_mode="none"), _sample_config())
    assert "router_nat" not in plan
    firewall_names = {fw["name"] for fw in plan["firewalls"]}
    assert not any(name.endswith("egress-web") for name in firewall_names)


@pytest.mark.parametrize("egress_mode", ["none", "deny-all"])
def test_zero_egress_mode_suppresses_requested_web_and_allow_lanes(egress_mode):
    # ADR-056-R2: a `none`/`deny-all` range's containment is absolute -- the mode
    # override must suppress the public-web and operator-allow egress lanes even
    # when an instance profile requests public-web egress AND the config declares
    # egress_allow_cidrs, not merely when nobody asked for egress. This proves the
    # override drops an otherwise-requested lane rather than confirming absence.
    config = _sample_config()
    config = dataclasses.replace(
        config,
        kali=dataclasses.replace(config.kali, allow_public_web_egress=True),
        egress_allow_cidrs=("8.8.8.0/24",),
    )

    plan = render_range_cell_plan("req-123", _variables(egress_mode=egress_mode), config)
    firewall_names = {fw["name"] for fw in plan["firewalls"]}

    assert not any(name.endswith("-egress-web") for name in firewall_names)
    assert not any(name.endswith("-egress-allow") for name in firewall_names)


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
        svc.patch.return_value = SimpleNamespace(name="op")
        return svc

    op_service = MagicMock()
    op_service.wait.return_value = SimpleNamespace(status="DONE")
    routers = service()
    router_state = {}

    def router_get(**kwargs):
        name = kwargs["router"]
        if name in router_state:
            return router_state[name]
        if exists:
            return {"name": name, "network": "projects/test-project/global/networks/shared-range", "nats": []}
        raise NotFound()

    def router_insert(**kwargs):
        body = kwargs["router_resource"]
        router_state[body["name"]] = body
        return SimpleNamespace(name="op")

    def router_patch(**kwargs):
        name = kwargs["router"]
        router_state[name] = {**router_state.get(name, {"name": name}), **kwargs["router_resource"]}
        return SimpleNamespace(name="op")

    def router_delete(**kwargs):
        router_state.pop(kwargs["router"], None)
        return SimpleNamespace(name="op")

    routers.get.side_effect = router_get
    routers.list.side_effect = lambda **_kwargs: list(router_state.values())
    routers.insert.side_effect = router_insert
    routers.patch.side_effect = router_patch
    routers.delete.side_effect = router_delete
    return SimpleNamespace(
        networks=service(),
        subnetworks=service(),
        firewalls=service(),
        addresses=service(),
        routers=routers,
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
    return GCEVertexCredentialOps(delete=mocks.delete), mocks


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
    assert plan["subnets"][0]["resource_name"] == "shifter-r-42-example"
    assert plan["subnets"][0]["network_link"] == "projects/test-project/global/networks/shared-range"


def test_render_range_cell_plan_vpc_per_range_mints_own_network():
    plan = render_range_cell_plan("req-123", _variables(), _sample_config())

    # vpc-per-range mode: the range owns (creates/deletes) its own VPC.
    assert plan["manage_network"] is True
    assert plan["network"]["name"] == "shifter-range-42"
    assert plan["network"]["self_link"] == "projects/test-project/global/networks/shifter-range-42"


def test_render_range_cell_plan_selects_bounded_machine_host_identity():
    base = _sample_config()
    nested_profile = GCERangeImageProfile(
        source_machine_image="projects/test-project/global/machineImages/nested-host-v1",
        machine_type="n2-standard-8",
        bootstrap_capability=GCE_BOOTSTRAP_PRECONFIGURED_MACHINE_HOST,
        participant_container_name="participant-desktop",
        participant_username="operator",
        host_ssh_username="hostadmin",
        host_ssh_port=2222,
        participant_readiness_contract=GCE_PARTICIPANT_READINESS_CONTRACT_V1,
        participant_readiness_manifest_sha256="a" * 64,
    )
    profiles = {profile_class: dict(entries) for profile_class, entries in base.image_key_profiles.items()}
    profiles["kali"]["nested-host"] = nested_profile
    config = dataclasses.replace(base, image_key_profiles=profiles, range_host_identity_pool_size=10)
    payload = _scenario_payload()
    payload["subnets"][0]["instances"][0]["ami_key"] = "nested-host"

    plan = render_range_cell_plan(
        "req-123",
        _variables(payload=payload),
        config,
        range_host_pool_slot=4,
    )

    attacker = next(instance for instance in plan["instances"] if instance["role"] == "attacker")
    assert attacker["ssh_username"] == "operator"
    assert attacker["host_ssh_username"] == "hostadmin"
    assert attacker["ssh_port"] == 2222
    assert attacker["service_account_email"] == gcp_range_host_pool_service_account_email("test-project", 4)

    output = instance_output(
        plan,
        attacker,
        InstanceCredentials(
            host_ssh_secret_ref="projects/test/secrets/host-ssh",
            participant_ssh_secret_ref=None,
            rdp_password_secret_ref="projects/test/secrets/rdp",
            ssh_public_key="ssh-ed25519 HOST",
        ),
        config,
    )
    assert output["participant_sftp_enabled"] is False
    assert output["gcp_service_account_email"] == gcp_range_host_pool_service_account_email("test-project", 4)
    assert output["gcp_participant_username"] == "operator"
    assert output["gcp_participant_readiness_contract"] == GCE_PARTICIPANT_READINESS_CONTRACT_V1
    assert output["gcp_participant_readiness_manifest_sha256"] == "a" * 64


def test_render_range_cell_plan_shards_machine_hosts_across_bounded_identity_pool():
    base = _sample_config()
    nested_profile = GCERangeImageProfile(
        source_machine_image="projects/test-project/global/machineImages/nested-host-v1",
        machine_type="n2-standard-8",
        bootstrap_capability=GCE_BOOTSTRAP_PRECONFIGURED_MACHINE_HOST,
        participant_container_name="participant-desktop",
        participant_username="operator",
        host_ssh_username="hostadmin",
    )
    profiles = {profile_class: dict(entries) for profile_class, entries in base.image_key_profiles.items()}
    profiles["kali"]["nested-host"] = nested_profile
    config = dataclasses.replace(base, image_key_profiles=profiles, range_host_identity_pool_size=4)
    payload = _scenario_payload()
    payload["subnets"][0]["instances"][0]["ami_key"] = "nested-host"

    plan = render_range_cell_plan(
        "req-123",
        _variables(payload=payload),
        config,
        range_host_pool_slot=4,
    )

    attacker = next(instance for instance in plan["instances"] if instance["role"] == "attacker")
    assert attacker["service_account_email"] == gcp_range_host_pool_service_account_email("test-project", 0)


def test_render_range_cell_plan_rejects_disabled_machine_host_identity_pool():
    base = _sample_config()
    nested_profile = GCERangeImageProfile(
        source_machine_image="projects/test-project/global/machineImages/nested-host-v1",
        machine_type="n2-standard-8",
        bootstrap_capability=GCE_BOOTSTRAP_PRECONFIGURED_MACHINE_HOST,
        participant_container_name="participant-desktop",
        participant_username="operator",
        host_ssh_username="hostadmin",
    )
    profiles = {profile_class: dict(entries) for profile_class, entries in base.image_key_profiles.items()}
    profiles["kali"]["nested-host"] = nested_profile
    config = dataclasses.replace(base, image_key_profiles=profiles, range_host_identity_pool_size=0)
    payload = _scenario_payload()
    payload["subnets"][0]["instances"][0]["ami_key"] = "nested-host"

    variables = _variables(payload=payload)

    with pytest.raises(CloudError, match="identity pool is disabled"):
        render_range_cell_plan("req-123", variables, config, range_host_pool_slot=4)


def test_render_range_cell_plan_private_google_access_adds_egress_hole():
    config = dataclasses.replace(_sample_config(), private_google_access=True)

    plan = render_range_cell_plan("req-123", _variables(), config)

    firewall_names = {fw["name"] for fw in plan["firewalls"]}
    assert "shifter-r-42-egress-googleapis" in firewall_names


def test_render_range_cell_plan_profile_can_allow_public_web_egress():
    config = _sample_config()
    config = dataclasses.replace(
        config,
        kali=dataclasses.replace(config.kali, allow_public_web_egress=True),
    )

    plan = render_range_cell_plan("req-123", _variables(), config)
    firewalls = {firewall["name"]: firewall for firewall in plan["firewalls"]}

    web = firewalls["shifter-r-42-egress-web"]
    assert web["priority"] == 1200
    assert web["allowed"] == [{"IPProtocol": "tcp", "ports": ["80", "443"]}]
    # ADR-056-R2: the public-web lane targets the public-internet complement, not a
    # bare 0.0.0.0/0 -- it reaches routable public space but never management,
    # peer-range, private-service, metadata, or the Google private-API VIP.
    assert web["destination_ranges"] != ["0.0.0.0/0"]
    web_dests = [ipaddress.ip_network(cidr) for cidr in web["destination_ranges"]]
    assert any(ipaddress.ip_address("8.8.8.8") in cidr for cidr in web_dests)
    for blocked in ("10.0.0.0/8", "169.254.0.0/16", "192.168.0.0/16", "172.16.0.0/12", "199.36.153.8/30"):
        assert all(not cidr.overlaps(ipaddress.ip_network(blocked)) for cidr in web_dests)
    assert firewalls["shifter-r-42-egress-deny"]["denied"] == [{"IPProtocol": "all"}]


def test_public_web_egress_excludes_declared_management_cidr_containing_denied_range():
    # Regression (#1295 codex): a declared management CIDR that CONTAINS an
    # already-denied range (the Google private-API VIP /30) must be fully excluded
    # from the public-web egress complement. Before the exclusion set was
    # collapsed, the VIP /30 split the surrounding /24 across fragments and most of
    # the /24 leaked back into the sanctioned public-web lane.
    config = _sample_config()
    config = dataclasses.replace(
        config,
        portal_network_cidrs=(*config.portal_network_cidrs, "199.36.153.0/24"),
        kali=dataclasses.replace(config.kali, allow_public_web_egress=True),
    )

    plan = render_range_cell_plan("req-123", _variables(), config)
    firewalls = {firewall["name"]: firewall for firewall in plan["firewalls"]}

    web_dests = [ipaddress.ip_network(cidr) for cidr in firewalls["shifter-r-42-egress-web"]["destination_ranges"]]
    declared = ipaddress.ip_network("199.36.153.0/24")
    assert all(not cidr.overlaps(declared) for cidr in web_dests)


def test_render_range_cell_plan_default_profile_keeps_public_web_denied():
    plan = render_range_cell_plan("req-123", _variables(), _sample_config())

    assert not any(firewall["name"].endswith("-egress-web") for firewall in plan["firewalls"])


def test_render_range_cell_plan_rejects_subnet_without_uuid():
    payload = _scenario_payload()
    del payload["subnets"][0]["uuid"]
    variables = _variables(payload=payload)
    config = _sample_config()

    with pytest.raises(RuntimeError, match="requires name and uuid"):
        render_range_cell_plan("req-123", variables, config)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda payload: payload.update(ngfw=True), "does not support NGFW"),
        (
            lambda payload: payload["subnets"][0]["instances"][0].update(ami_key="custom-stack"),
            "requires an unsupported bootstrap capability",
        ),
    ],
)
def test_legacy_realizer_rejects_unsupported_composition_before_provider_mutation(
    mocker,
    mutate,
    message,
):
    payload = _scenario_payload()
    mutate(payload)
    clients = _mock_clients(exists=False)
    secret_ops, secret_mocks = _mock_secret_ops(mocker)
    vertex_ops, _ = _mock_vertex_ops(mocker)
    variables = _variables(payload=payload)
    config = _sample_config()

    with pytest.raises(CloudError, match=message) as exc:
        apply_range_cell(
            "req-123",
            variables,
            config=config,
            clients=clients,
            secret_ops=secret_ops,
            vertex_ops=vertex_ops,
        )

    assert exc.value.code == UNSUPPORTED_CAPABILITY_CODE
    clients.networks.insert.assert_not_called()
    clients.subnetworks.insert.assert_not_called()
    clients.firewalls.insert.assert_not_called()
    clients.addresses.insert.assert_not_called()
    clients.instances.insert.assert_not_called()
    secret_mocks.ensure_ssh.assert_not_called()
    secret_mocks.ensure_participant_ssh.assert_not_called()
    secret_mocks.ensure_rdp_password.assert_not_called()


def test_legacy_realizer_rejects_missing_dc_image_before_provider_mutation(mocker):
    clients = _mock_clients(exists=False)
    secret_ops, secret_mocks = _mock_secret_ops(mocker)
    vertex_ops, _ = _mock_vertex_ops(mocker)
    config = dataclasses.replace(
        _sample_config(),
        dc=GCERangeImageProfile(),
        image_key_profiles={},
    )
    variables = _variables()

    with pytest.raises(CloudError, match="Missing GCE range image") as exc:
        apply_range_cell(
            "req-123",
            variables,
            config=config,
            clients=clients,
            secret_ops=secret_ops,
            vertex_ops=vertex_ops,
        )

    assert exc.value.code == PREREQUISITE_DENIAL_CODE
    clients.networks.insert.assert_not_called()
    clients.instances.insert.assert_not_called()
    secret_mocks.ensure_ssh.assert_not_called()


def test_domain_composition_rejects_mismatched_keyed_domain_before_provider_mutation(mocker):
    payload = _scenario_payload()
    dc = payload["subnets"][0]["instances"][1]
    dc["ami_key"] = "example-dc"
    dc["dc_config"] = {
        "domain_name": "internal.shifter",
        "netbios_name": "INTSHIFTER",
    }
    clients = _mock_clients(exists=False)
    secret_ops, _ = _mock_secret_ops(mocker)
    vertex_ops, _ = _mock_vertex_ops(mocker)
    variables = _variables(payload=payload)
    config = _sample_config()

    with pytest.raises(CloudError, match="does not match the authored domain identity") as exc:
        apply_range_cell(
            "req-123",
            variables,
            config=config,
            clients=clients,
            secret_ops=secret_ops,
            vertex_ops=vertex_ops,
        )

    assert exc.value.code == PREREQUISITE_DENIAL_CODE
    clients.networks.insert.assert_not_called()
    clients.instances.insert.assert_not_called()


def test_domain_composition_accepts_matching_profile_domain_identity():
    payload = _scenario_payload()
    dc = payload["subnets"][0]["instances"][1]
    dc["ami_key"] = "example-dc"
    dc["dc_config"] = {
        "domain_name": "EXAMPLE.TEST.",
        "netbios_name": "example",
    }

    plan = render_range_cell_plan("req-123", _variables(payload=payload), _sample_config())

    assert plan["instances"][1]["profile"].bootstrap_capability == GCE_BOOTSTRAP_PREPROMOTED_DC


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


def test_shared_nat_capacity_refusal_precedes_subnet_creation(mocker):
    clients = _mock_clients(exists=False)
    secret_ops, _ = _mock_secret_ops(mocker)
    vertex_ops, _ = _mock_vertex_ops(mocker)
    clients.routers.list.return_value = [
        {"name": f"other-{index}", "network": "projects/test-project/global/networks/shared-range", "nats": []}
        for index in range(5)
    ]
    clients.routers.list.side_effect = None

    with pytest.raises(RuntimeError, match="shared-nat-router-capacity-exhausted"):
        apply_range_cell(
            "req-123",
            _variables(),
            config=_shared_vpc_config(),
            clients=clients,
            secret_ops=secret_ops,
            vertex_ops=vertex_ops,
            cleanup_range_cell=lambda *_args: None,
        )

    clients.subnetworks.insert.assert_not_called()


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


def test_apply_does_not_issue_provider_keys(mocker):
    clients = _mock_clients(exists=True)
    secret_ops, _ = _mock_secret_ops(mocker)
    vertex_ops, _ = _mock_vertex_ops(mocker)

    outputs = apply_range_cell(
        "req-123",
        _variables(),
        config=_sample_config(),
        clients=clients,
        secret_ops=secret_ops,
        vertex_ops=vertex_ops,
    )

    assert all("gcp_vertex_secret_ref" not in output for output in outputs["instances"])


def test_destroy_deletes_per_range_vertex_key(mocker):
    clients = _mock_clients(exists=True)
    secret_ops, _ = _mock_secret_ops(mocker)
    vertex_ops, vertex_mocks = _mock_vertex_ops(mocker)

    destroy_range_cell(
        "req-123",
        _variables(),
        config=_sample_config(),
        clients=clients,
        secret_ops=secret_ops,
        vertex_ops=vertex_ops,
    )

    vertex_mocks.delete.assert_called_once_with(42, "test-project")


def test_render_range_cell_plan_uses_vpc_per_range_and_deterministic_ips():
    plan = render_range_cell_plan("req-123", _variables(), _sample_config())

    assert plan["network"]["name"] == "shifter-range-42"
    assert plan["subnets"][0]["resource_name"] == "shifter-r-42-example"
    assert plan["subnets"][0]["ip_assignments"] == {
        _LINUX_UUID: "10.50.2.3",
        "dc-uuid": "10.50.2.4",
    }
    assert [instance["private_ip"] for instance in plan["instances"]] == ["10.50.2.3", "10.50.2.4"]
    assert {firewall["name"] for firewall in plan["firewalls"]} >= {
        "shifter-r-42-example-ingress",
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


def test_ensure_firewall_inserts_when_missing():
    plan = render_range_cell_plan("req-123", _variables(), _sample_config())
    mgmt = _firewall_by_name(plan, "mgmt")
    clients = _mock_clients(exists=False)

    _ensure_firewall(plan, clients, mgmt)

    clients.firewalls.insert.assert_called_once()
    clients.firewalls.patch.assert_not_called()


def test_ensure_firewall_reconciles_existing_broad_rule_to_planned_body():
    # #1711 / ADR-039-R9: an existing rule (e.g. a legacy broad *-mgmt that once
    # opened participant RDP) must be converged to the narrowed planned body, not
    # trusted because its name exists. Reconcile = patch with the fresh body.
    config = dataclasses.replace(
        _sample_config(),
        portal_network_cidrs=("10.46.0.0/20",),
        access_network_cidrs=("10.47.0.0/24",),
    )
    plan = render_range_cell_plan("req-123", _variables(), config)
    mgmt = _firewall_by_name(plan, "mgmt")
    clients = _mock_clients(exists=True)

    _ensure_firewall(plan, clients, mgmt)

    clients.firewalls.insert.assert_not_called()
    clients.firewalls.patch.assert_called_once()
    _, kwargs = clients.firewalls.patch.call_args
    assert kwargs["firewall"] == "shifter-r-42-mgmt"
    # The converged body is SSH-only -- the broad participant RDP is gone.
    assert kwargs["firewall_resource"]["allowed"] == [{"I_p_protocol": "tcp", "ports": ["22", "2222"]}]


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
    config = dataclasses.replace(_sample_config(), egress_allow_cidrs=("8.8.8.8/32",))

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


def test_range_cell_firewalls_reject_access_management_source_overlap():
    # #1711 / ADR-039-R9: the access-workload source and the provisioner/management
    # source must be disjoint identities. An overlap would let the broad management
    # source re-enter the participant path, defeating the dedicated access identity.
    config = dataclasses.replace(
        _sample_config(),
        portal_network_cidrs=("10.46.0.0/20",),
        access_network_cidrs=("10.46.1.0/24",),
    )
    variables = _variables()

    with pytest.raises(RuntimeError, match="must not overlap portal_network_cidrs"):
        render_range_cell_plan("req-123", variables, config)


def test_range_cell_firewalls_deduplicate_explicit_egress_cidrs():
    config = dataclasses.replace(_sample_config(), egress_allow_cidrs=("8.8.8.0/24", "8.8.8.0/24"))

    plan = render_range_cell_plan("req-123", _variables(), config)
    egress = next(rule for rule in plan["firewalls"] if rule["name"].endswith("-egress-allow"))

    assert egress["destination_ranges"] == ["8.8.8.0/24"]


@pytest.mark.parametrize(
    ("cidr", "overlaps"),
    [
        ("10.0.0.0/24", "10.0.0.0/8"),  # RFC1918 management/peer-range space
        ("169.254.169.254/32", "169.254.0.0/16"),  # link-local metadata server
        ("192.168.5.0/24", "192.168.0.0/16"),  # RFC1918
        ("199.36.153.8/30", "199.36.153.8/30"),  # Google private-API VIP
        ("10.40.0.0/24", "10.40.0.0/20"),  # a declared portal/management CIDR
    ],
)
def test_range_cell_firewalls_reject_egress_allow_overlapping_denied_inventory(cidr, overlaps):
    # ADR-056-R2/R4: a sanctioned egress allow-CIDR is for public destinations
    # only. Overlap with the denied-network inventory (management, peer-range,
    # private-service, metadata, special-use) fails closed rather than re-opening
    # an internal path the default deny is meant to close.
    config = dataclasses.replace(_sample_config(), egress_allow_cidrs=(cidr,))
    variables = _variables()

    with pytest.raises(RuntimeError, match="must not overlap the denied-network inventory"):
        render_range_cell_plan("req-123", variables, config)


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


def test_existing_keyed_instance_rejects_profile_drift_before_secret_mutation(mocker):
    payload = _scenario_payload()
    payload["subnets"][0]["instances"][0]["ami_key"] = "example-vm"
    config = _sample_config()
    plan = render_range_cell_plan("req-123", _variables(payload=payload), config)
    instance = plan["instances"][0]
    clients = _mock_clients(exists=False)
    clients.instances.get.side_effect = None
    clients.instances.get.return_value = SimpleNamespace(
        labels={"image-key": "example-vm", "image-profile": "wrong-profile"}
    )
    secret_ops, secret_mocks = _mock_secret_ops(mocker)

    with pytest.raises(RuntimeError, match="image-profile binding"):
        _ensure_instance(plan, clients, config, instance, secret_ops)

    secret_mocks.ensure_ssh.assert_not_called()


def test_machine_image_instance_clone_converges_all_attached_disks_to_auto_delete(mocker):
    base = _sample_config()
    nested_profile = GCERangeImageProfile(
        source_machine_image="projects/test-project/global/machineImages/nested-host-v1",
        machine_type="n2-standard-8",
        bootstrap_capability=GCE_BOOTSTRAP_PRECONFIGURED_MACHINE_HOST,
        participant_container_name="participant-desktop",
        participant_username="operator",
        host_ssh_username="hostadmin",
        host_ssh_port=2222,
    )
    profiles = {profile_class: dict(entries) for profile_class, entries in base.image_key_profiles.items()}
    profiles["kali"]["nested-host"] = nested_profile
    config = dataclasses.replace(base, image_key_profiles=profiles, range_host_identity_pool_size=10)
    payload = _scenario_payload()
    payload["subnets"][0]["instances"][0]["ami_key"] = "nested-host"
    plan = render_range_cell_plan(
        "req-123",
        _variables(payload=payload),
        config,
        range_host_pool_slot=4,
    )
    instance = plan["instances"][0]
    clients = _mock_clients(exists=False)
    created = SimpleNamespace(
        disks=[
            SimpleNamespace(device_name="boot", auto_delete=True),
            SimpleNamespace(device_name="nested-data", auto_delete=False),
        ]
    )
    clients.instances.get.side_effect = [NotFound(), created]
    clients.instances.set_disk_auto_delete.return_value = SimpleNamespace(name="op")
    secret_ops, _secret_mocks = _mock_secret_ops(mocker)

    _ensure_instance(plan, clients, config, instance, secret_ops)

    request = clients.instances.insert.call_args.kwargs["request"]
    assert request["source_machine_image"] == nested_profile.source_machine_image
    assert "disks" not in request["instance_resource"]
    clients.instances.set_disk_auto_delete.assert_called_once_with(
        project="test-project",
        zone="us-central1-b",
        instance=instance["resource_name"],
        device_name="nested-data",
        auto_delete=True,
    )


def test_machine_image_clone_retries_only_source_operation_rate_limit(monkeypatch):
    plan = {"project_id": "test-project", "zone": "us-central1-b"}
    instance = {
        "resource_name": "shifter-r-42-host",
        "profile": GCERangeImageProfile(source_machine_image="projects/test-project/global/machineImages/host-v1"),
        "image_key": "",
    }
    clients = _mock_clients(exists=False)
    clients.instances.get.side_effect = [NotFound(), SimpleNamespace(disks=[])]
    wait = MagicMock(side_effect=[RuntimeError("RESOURCE_OPERATION_RATE_EXCEEDED"), None])
    sleep = MagicMock()
    monkeypatch.setattr("gcp_range_cell_ops._wait_for_operation", wait)
    monkeypatch.setattr("gcp_range_cell_ops.time.sleep", sleep)
    monkeypatch.setattr("gcp_range_cell_ops._machine_image_retry_jitter", lambda _name, _attempt, _delay: 0)

    _insert_instance(plan, clients, instance, {"name": instance["resource_name"]})

    assert clients.instances.insert.call_count == 2
    assert clients.instances.get.call_count == 2
    sleep.assert_called_once_with(15)


def test_machine_image_clone_does_not_retry_other_forbidden_errors(monkeypatch):
    plan = {"project_id": "test-project", "zone": "us-central1-b"}
    instance = {
        "resource_name": "shifter-r-42-host",
        "profile": GCERangeImageProfile(source_machine_image="projects/test-project/global/machineImages/host-v1"),
        "image_key": "",
    }
    clients = _mock_clients(exists=False)
    clients.instances.insert.side_effect = RuntimeError("permission denied")
    sleep = MagicMock()
    monkeypatch.setattr("gcp_range_cell_ops.time.sleep", sleep)

    with pytest.raises(RuntimeError, match="permission denied"):
        _insert_instance(plan, clients, instance, {"name": instance["resource_name"]})

    clients.instances.insert.assert_called_once()
    clients.instances.get.assert_not_called()
    sleep.assert_not_called()


def test_machine_image_rate_limit_reconciles_created_instance_without_duplicate_insert(monkeypatch):
    plan = {"project_id": "test-project", "zone": "us-central1-b"}
    instance = {
        "resource_name": "shifter-r-42-host",
        "profile": GCERangeImageProfile(source_machine_image="projects/test-project/global/machineImages/host-v1"),
        "image_key": "",
    }
    clients = _mock_clients(exists=False)
    clients.instances.get.side_effect = None
    clients.instances.get.return_value = SimpleNamespace(disks=[])
    wait = MagicMock(side_effect=RuntimeError("RESOURCE_OPERATION_RATE_EXCEEDED"))
    sleep = MagicMock()
    monkeypatch.setattr("gcp_range_cell_ops._wait_for_operation", wait)
    monkeypatch.setattr("gcp_range_cell_ops.time.sleep", sleep)

    _insert_instance(plan, clients, instance, {"name": instance["resource_name"]})

    clients.instances.insert.assert_called_once()
    sleep.assert_not_called()


def test_machine_image_rate_limit_exhaustion_keeps_failure_closed(monkeypatch):
    plan = {"project_id": "test-project", "zone": "us-central1-b"}
    instance = {
        "resource_name": "shifter-r-42-host",
        "profile": GCERangeImageProfile(source_machine_image="projects/test-project/global/machineImages/host-v1"),
        "image_key": "",
    }
    clients = _mock_clients(exists=False)
    clients.instances.get.side_effect = NotFound()
    wait = MagicMock(side_effect=RuntimeError("RESOURCE_OPERATION_RATE_EXCEEDED"))
    sleep = MagicMock()
    monkeypatch.setattr("gcp_range_cell_ops._wait_for_operation", wait)
    monkeypatch.setattr("gcp_range_cell_ops._MACHINE_IMAGE_RATE_RETRY_DELAYS", (0,))
    monkeypatch.setattr("gcp_range_cell_ops.time.sleep", sleep)
    monkeypatch.setattr("gcp_range_cell_ops._machine_image_retry_jitter", lambda _name, _attempt, _delay: 0)

    with pytest.raises(RuntimeError, match="RESOURCE_OPERATION_RATE_EXCEEDED"):
        _insert_instance(plan, clients, instance, {"name": instance["resource_name"]})

    assert clients.instances.insert.call_count == 2
    sleep.assert_called_once_with(0)


def test_custom_image_host_reconcile_restores_boot_disk_auto_delete(mocker):
    base = _sample_config()
    profile = GCERangeImageProfile(
        source_image="projects/test-project/global/images/nested-host-v1",
        machine_type="n2-standard-8",
        disk_size_gb=220,
        bootstrap_capability=GCE_BOOTSTRAP_PRECONFIGURED_MACHINE_HOST,
        participant_container_name="participant-desktop",
        participant_username="operator",
        host_ssh_username="hostadmin",
        participant_readiness_contract=GCE_PARTICIPANT_READINESS_CONTRACT_V1,
        participant_readiness_manifest_sha256="a" * 64,
    )
    profiles = {profile_class: dict(entries) for profile_class, entries in base.image_key_profiles.items()}
    profiles["kali"]["nested-host"] = profile
    config = dataclasses.replace(base, image_key_profiles=profiles, range_host_identity_pool_size=10)
    payload = _scenario_payload()
    payload["subnets"][0]["instances"][0]["ami_key"] = "nested-host"
    plan = render_range_cell_plan("req-123", _variables(payload=payload), config, range_host_pool_slot=4)
    instance = plan["instances"][0]
    clients = _mock_clients(exists=False)
    clients.instances.get.side_effect = None
    clients.instances.get.return_value = SimpleNamespace(
        labels={**plan["labels"], "image-key": "nested-host", "image-profile": instance["image_profile_fingerprint"]},
        disks=[SimpleNamespace(device_name="boot", auto_delete=False)],
        metadata=SimpleNamespace(items=[]),
    )
    clients.instances.set_disk_auto_delete.return_value = SimpleNamespace(name="op")
    secret_ops, _ = _mock_secret_ops(mocker)

    _ensure_instance(plan, clients, config, instance, secret_ops)

    clients.instances.insert.assert_not_called()
    clients.instances.set_disk_auto_delete.assert_called_once_with(
        project="test-project",
        zone="us-central1-b",
        instance=instance["resource_name"],
        device_name="boot",
        auto_delete=True,
    )


def test_render_plan_resolves_distinct_images_for_same_role_by_ami_key():
    payload = _scenario_payload()
    example = payload["subnets"][0]["instances"][0]
    example["ami_key"] = "example-vm"
    alternate = deepcopy(example)
    alternate.update(
        {
            "uuid": "33333333-3333-4333-8333-333333333333",
            "name": "alternate",
            "ami_key": "alternate",
        }
    )
    payload["subnets"][0]["instances"].append(alternate)
    config = dataclasses.replace(
        _sample_config(),
        image_key_profiles={
            "kali": {
                "example-vm": GCERangeImageProfile(
                    source_image="projects/test/global/images/family/shifter-example-vm",
                    machine_type="e2-standard-8",
                    disk_size_gb=210,
                ),
                "alternate": GCERangeImageProfile(
                    source_image="projects/test/global/images/family/shifter-alternate",
                    machine_type="n2-standard-8",
                    disk_size_gb=150,
                ),
            }
        },
    )

    plan = render_range_cell_plan("req-123", _variables(payload=payload), config)
    by_name = {instance["name"]: instance for instance in plan["instances"]}

    assert by_name["kali"]["profile"].source_image.endswith("shifter-example-vm")
    assert by_name["kali"]["profile"].disk_size_gb == 210
    assert by_name["alternate"]["profile"].source_image.endswith("shifter-alternate")
    assert by_name["alternate"]["profile"].disk_size_gb == 150


def test_mgmt_firewall_is_ssh_only_and_omits_participant_ingress_without_access_range():
    """Fail closed (#1711 / ADR-039-R9): with no access-workload range configured,
    the management ingress rule is SSH-only (host SSH + Docker-host mgmt port) and
    participant ingress (22/3389 from an access source) is omitted entirely -- the
    management source never inherits participant RDP as a fallback."""
    config = GCERangeCellConfig(
        project_id="test-project",
        region="us-central1",
        zone="us-central1-b",
        network_mode="vpc-per-range",
        service_account_email="range-host@test-project.iam.gserviceaccount.com",
        kali=GCERangeImageProfile(source_image="projects/shifter/global/images/example-vm"),
        dc=GCERangeImageProfile(source_image="projects/shifter/global/images/example-dc"),
        portal_network_cidrs=("10.46.0.0/20",),
        host_mgmt_ssh_port=2222,
    )
    plan = render_range_cell_plan("req-123", _variables(), config)
    mgmt = next(fw for fw in plan["firewalls"] if fw["name"] == "shifter-r-42-mgmt")

    assert mgmt["allowed"] == [{"IPProtocol": "tcp", "ports": ["22", "2222"]}]
    # No participant access rule and no RDP anywhere without an access range.
    assert not [fw for fw in plan["firewalls"] if fw["name"] == "shifter-r-42-access"]
    assert all("3389" not in fw.get("allowed", [{}])[0].get("ports", []) for fw in plan["firewalls"] if "allowed" in fw)


def test_instance_resource_installs_key_for_host_login_user():
    """GCE ssh-keys metadata installs the key for the host user the provisioner drives.

    Regression: for a Docker-host guest the provisioner connects as the host
    user (ubuntu), not the participant user (kali) whose key the container's
    authorized_keys carries; installing the key for kali would leave host setup
    unable to SSH in.
    """
    from gcp_range_cell_resources import instance_resource

    payload = _scenario_payload()
    payload["subnets"][0]["instances"][0]["ami_key"] = "example-vm"
    variables = _variables(payload=payload)
    plan = render_range_cell_plan("req-123", variables, _sample_config())
    host = {**plan["instances"][0], "host_ssh_username": "setup-user"}

    body = instance_resource(plan, host, _sample_config(), ssh_public_key="ssh-ed25519 AAAA")
    ssh_keys = next(item for item in body["metadata"]["items"] if item["key"] == "ssh-keys")

    assert ssh_keys["value"] == "setup-user:ssh-ed25519 AAAA"
    assert body["labels"]["image-key"] == "example-vm"
    assert body["labels"]["image-profile"] == host["image_profile_fingerprint"]


def test_windows_guest_bootstrap_preserves_firewall_profiles_and_opens_only_management_ssh():
    """Core management reachability cannot disable the guest's firewall policy."""
    from gcp_range_cell_resources import instance_resource

    plan = render_range_cell_plan("req-123", _variables(), _sample_config())
    by_name = {inst["name"]: inst for inst in plan["instances"]}

    instance = {**by_name["dc01"], "ssh_port": 2222}
    dc_body = instance_resource(plan, instance, _sample_config(), ssh_public_key="ssh-ed25519 AAAA")
    dc_meta = {item["key"]: item["value"] for item in dc_body["metadata"]["items"]}
    assert "windows-startup-script-ps1" in dc_meta
    script = dc_meta["windows-startup-script-ps1"]
    assert "Set-NetFirewallProfile" not in script
    assert "-LocalPort 2222" in script
    assert "-Protocol TCP" in script
    assert "-Action Allow" in script
    assert "sshd" in dc_meta["windows-startup-script-ps1"]

    host_body = instance_resource(plan, by_name["kali"], _sample_config(), ssh_public_key="ssh-ed25519 AAAA")
    host_meta = {item["key"]: item["value"] for item in host_body["metadata"]["items"]}
    assert "windows-startup-script-ps1" not in host_meta


def test_instance_resource_injects_ssh_host_key_per_os():
    """The provisioner-issued SSH host key is installed via the guest startup
    script (Windows: ProgramData\\ssh; Linux: /etc/ssh) and its public half is
    surfaced in metadata so the setup runner can seed known_hosts."""
    from gcp_range_cell_resources import HOST_PUBLIC_KEY_METADATA_KEY, instance_resource

    plan = render_range_cell_plan("req-123", _variables(), _sample_config())
    by_name = {inst["name"]: inst for inst in plan["instances"]}

    dc_body = instance_resource(
        plan,
        by_name["dc01"],
        _sample_config(),
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
        _sample_config(),
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


def test_apply_creates_every_planned_gcp_resource_with_the_expected_body(mocker):
    from gcp_range_cell_resources import (
        address_resource,
        firewall_resource,
        network_resource,
        subnetwork_resource,
    )

    config = _sample_config()
    variables = _variables()
    plan = render_range_cell_plan("req-123", variables, config)
    clients = _mock_clients(exists=False)
    secret_ops, _ = _mock_secret_ops(mocker)
    vertex_ops, _ = _mock_vertex_ops(mocker)

    apply_range_cell(
        "req-123",
        variables,
        config=config,
        clients=clients,
        secret_ops=secret_ops,
        vertex_ops=vertex_ops,
    )

    clients.networks.insert.assert_called_once_with(
        project=plan["project_id"],
        network_resource=network_resource(plan),
    )
    assert clients.subnetworks.insert.call_args_list == [
        call(
            project=plan["project_id"],
            region=plan["region"],
            subnetwork_resource=subnetwork_resource(plan, subnet),
        )
        for subnet in plan["subnets"]
    ]
    assert clients.firewalls.insert.call_args_list == [
        call(
            project=plan["project_id"],
            firewall_resource=firewall_resource(plan, firewall),
        )
        for firewall in plan["firewalls"]
    ]
    assert clients.addresses.insert.call_args_list == [
        call(
            project=plan["project_id"],
            region=plan["region"],
            address_resource=address_resource(instance),
        )
        for instance in plan["instances"]
    ]
    assert clients.instances.insert.call_count == len(plan["instances"])
    assert [
        call_record.kwargs["instance_resource"]["name"] for call_record in clients.instances.insert.call_args_list
    ] == [instance["resource_name"] for instance in plan["instances"]]


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
    vertex_ops, _ = _mock_vertex_ops(mocker)
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
    vertex_ops, _ = _mock_vertex_ops(mocker)
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


def test_render_plan_carries_private_google_access_flag():
    """Private Google Access flows from config into the subnet resource body."""
    from gcp_range_cell_resources import subnetwork_resource

    config = GCERangeCellConfig(
        project_id="test-project",
        region="us-central1",
        zone="us-central1-b",
        network_mode="vpc-per-range",
        service_account_email="range-host@test-project.iam.gserviceaccount.com",
        kali=GCERangeImageProfile(source_image="projects/shifter/global/images/example-vm"),
        dc=GCERangeImageProfile(source_image="projects/shifter/global/images/example-dc"),
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
    plan = render_range_cell_plan("req-123", _variables(), _sample_config())
    assert not any(fw["name"].endswith("-egress-googleapis") for fw in plan["firewalls"])


def test_resource_bodies_use_proto_field_names():
    """Compute resource bodies use google-cloud-compute proto (snake_case) field
    names, including the proto-plus quirks I_p_protocol and network_i_p, so the
    clients can construct the messages."""
    from gcp_range_cell_resources import firewall_resource, instance_resource, network_resource

    plan = render_range_cell_plan("req-123", _variables(), _sample_config())

    net = network_resource(plan)
    assert "auto_create_subnetworks" in net
    assert net["routing_config"] == {"routing_mode": "REGIONAL"}

    mgmt = next(fw for fw in plan["firewalls"] if fw["name"].endswith("-mgmt"))
    fw_body = firewall_resource(plan, mgmt)
    # Management ingress is SSH-only (host SSH + Docker-host mgmt port); no
    # participant RDP fallback (#1711). Ports carried through proto translation.
    assert fw_body["allowed"] == [{"I_p_protocol": "tcp", "ports": ["22", "2222"]}]
    assert "target_tags" in fw_body

    host = plan["instances"][0]
    body = instance_resource(plan, host, _sample_config(), ssh_public_key="ssh-ed25519 AAAA")
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
    config = _sample_config()
    expected_plan = render_range_cell_plan("req-123", _variables(), config)

    output = apply_range_cell(
        "req-123",
        _variables(),
        config=config,
        clients=clients,
        secret_ops=secret_ops,
    )

    validate_gcp_vm_range_cell_result(output.pop("range_cell"))

    assert output == {
        "subnets": {
            "example": {
                "uuid": "subnet-uuid",
                "subnet_id": "shifter-r-42-example",
                "subnet_cidr": "10.50.2.0/28",
                "gcp_network_name": "shifter-range-42",
                "gcp_network_self_link": "projects/test-project/global/networks/shifter-range-42",
                "gcp_subnetwork_name": "shifter-r-42-example",
                "gcp_subnetwork_self_link": _EXAMPLE_SUBNETWORK_SELF_LINK,
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
                "subnet_name": "example",
                "instance_id": "shifter-r-42-example-kali",
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
                "gcp_subnetwork_name": "shifter-r-42-example",
                "gcp_subnetwork_self_link": _EXAMPLE_SUBNETWORK_SELF_LINK,
                "gcp_instance_name": "shifter-r-42-example-kali",
                "gcp_address_name": "shifter-r-42-example-kali-ip",
                "gcp_network_tags": ["shifter-range-42", "shifter-range-42-example", "shifter-role-attacker"],
                "gcp_image_key": "default",
                "gcp_image_profile_fingerprint": expected_plan["instances"][0]["image_profile_fingerprint"],
                "gcp_source_image": "projects/kali/global/images/kali",
                "gcp_bootstrap_capability": "standard",
                "bootstrap_capability": "standard",
                "gcp_service_account_email": "range-host@test-project.iam.gserviceaccount.com",
                "rdp_password_secret_arn": "projects/test/secrets/rdp",
                "gcp_bootstrap_rdp_password_secret_ref": "projects/test/secrets/rdp",
            },
            {
                "uuid": "dc-uuid",
                "name": "dc01",
                "asset_type": "gce_vm",
                "role": "dc",
                "os": "windows",
                "subnet_name": "example",
                "instance_id": "shifter-r-42-example-dc01",
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
                "gcp_subnetwork_name": "shifter-r-42-example",
                "gcp_subnetwork_self_link": _EXAMPLE_SUBNETWORK_SELF_LINK,
                "gcp_instance_name": "shifter-r-42-example-dc01",
                "gcp_address_name": "shifter-r-42-example-dc01-ip",
                "gcp_network_tags": ["shifter-range-42", "shifter-range-42-example", "shifter-role-dc"],
                "gcp_image_key": "default",
                "gcp_image_profile_fingerprint": expected_plan["instances"][1]["image_profile_fingerprint"],
                "gcp_source_image": "projects/windows-cloud/global/images/family/windows-2022",
                "gcp_bootstrap_capability": "standard",
                "bootstrap_capability": "standard",
                "gcp_service_account_email": "range-host@test-project.iam.gserviceaccount.com",
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
    disk = object()
    image = object()
    global_operations = object()
    region_operations = object()
    zone_operations = object()
    router = object()
    compute_module.NetworksClient = mocker.Mock(return_value=network)
    compute_module.SubnetworksClient = mocker.Mock(return_value=subnetwork)
    compute_module.FirewallsClient = mocker.Mock(return_value=firewall)
    compute_module.AddressesClient = mocker.Mock(return_value=address)
    compute_module.RoutersClient = mocker.Mock(return_value=router)
    compute_module.InstancesClient = mocker.Mock(return_value=instance)
    compute_module.DisksClient = mocker.Mock(return_value=disk)
    compute_module.ImagesClient = mocker.Mock(return_value=image)
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
    assert clients.routers is router
    assert clients.instances is instance
    assert clients.disks is disk
    assert clients.images is image
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
    config = _sample_config()
    order = MagicMock()
    order.attach_mock(clients.instances.delete, "delete_instance")
    order.attach_mock(clients.addresses.delete, "delete_address")
    order.attach_mock(clients.firewalls.delete, "delete_firewall")
    order.attach_mock(clients.subnetworks.delete, "delete_subnetwork")
    order.attach_mock(clients.networks.delete, "delete_network")

    destroy_range_cell(
        "req-123",
        _variables(),
        backend="gce",
        config=config,
        clients=clients,
        secret_ops=secret_ops,
        vertex_ops=vertex_ops,
    )

    assert clients.instances.delete.call_count == 2
    assert clients.addresses.delete.call_count == 2
    assert clients.firewalls.delete.call_count == 5
    assert clients.subnetworks.delete.call_count == 1
    clients.networks.delete.assert_called_once()
    assert mocks.delete_ssh.call_count == 2
    assert mocks.delete_participant_ssh.call_count == 2
    assert mocks.delete_rdp_password.call_count == 2
    assert order.mock_calls == [
        call.delete_instance(project="test-project", zone="us-central1-b", instance="shifter-r-42-example-dc01"),
        call.delete_address(project="test-project", region="us-central1", address="shifter-r-42-example-dc01-ip"),
        call.delete_instance(project="test-project", zone="us-central1-b", instance="shifter-r-42-example-kali"),
        call.delete_address(project="test-project", region="us-central1", address="shifter-r-42-example-kali-ip"),
        call.delete_firewall(project="test-project", firewall="shifter-r-42-egress-web"),
        call.delete_firewall(project="test-project", firewall="shifter-r-42-egress-deny"),
        call.delete_firewall(project="test-project", firewall="shifter-r-42-egress-internal"),
        call.delete_firewall(project="test-project", firewall="shifter-r-42-mgmt"),
        call.delete_firewall(project="test-project", firewall="shifter-r-42-example-ingress"),
        call.delete_subnetwork(project="test-project", region="us-central1", subnetwork="shifter-r-42-example"),
        call.delete_network(project="test-project", network="shifter-range-42"),
    ]


def test_destroy_range_cell_deletes_profile_web_egress_rule(mocker):
    clients = _mock_clients(exists=True)
    secret_ops, _ = _mock_secret_ops(mocker)
    vertex_ops, _ = _mock_vertex_ops(mocker)
    config = _sample_config()
    config = dataclasses.replace(
        config,
        kali=dataclasses.replace(config.kali, allow_public_web_egress=True),
    )

    destroy_range_cell(
        "req-123",
        _variables(),
        backend="gce",
        config=config,
        clients=clients,
        secret_ops=secret_ops,
        vertex_ops=vertex_ops,
    )

    clients.firewalls.delete.assert_any_call(
        project="test-project",
        firewall="shifter-r-42-egress-web",
    )


def test_destroy_range_cell_marks_inherited_disks_for_instance_deletion(mocker):
    clients = _mock_clients(exists=True)
    clients.instances.get.side_effect = None
    clients.instances.get.return_value = SimpleNamespace(
        disks=[SimpleNamespace(device_name="captured-data", auto_delete=False)]
    )
    clients.instances.set_disk_auto_delete.return_value = SimpleNamespace(name="op")
    secret_ops, _mocks = _mock_secret_ops(mocker)
    vertex_ops, _vertex_mocks = _mock_vertex_ops(mocker)

    destroy_range_cell(
        "req-123",
        _variables(),
        config=_sample_config(),
        clients=clients,
        secret_ops=secret_ops,
        vertex_ops=vertex_ops,
    )

    assert clients.instances.set_disk_auto_delete.call_count == 2
    for call_args in clients.instances.set_disk_auto_delete.call_args_list:
        assert call_args.kwargs["device_name"] == "captured-data"
        assert call_args.kwargs["auto_delete"] is True


def test_destroy_range_cell_tolerates_missing_cidr_after_pre_mutation_failure(mocker):
    clients = _mock_clients(exists=False)
    secret_ops, mocks = _mock_secret_ops(mocker)
    vertex_ops, vertex_mocks = _mock_vertex_ops(mocker)
    config = dataclasses.replace(_shared_vpc_config(), private_google_access=True)

    destroy_range_cell(
        "req-123",
        _variables(bindings=[]),
        config=config,
        clients=clients,
        secret_ops=secret_ops,
        vertex_ops=vertex_ops,
    )

    clients.instances.get.assert_called()
    clients.subnetworks.get.assert_called()
    clients.firewalls.get.assert_called()
    vertex_mocks.delete.assert_called_once_with(42, "test-project")
    assert mocks.delete_ssh.call_count == 2


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
    assert state["provider_metadata"]["gcp"]["instance_name"] == "shifter-r-42-example-kali"
    assert state["provider_metadata"]["gcp"]["network_name"] == "shifter-range-42"
    assert state["provider_metadata"]["gcp"]["network_tags"] == [
        "shifter-range-42",
        "shifter-range-42-example",
        "shifter-role-attacker",
    ]
    assert state["provider_metadata"]["gcp"]["image_key"] == "default"
    assert len(state["provider_metadata"]["gcp"]["image_profile_fingerprint"]) == 24
    assert state["provider_metadata"]["gcp"]["source_image"] == "projects/kali/global/images/kali"


def test_instance_output_emits_sftp_root_directory_from_profile():
    """The realized instance output carries the image's declared SFTP root (#375)."""
    base = _sample_config()
    config = dataclasses.replace(
        base,
        kali=dataclasses.replace(base.kali, sftp_root_directory="/home/kali"),
    )
    plan = render_range_cell_plan("req-123", _variables(payload=_scenario_payload()), config)
    attacker = next(instance for instance in plan["instances"] if instance["role"] == "attacker")

    output = instance_output(
        plan,
        attacker,
        InstanceCredentials(
            host_ssh_secret_ref="projects/test/secrets/host-ssh",
            participant_ssh_secret_ref=None,
            rdp_password_secret_ref="projects/test/secrets/rdp",
            ssh_public_key="ssh-ed25519 HOST",
        ),
        config,
    )
    assert output["sftp_root_directory"] == "/home/kali"


def test_instance_output_omits_sftp_root_when_profile_has_none():
    """A profile with no declared root emits no key rather than an empty guess."""
    config = _sample_config()
    plan = render_range_cell_plan("req-123", _variables(payload=_scenario_payload()), config)
    attacker = next(instance for instance in plan["instances"] if instance["role"] == "attacker")

    output = instance_output(
        plan,
        attacker,
        InstanceCredentials(
            host_ssh_secret_ref="projects/test/secrets/host-ssh",
            participant_ssh_secret_ref=None,
            rdp_password_secret_ref="projects/test/secrets/rdp",
            ssh_public_key="ssh-ed25519 HOST",
        ),
        config,
    )
    assert "sftp_root_directory" not in output


def test_render_plan_carries_the_operator_range_telemetry_policy():
    from shared.gcp_range_telemetry import GcpRangeTelemetryPolicy

    config = dataclasses.replace(
        _sample_config(),
        range_telemetry=GcpRangeTelemetryPolicy.model_validate(
            {"vpc_flow_logs": {"flow_sampling": 0.2}, "nat_logs": {"filter": "ERRORS_ONLY"}}
        ),
    )

    plan = render_range_cell_plan("req-123", _variables(), config)

    assert plan["telemetry"]["vpc_flow_logs"]["flow_sampling"] == 0.2
    assert plan["telemetry"]["nat_logs"] == {"enabled": True, "filter": "ERRORS_ONLY"}


def test_zero_egress_range_gets_flow_logs_but_no_nat_path():
    """Logging never authorizes a NAT path: a `none` range keeps no router_nat (#2535)."""
    from gcp_range_cell_resources import subnetwork_resource

    plan = render_range_cell_plan("req-123", _variables(egress_mode="none"), _sample_config())

    assert "router_nat" not in plan and "shared_nat" not in plan
    assert subnetwork_resource(plan, plan["subnets"][0])["log_config"]["enable"] is True


def _existing(log_config: dict | None, **fields: object) -> dict:
    resource = {"fingerprint": "fp-1", **fields}
    if log_config is not None:
        resource["log_config"] = log_config
    return resource


@pytest.mark.parametrize(
    ("observed", "expect_patch"),
    [
        (None, True),
        ({"enable": False}, True),
        (
            {
                "enable": True,
                "aggregation_interval": "INTERVAL_5_SEC",
                "flow_sampling": 0.1,
                "metadata": "INCLUDE_ALL_METADATA",
            },
            True,
        ),
        (
            {
                "enable": True,
                "aggregation_interval": "INTERVAL_5_SEC",
                "flow_sampling": 0.5,
                "metadata": "INCLUDE_ALL_METADATA",
            },
            False,
        ),
    ],
)
def test_ensure_subnetwork_replay_converges_flow_logging(observed, expect_patch):
    from gcp_range_cell_resources import subnetwork_log_config

    plan = render_range_cell_plan("req-123", _variables(), _sample_config())
    subnet = plan["subnets"][0]
    clients = _mock_clients(exists=True)
    clients.subnetworks.get.side_effect = None
    clients.subnetworks.get.return_value = _existing(observed)

    created = _ensure_subnetwork(plan, clients, subnet)

    assert created is False
    clients.subnetworks.insert.assert_not_called()
    if expect_patch:
        clients.subnetworks.patch.assert_called_once_with(
            project=plan["project_id"],
            region=plan["region"],
            subnetwork=subnet["resource_name"],
            subnetwork_resource={"fingerprint": "fp-1", "log_config": subnetwork_log_config(plan)},
        )
    else:
        clients.subnetworks.patch.assert_not_called()


@pytest.mark.parametrize(
    ("observed", "expect_patch"),
    [(None, True), ({"enable": True, "filter": "ERRORS_ONLY"}, True), ({"enable": True, "filter": "ALL"}, False)],
)
def test_ensure_router_nat_replay_converges_nat_logging(observed, expect_patch):
    from gcp_range_cell_resources import router_nat_resource

    plan = render_range_cell_plan("req-123", _variables(), _sample_config())
    nat_name = plan["router_nat"]["nat_name"]
    gateway = {"name": nat_name}
    if observed is not None:
        gateway["log_config"] = observed
    clients = _mock_clients(exists=True)
    clients.routers.get.side_effect = None
    clients.routers.get.return_value = {"name": plan["router_nat"]["router_name"], "nats": [gateway]}

    created = _ensure_router_nat(plan, clients)

    assert created is False
    clients.routers.insert.assert_not_called()
    if expect_patch:
        clients.routers.patch.assert_called_once_with(
            project=plan["project_id"],
            region=plan["region"],
            router=plan["router_nat"]["router_name"],
            router_resource={"nats": router_nat_resource(plan)["nats"]},
        )
    else:
        clients.routers.patch.assert_not_called()
