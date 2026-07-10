"""Tests for the GCE range-cell backend."""

from __future__ import annotations

import dataclasses
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock, call

import pytest

from config import GCERangeCellConfig, GCERangeImageProfile
from gcp_range_cells import (
    GCEGuestSecretOps,
    GCEVertexCredentialOps,
    _build_clients,
    apply_range_cell,
    destroy_range_cell,
    render_range_cell_plan,
)
from state_helpers import _build_instance_state


class NotFound(Exception):
    """Fake Google NotFound exception."""


_POLARIS_SUBNETWORK_SELF_LINK = "projects/test-project/regions/us-central1/subnetworks/shifter-r-42-polaris"


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
        portal_network_cidrs=("10.40.0.0/20",),
    )


def _variables() -> dict:
    return {
        "range_id": 42,
        "request_uuid": "req-123",
        "subnets": [
            {
                "name": "polaris",
                "uuid": "subnet-uuid",
                "cidr": "10.50.2.0/28",
                "instances": [
                    {
                        "uuid": "linux-uuid",
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
    }


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
        ensure_ssh=mocker.Mock(return_value=("projects/test/secrets/ssh", "ssh-ed25519 AAAA")),
        ensure_rdp_password=mocker.Mock(return_value=("projects/test/secrets/rdp", "Password-1")),
        delete_ssh=mocker.Mock(),
        delete_rdp_password=mocker.Mock(),
    )
    return (
        GCEGuestSecretOps(
            ensure_ssh=mocks.ensure_ssh,
            ensure_rdp_password=mocks.ensure_rdp_password,
            delete_ssh=mocks.delete_ssh,
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


def test_render_range_cell_plan_rejects_subnet_without_uuid():
    variables = {"range_id": 42, "subnets": [{"name": "polaris", "cidr": "10.50.2.0/28"}]}

    with pytest.raises(RuntimeError, match="requires name and uuid"):
        render_range_cell_plan("req-123", variables, _sample_config())


def test_render_range_cell_plan_rejects_subnet_without_cidr_when_images_required():
    variables = {"range_id": 42, "subnets": [{"name": "polaris", "uuid": "subnet-uuid"}]}

    with pytest.raises(RuntimeError, match="requires a cidr"):
        render_range_cell_plan("req-123", variables, _sample_config())


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
        "linux-uuid": "10.50.2.3",
        "dc-uuid": "10.50.2.4",
    }
    assert [instance["private_ip"] for instance in plan["instances"]] == ["10.50.2.3", "10.50.2.4"]
    assert {firewall["name"] for firewall in plan["firewalls"]} >= {
        "shifter-r-42-polaris-ingress",
        "shifter-r-42-mgmt",
        "shifter-r-42-egress-internal",
        "shifter-r-42-egress-deny",
    }


def test_render_plan_destroy_tolerates_missing_subnet_cidr():
    # Auto-cleanup after a provision that failed before CIDR allocation renders
    # the destroy plan with require_images=False; the subnet is deleted by
    # resource name, so an empty CIDR must not raise.
    variables = _variables()
    variables["subnets"][0]["cidr"] = ""
    plan = render_range_cell_plan("req-123", variables, _sample_config(), require_images=False)
    subnet = plan["subnets"][0]
    assert subnet["cidr"] == ""
    assert subnet["ip_assignments"] == {}
    assert subnet["resource_name"]


def test_render_plan_provision_requires_subnet_cidr():
    variables = _variables()
    variables["subnets"][0]["cidr"] = ""
    with pytest.raises(RuntimeError, match="requires a cidr"):
        render_range_cell_plan("req-123", variables, _sample_config())


def test_render_plan_requires_subnet_name_and_uuid():
    # name/uuid identify the subnet for both provision and destroy, so they are
    # required in either mode.
    variables = _variables()
    variables["subnets"][0]["uuid"] = ""
    with pytest.raises(RuntimeError, match="requires name and uuid"):
        render_range_cell_plan("req-123", variables, _sample_config(), require_images=False)


def test_render_plan_translates_polaris_vm_to_docker_host_access():
    """A polaris-vm Docker host uses the host login user + management sshd port.

    The Kali participant container publishes the host's :22/:3389, so the
    provisioner must drive the host sshd on the management port as the host
    login user, not the participant "kali" user.
    """
    variables = _variables()
    kali = variables["subnets"][0]["instances"][0]
    kali["ami_key"] = "polaris-vm"
    kali["instance_type"] = "m5.2xlarge"  # AWS shape; must NOT reach GCE.

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

    variables = _variables()
    variables["subnets"][0]["instances"][0]["ami_key"] = "polaris-vm"
    plan = render_range_cell_plan("req-123", variables, _vertex_config())
    host = plan["instances"][0]

    body = instance_resource(plan, host, _vertex_config(), ssh_public_key="ssh-ed25519 AAAA")
    ssh_keys = next(item for item in body["metadata"]["items"] if item["key"] == "ssh-keys")

    assert ssh_keys["value"] == "ubuntu:ssh-ed25519 AAAA"


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

    output = apply_range_cell(
        "req-123",
        _variables(),
        config=_sample_config(),
        clients=clients,
        secret_ops=secret_ops,
    )

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
                    "linux-uuid": "10.50.2.3",
                    "dc-uuid": "10.50.2.4",
                },
            }
        },
        "instances": [
            {
                "uuid": "linux-uuid",
                "name": "kali",
                "asset_type": "gce_vm",
                "role": "attacker",
                "os": "kali",
                "subnet_name": "polaris",
                "instance_id": "shifter-r-42-polaris-kali",
                "private_ip": "10.50.2.3",
                "ssh_key_secret_arn": "projects/test/secrets/ssh",
                "ssh_username": "kali",
                "public_key": "ssh-ed25519 AAAA",
                "gcp_host_public_key": "",
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
                "gcp_service_account_email": "range-host@test-project.iam.gserviceaccount.com",
                "rdp_password_secret_arn": "projects/test/secrets/rdp",
                "gcp_rdp_password_secret_ref": "projects/test/secrets/rdp",
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
                "ssh_key_secret_arn": "projects/test/secrets/ssh",
                "ssh_username": "Administrator",
                "public_key": "ssh-ed25519 AAAA",
                "gcp_host_public_key": "",
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

    with pytest.raises(RuntimeError, match="insert failed"):
        apply_range_cell(
            "req-123",
            _variables(),
            config=_sample_config(),
            clients=clients,
            secret_ops=secret_ops,
            cleanup_range_cell=cleanup,
        )

    cleanup.assert_called_once_with("req-123", _variables())


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

    with pytest.raises(RuntimeError, match="QUOTA_EXCEEDED: too many networks"):
        apply_range_cell(
            "req-123",
            _variables(),
            config=_sample_config(),
            clients=clients,
            secret_ops=secret_ops,
            cleanup_range_cell=cleanup,
        )

    cleanup.assert_called_once_with("req-123", _variables())


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
