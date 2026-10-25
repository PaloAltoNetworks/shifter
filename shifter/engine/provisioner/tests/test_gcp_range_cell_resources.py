"""Tests for GCE range-cell Compute Engine resource bodies.

These render the ``*_resource=`` dicts passed to the Compute clients. Field names
are the proto-plus (snake_case) message fields, including the quirks
``I_p_protocol`` and ``network_i_p``. The functions are pure: given a plan and
config they return a dict, with no cloud calls.
"""

from __future__ import annotations

from shared.gcp_range_telemetry import GcpRangeTelemetryPolicy

from config import GCERangeCellConfig, GCERangeImageProfile, gce_image_profile_fingerprint
from gcp_range_cell_plan import range_telemetry_plan
from gcp_range_cell_resources import (
    HOST_PUBLIC_KEY_METADATA_KEY,
    address_resource,
    firewall_resource,
    instance_resource,
    log_config_matches,
    network_resource,
    router_nat_resource,
    subnetwork_resource,
)


def _plan() -> dict:
    return {
        "project_id": "test-project",
        "region": "us-central1",
        "zone": "us-central1-b",
        "range_id": 42,
        "request_uuid": "87a99f87-5af2-46e6-a459-0e5eb1ab1bf2",
        "private_google_access": True,
        "labels": {"range": "shifter-range-42", "managed-by": "shifter"},
        "network": {"name": "shifter-range-42", "self_link": "projects/p/global/networks/shifter-range-42"},
        "telemetry": range_telemetry_plan(GcpRangeTelemetryPolicy()),
    }


def _telemetry(**overrides: dict) -> dict:
    return range_telemetry_plan(GcpRangeTelemetryPolicy.model_validate(overrides))


def _instance(*, os_type: str = "kali", attach_service_account: bool = True) -> dict:
    profile = GCERangeImageProfile(
        source_image="projects/kali/global/images/kali",
        machine_type="e2-standard-4",
        disk_size_gb=80,
        disk_type="pd-ssd",
    )
    return {
        "resource_name": "shifter-r-42-kali",
        "address_name": "shifter-r-42-kali-ip",
        "subnet_name": "example",
        "subnetwork_link": "projects/p/regions/us-central1/subnetworks/sn",
        "private_ip": "10.50.2.4",
        "role": "attacker",
        "os_type": os_type,
        "tags": ["shifter-range-42", "shifter-range-42-example"],
        "host_ssh_username": "ubuntu",
        "ssh_port": 22,
        "profile": profile,
        "image_key": "",
        "image_profile_fingerprint": gce_image_profile_fingerprint(profile),
        "attach_service_account": attach_service_account,
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
            "resource_name": "shifter-r-42-example",
            "network_link": "projects/p/global/networks/shifter-range-42",
            "cidr": "10.50.2.0/28",
        }
        body = subnetwork_resource(_plan(), subnet)
        assert body["name"] == "shifter-r-42-example"
        assert body["ip_cidr_range"] == "10.50.2.0/28"
        assert body["region"] == "us-central1"
        assert body["private_ip_google_access"] is True


_TELEMETRY_SUBNET = {
    "resource_name": "shifter-r-42-example",
    "network_link": "projects/p/global/networks/shifter-range-42",
    "cidr": "10.50.2.0/28",
}


class TestRangeAuditTelemetry:
    """Subnet flow logs and NAT logging ride in the provider bodies (#2535)."""

    def _nat_plan(self, telemetry: dict | None = None) -> dict:
        plan = _plan()
        if telemetry is not None:
            plan["telemetry"] = telemetry
        plan["router_nat"] = {
            "router_name": "shifter-r-42-router",
            "nat_name": "shifter-r-42-nat",
            "subnetwork_self_links": ["projects/p/regions/us-central1/subnetworks/shifter-r-42-example"],
        }
        return plan

    def test_subnetwork_enables_flow_logs_with_default_settings(self):
        body = subnetwork_resource(_plan(), _TELEMETRY_SUBNET)

        assert body["log_config"] == {
            "enable": True,
            "aggregation_interval": "INTERVAL_5_SEC",
            "flow_sampling": 0.5,
            "metadata": "INCLUDE_ALL_METADATA",
        }

    def test_subnetwork_uses_the_operator_flow_log_override(self):
        plan = _plan()
        plan["telemetry"] = _telemetry(
            vpc_flow_logs={
                "aggregation_interval": "INTERVAL_1_MIN",
                "flow_sampling": 0.1,
                "metadata": "EXCLUDE_ALL_METADATA",
            }
        )

        body = subnetwork_resource(plan, _TELEMETRY_SUBNET)

        assert body["log_config"] == {
            "enable": True,
            "aggregation_interval": "INTERVAL_1_MIN",
            "flow_sampling": 0.1,
            "metadata": "EXCLUDE_ALL_METADATA",
        }

    def test_subnetwork_explicitly_disables_flow_logs_when_the_operator_turns_them_off(self):
        plan = _plan()
        plan["telemetry"] = _telemetry(vpc_flow_logs={"enabled": False})

        assert subnetwork_resource(plan, _TELEMETRY_SUBNET)["log_config"] == {"enable": False}

    def test_range_owned_nat_logs_translations_and_errors_by_default(self):
        body = router_nat_resource(self._nat_plan())

        assert body["nats"][0]["log_config"] == {"enable": True, "filter": "ALL"}
        assert body["nats"][0]["source_subnetwork_ip_ranges_to_nat"] == "LIST_OF_SUBNETWORKS"

    def test_range_owned_nat_uses_the_operator_filter_or_disable(self):
        errors_only = router_nat_resource(self._nat_plan(_telemetry(nat_logs={"filter": "ERRORS_ONLY"})))
        disabled = router_nat_resource(self._nat_plan(_telemetry(nat_logs={"enabled": False})))

        assert errors_only["nats"][0]["log_config"] == {"enable": True, "filter": "ERRORS_ONLY"}
        assert disabled["nats"][0]["log_config"] == {"enable": False}

    def test_log_config_comparison_reads_provider_messages_and_enums(self):
        desired = subnetwork_resource(_plan(), _TELEMETRY_SUBNET)["log_config"]
        enum = type("Enum", (), {"name": "INTERVAL_5_SEC"})()
        provider = type(
            "LogConfig",
            (),
            {
                "enable": True,
                "aggregation_interval": enum,
                "flow_sampling": 0.5000001,
                "metadata": "INCLUDE_ALL_METADATA",
            },
        )()

        assert log_config_matches(provider, desired) is True
        assert log_config_matches(None, desired) is False
        assert log_config_matches({**desired, "flow_sampling": 0.1}, desired) is False
        assert log_config_matches({"enable": False}, desired) is False
        assert log_config_matches(None, {"enable": False}) is True
        assert log_config_matches({"enable": True, "filter": "ALL"}, {"enable": False}) is False


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
        assert body["labels"]["subnet"] == "example"
        assert body["labels"]["role"] == "attacker"
        assert body["labels"]["range"] == "shifter-range-42"
        assert body["tags"] == {"items": ["shifter-range-42", "shifter-range-42-example"]}
        assert body["network_interfaces"][0]["network_i_p"] == "10.50.2.4"
        assert "access_configs" not in body["network_interfaces"][0]
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

        # The composition script is appended to the host-key script, so the
        # host-key half must never terminate the shell: an `exit` here would
        # silently skip building the range's content (issue #987).
        startup = meta["startup-script"]
        host_key_half = startup.split("shifter_install_host_key || true", 1)[0]
        assert "\nexit " not in host_key_half, "host-key install must not exit the shared startup script"

        # A divergence between the injected key and the key sshd serves leaves
        # every terminal session failing with HostKeyNotVerifiable, so the script
        # verifies convergence and says so on the serial console rather than
        # swallowing the failure (issue #987).
        assert "shifter-hostkey:" in startup, "host-key install must log a diagnosable marker"
        assert "ssh-keyscan" in startup, "host-key install must verify sshd serves the injected key"

        # service_account_email set -> service_accounts block present with scopes.
        assert body["service_accounts"][0]["email"] == "range-host@test-project.iam.gserviceaccount.com"
        assert body["service_accounts"][0]["scopes"] == ["https://www.googleapis.com/auth/cloud-platform"]

    def test_host_key_converge_check_targets_the_instance_mgmt_ssh_port(self):
        """A Docker host's sshd is on a mgmt port; :22 is the container's.

        The converge check must scan the host's actual management port or it
        would scan the container's sshd (or a closed port) and always report
        FAILED even when the host key is correctly served.
        """
        instance = _instance(os_type="kali")
        instance["ssh_port"] = 2222
        body = instance_resource(
            _plan(),
            instance,
            _config(),
            ssh_public_key="ssh-ed25519 AAAAkey",
            host_private_key_b64="Ym9ndXM=",
            host_public_key="ssh-ed25519 AAAAhost",
        )
        startup = _metadata_map(body)["startup-script"]
        assert "ssh-keyscan -t ed25519 -T 5 -p 2222 127.0.0.1" in startup

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

    def test_configured_service_account_is_omitted_when_guest_does_not_need_cloud_apis(self):
        body = instance_resource(
            _plan(),
            _instance(attach_service_account=False),
            _config(service_account_email="range-host@test-project.iam.gserviceaccount.com"),
            ssh_public_key="ssh-ed25519 AAAAkey",
        )

        assert "service_accounts" not in body

    def test_machine_image_instance_replaces_inherited_identity_network_and_metadata(self):
        instance = _instance(attach_service_account=False)
        instance["profile"] = GCERangeImageProfile(
            source_machine_image="projects/test/global/machineImages/nested-host-v1",
            machine_type="n2-standard-8",
            bootstrap_capability="preconfigured-machine-host",
            participant_container_name="participant-desktop",
            participant_username="operator",
            host_ssh_username="hostadmin",
            host_ssh_port=2222,
        )
        instance["host_ssh_username"] = "hostadmin"
        instance["service_account_email"] = "sh-range-host-4@test-project.iam.gserviceaccount.com"

        body = instance_resource(
            _plan(),
            instance,
            _config(service_account_email="deployment-wide@test-project.iam.gserviceaccount.com"),
            ssh_public_key="ssh-ed25519 AAAAkey",
            host_private_key_b64="Ym9ndXM=",
            host_public_key="ssh-ed25519 AAAAhost",
        )

        assert "disks" not in body
        assert "shielded_instance_config" not in body
        assert body["advanced_machine_features"] == {"enable_nested_virtualization": True}
        assert body["network_interfaces"] == [
            {
                "subnetwork": "projects/p/regions/us-central1/subnetworks/sn",
                "network_i_p": "10.50.2.4",
            }
        ]
        assert body["service_accounts"][0]["email"] == "sh-range-host-4@test-project.iam.gserviceaccount.com"
        assert _metadata_map(body)["ssh-keys"] == "hostadmin:ssh-ed25519 AAAAkey"

    def test_custom_image_preconfigured_host_has_nested_virt_and_owned_boot_disk(self):
        instance = _instance(attach_service_account=False)
        instance["profile"] = GCERangeImageProfile(
            source_image="projects/test/global/images/nested-host-v1",
            machine_type="n2-standard-8",
            disk_size_gb=220,
            bootstrap_capability="preconfigured-machine-host",
            participant_container_name="participant-desktop",
            participant_username="operator",
            host_ssh_username="hostadmin",
        )
        instance["host_ssh_username"] = "hostadmin"
        body = instance_resource(_plan(), instance, _config(), ssh_public_key="ssh-ed25519 AAAAkey")
        assert body["advanced_machine_features"] == {"enable_nested_virtualization": True}
        assert body["disks"][0]["auto_delete"] is True
        assert body["disks"][0]["initialize_params"]["source_image"] == instance["profile"].source_image
        assert body["service_accounts"] == []
        assert body["shielded_instance_config"]["enable_secure_boot"] is True

    def test_machine_image_instance_clears_inherited_identity_when_none_is_authorized(self):
        instance = _instance(attach_service_account=False)
        instance["profile"] = GCERangeImageProfile(
            source_machine_image="projects/test/global/machineImages/nested-host-v1",
            machine_type="n2-standard-8",
            bootstrap_capability="preconfigured-machine-host",
            participant_container_name="participant-desktop",
            participant_username="operator",
            host_ssh_username="hostadmin",
            host_ssh_port=2222,
        )
        instance["service_account_email"] = ""

        body = instance_resource(
            _plan(),
            instance,
            _config(service_account_email="deployment-wide@test-project.iam.gserviceaccount.com"),
            ssh_public_key="ssh-ed25519 AAAAkey",
        )

        assert body["service_accounts"] == []
