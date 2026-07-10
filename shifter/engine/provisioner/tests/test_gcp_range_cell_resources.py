"""Tests for GCE range-cell Compute Engine resource bodies.

These render the ``*_resource=`` dicts passed to the Compute clients. Field names
are the proto-plus (snake_case) message fields, including the quirks
``I_p_protocol`` and ``network_i_p``. The functions are pure: given a plan and
config they return a dict, with no cloud calls.
"""

from __future__ import annotations

from config import GCERangeCellConfig, GCERangeImageProfile
from gcp_range_cell_resources import (
    HOST_PUBLIC_KEY_METADATA_KEY,
    address_resource,
    firewall_resource,
    instance_resource,
    network_resource,
    subnetwork_resource,
)


def _plan() -> dict:
    return {
        "region": "us-central1",
        "zone": "us-central1-b",
        "private_google_access": True,
        "labels": {"range": "shifter-range-42", "managed-by": "shifter"},
        "network": {"name": "shifter-range-42", "self_link": "projects/p/global/networks/shifter-range-42"},
    }


def _instance(*, os_type: str = "kali") -> dict:
    return {
        "resource_name": "shifter-r-42-kali",
        "address_name": "shifter-r-42-kali-ip",
        "subnet_name": "polaris",
        "subnetwork_link": "projects/p/regions/us-central1/subnetworks/sn",
        "private_ip": "10.50.2.4",
        "role": "attacker",
        "os_type": os_type,
        "tags": ["shifter-range-42", "shifter-range-42-polaris"],
        "host_ssh_username": "ubuntu",
        "profile": GCERangeImageProfile(
            source_image="projects/kali/global/images/kali",
            machine_type="e2-standard-4",
            disk_size_gb=80,
            disk_type="pd-ssd",
        ),
    }


def _config(*, service_account_email: str = "") -> GCERangeCellConfig:
    return GCERangeCellConfig(
        project_id="test-project",
        region="us-central1",
        zone="us-central1-b",
        network_mode="vpc-per-range",
        service_account_email=service_account_email,
    )


class TestNetworkResource:
    def test_disables_auto_subnets_and_uses_regional_routing(self):
        body = network_resource(_plan())
        assert body == {
            "name": "shifter-range-42",
            "auto_create_subnetworks": False,
            "routing_config": {"routing_mode": "REGIONAL"},
        }


class TestSubnetworkResource:
    def test_renders_cidr_region_and_pga_flag(self):
        subnet = {
            "resource_name": "shifter-r-42-polaris",
            "network_link": "projects/p/global/networks/shifter-range-42",
            "cidr": "10.50.2.0/28",
        }
        body = subnetwork_resource(_plan(), subnet)
        assert body["name"] == "shifter-r-42-polaris"
        assert body["ip_cidr_range"] == "10.50.2.0/28"
        assert body["region"] == "us-central1"
        assert body["private_ip_google_access"] is True


class TestFirewallResource:
    def test_ingress_with_allowed_translates_proto_fields(self):
        firewall = {
            "name": "shifter-r-42-allow-ssh",
            "direction": "INGRESS",
            "priority": 1000,
            "target_tags": ["shifter-range-42"],
            "source_ranges": ["10.40.0.0/20"],
            "allowed": [{"IPProtocol": "tcp", "ports": ["22", "3389"]}],
        }
        body = firewall_resource(_plan(), firewall)
        assert body["network"] == "projects/p/global/networks/shifter-range-42"
        assert body["source_ranges"] == ["10.40.0.0/20"]
        # IPProtocol -> I_p_protocol proto quirk.
        assert body["allowed"] == [{"I_p_protocol": "tcp", "ports": ["22", "3389"]}]
        assert "destination_ranges" not in body
        assert "denied" not in body

    def test_egress_with_denied_and_destination_ranges(self):
        firewall = {
            "name": "shifter-r-42-egress-deny",
            "direction": "EGRESS",
            "priority": 1100,
            "target_tags": ["shifter-range-42"],
            "destination_ranges": ["0.0.0.0/0"],
            "denied": [{"IPProtocol": "all"}],
        }
        body = firewall_resource(_plan(), firewall)
        assert body["destination_ranges"] == ["0.0.0.0/0"]
        assert body["denied"] == [{"I_p_protocol": "all"}]
        assert "source_ranges" not in body
        assert "allowed" not in body


class TestAddressResource:
    def test_internal_address_body(self):
        body = address_resource(_instance())
        assert body == {
            "name": "shifter-r-42-kali-ip",
            "address_type": "INTERNAL",
            "address": "10.50.2.4",
            "subnetwork": "projects/p/regions/us-central1/subnetworks/sn",
        }


def _metadata_map(body: dict) -> dict[str, str]:
    return {item["key"]: item["value"] for item in body["metadata"]["items"]}


class TestInstanceResource:
    def test_linux_instance_full_body(self):
        body = instance_resource(
            _plan(),
            _instance(os_type="kali"),
            _config(service_account_email="range-host@test-project.iam.gserviceaccount.com"),
            ssh_public_key="ssh-ed25519 AAAAkey",
            host_private_key_b64="Ym9ndXM=",
            host_public_key="ssh-ed25519 AAAAhost",
        )
        assert body["machine_type"] == "zones/us-central1-b/machineTypes/e2-standard-4"
        assert body["labels"]["subnet"] == "polaris"
        assert body["labels"]["role"] == "attacker"
        assert body["labels"]["range"] == "shifter-range-42"
        assert body["tags"] == {"items": ["shifter-range-42", "shifter-range-42-polaris"]}
        assert body["network_interfaces"][0]["network_i_p"] == "10.50.2.4"
        disk = body["disks"][0]["initialize_params"]
        assert disk["source_image"] == "projects/kali/global/images/kali"
        assert disk["disk_size_gb"] == 80
        assert disk["disk_type"] == "zones/us-central1-b/diskTypes/pd-ssd"
        assert body["shielded_instance_config"]["enable_secure_boot"] is True
        assert body["deletion_protection"] is False

        meta = _metadata_map(body)
        # Base config metadata carried through.
        assert meta["block-project-ssh-keys"] == "true"
        # Provisioned key installed for the host OS login user, not the participant.
        assert meta["ssh-keys"] == "ubuntu:ssh-ed25519 AAAAkey"
        assert meta[HOST_PUBLIC_KEY_METADATA_KEY] == "ssh-ed25519 AAAAhost"
        # Linux host-key install runs as a startup-script, not the windows PS1 key.
        assert "startup-script" in meta
        assert "windows-startup-script-ps1" not in meta
        assert "ssh_host_ed25519_key" in meta["startup-script"]

        # service_account_email set -> service_accounts block present with scopes.
        assert body["service_accounts"][0]["email"] == "range-host@test-project.iam.gserviceaccount.com"
        assert body["service_accounts"][0]["scopes"] == ["https://www.googleapis.com/auth/cloud-platform"]

    def test_windows_instance_uses_powershell_boot_script(self):
        body = instance_resource(
            _plan(),
            _instance(os_type="windows"),
            _config(),
            ssh_public_key="ssh-ed25519 AAAAkey",
            host_private_key_b64="Ym9ndXM=",
            host_public_key="ssh-ed25519 AAAAhost",
        )
        meta = _metadata_map(body)
        assert "windows-startup-script-ps1" in meta
        assert "startup-script" not in meta
        assert "administrators_authorized_keys" in meta["windows-startup-script-ps1"]

    def test_no_service_account_and_no_host_keys(self):
        body = instance_resource(
            _plan(),
            _instance(os_type="kali"),
            _config(),
            ssh_public_key="ssh-ed25519 AAAAkey",
        )
        meta = _metadata_map(body)
        # No service account configured -> no service_accounts block.
        assert "service_accounts" not in body
        # No host key material -> no host pubkey entry and no startup-script.
        assert HOST_PUBLIC_KEY_METADATA_KEY not in meta
        assert "startup-script" not in meta
        assert meta["ssh-keys"] == "ubuntu:ssh-ed25519 AAAAkey"
