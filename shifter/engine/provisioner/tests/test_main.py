"""Tests for provisioner parsing and utility functions.

Only tests for pure logic - no mock-heavy integration tests.
"""

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestParseSerialNumber:
    """Tests for parse_serial_number helper function."""

    def test_extracts_serial_from_system_info(self):
        """Extracts serial from PAN-OS show system info output."""
        from ngfw_polling import parse_serial_number

        system_info = """hostname: PA-VM
serial: 007200001267
software-version: 11.1.0
"""
        assert parse_serial_number(system_info) == "007200001267"

    def test_extracts_serial_case_insensitive(self):
        """Handles case variations."""
        from ngfw_polling import parse_serial_number

        assert parse_serial_number("SERIAL: ABC123DEF456") == "ABC123DEF456"

    def test_extracts_serial_with_extra_whitespace(self):
        """Handles extra whitespace."""
        from ngfw_polling import parse_serial_number

        result = parse_serial_number("serial:   007200001267   ")
        assert result == "007200001267"

    def test_returns_none_when_not_found(self):
        """Returns None when serial not in output."""
        from ngfw_polling import parse_serial_number

        result = parse_serial_number("hostname: PA-VM\nsoftware-version: 11.1.0")
        assert result is None

    def test_returns_none_for_unknown_placeholder(self):
        """Returns None for 'unknown' placeholder."""
        from ngfw_polling import parse_serial_number

        assert parse_serial_number("serial: unknown") is None

    def test_returns_none_for_none_placeholder(self):
        """Returns None for 'none' placeholder."""
        from ngfw_polling import parse_serial_number

        assert parse_serial_number("serial: none") is None

    def test_returns_none_for_empty_output(self):
        """Returns None for empty output."""
        from ngfw_polling import parse_serial_number

        assert parse_serial_number("") is None


class TestParseDeviceCertificateStatus:
    """Tests for parse_device_certificate_status helper function."""

    def test_extracts_valid_cert_status(self):
        """Extracts 'Valid' certificate status."""
        from ngfw_polling import parse_device_certificate_status

        system_info = "device-certificate-status: Valid"
        assert parse_device_certificate_status(system_info) == "Valid"

    def test_extracts_cert_status_case_insensitive(self):
        """Handles case variations in field name."""
        from ngfw_polling import parse_device_certificate_status

        result = parse_device_certificate_status("DEVICE-CERTIFICATE-STATUS: Valid")
        assert result == "Valid"

    def test_returns_none_when_not_found(self):
        """Returns None when cert status not in output."""
        from ngfw_polling import parse_device_certificate_status

        assert parse_device_certificate_status("serial: 12345") is None

    def test_returns_none_for_empty_output(self):
        """Returns None for empty output."""
        from ngfw_polling import parse_device_certificate_status

        assert parse_device_certificate_status("") is None


class TestRangeStatePayloads:
    """Tests for provider-aware range state serialization helpers."""

    def test_build_subnet_state_preserves_aws_fields(self):
        from state_helpers import _build_subnet_state

        subnet_state = _build_subnet_state(
            {
                "subnet_id": "subnet-123",
                "subnet_cidr": "10.1.1.0/28",
                "security_group_id": "sg-123",
                "route_table_id": "rtb-123",
            },
            provider="aws",
        )

        assert subnet_state["cloud_provider"] == "aws"
        assert subnet_state["subnet_id"] == "subnet-123"
        assert subnet_state["aws_subnet_id"] == "subnet-123"
        assert subnet_state["aws_cidr"] == "10.1.1.0/28"
        assert subnet_state["provider_metadata"] == {
            "aws": {
                "subnet_id": "subnet-123",
                "cidr": "10.1.1.0/28",
                "security_group_id": "sg-123",
                "route_table_id": "rtb-123",
            }
        }

    def test_build_subnet_state_persists_gdc_metadata_without_aws_aliases(self):
        from state_helpers import _build_subnet_state

        subnet_state = _build_subnet_state(
            {
                "subnet_id": "range-42-attack",
                "subnet_cidr": "10.200.0.96/28",
                "security_group_id": "",
                "route_table_id": "",
                "gdc_namespace": "range-42",
                "gdc_network_name": "range-42-attack",
                "gdc_nad_name": "range-42-attack",
                "gdc_gateway_ip": "10.200.0.97",
                "gdc_ipam_range": "10.200.0.96/28",
            },
            provider="gcp",
        )

        assert subnet_state["cloud_provider"] == "gcp"
        assert subnet_state["subnet_id"] == "range-42-attack"
        assert subnet_state["aws_subnet_id"] is None
        assert subnet_state["provider_metadata"] == {
            "gcp": {
                "namespace": "range-42",
                "network_name": "range-42-attack",
                "nad_name": "range-42-attack",
                "gateway_ip": "10.200.0.97",
                "ipam_range": "10.200.0.96/28",
            }
        }

    def test_build_instance_state_preserves_aws_instance_alias(self):
        from state_helpers import _build_instance_state

        instance_state = _build_instance_state(
            {
                "instance_id": "i-abc123",
                "private_ip": "10.1.1.10",
                "ssh_key_secret_arn": "arn:aws:secretsmanager:us-east-2:123:secret:key",
                "subnet_name": "attack",
            },
            provider="aws",
        )

        assert instance_state["cloud_provider"] == "aws"
        assert instance_state["instance_id"] == "i-abc123"
        assert instance_state["aws_instance_id"] == "i-abc123"
        assert instance_state["provider_metadata"] == {"aws": {"instance_id": "i-abc123"}}

    def test_build_instance_state_collects_gdc_metadata(self):
        from state_helpers import _build_instance_state

        instance_state = _build_instance_state(
            {
                "asset_type": "vm_runtime_vm",
                "instance_id": "vmrt-vm-1",
                "private_ip": "10.200.0.110",
                "ssh_key_secret_arn": "projects/test/secrets/vmrt-ssh-key",
                "ssh_username": "ubuntu",
                "subnet_name": "attack",
                "gdc_vm_name": "vmrt-vm-1",
                "gdc_namespace": "range-42",
                "gdc_network_name": "range-42-attack",
                "gdc_ip": "10.200.0.110",
                "gdc_ssh_secret_id": "projects/test/secrets/vmrt-ssh-key",
                "gdc_username": "ubuntu",
                "vmruntime_disk_name": "vmrt-vm-1-disk",
            },
            provider="gcp",
        )

        assert instance_state["cloud_provider"] == "gcp"
        assert instance_state["asset_type"] == "vm_runtime_vm"
        assert instance_state["aws_instance_id"] is None
        assert instance_state["ssh_username"] == "ubuntu"
        assert instance_state["provider_metadata"] == {
            "gcp": {
                "vm_name": "vmrt-vm-1",
                "namespace": "range-42",
                "network_name": "range-42-attack",
                "ip": "10.200.0.110",
                "ssh_secret_id": "projects/test/secrets/vmrt-ssh-key",
                "username": "ubuntu",
                "disk_name": "vmrt-vm-1-disk",
            }
        }

    def test_build_instance_state_collects_gdc_alias_metadata_under_gcp_provider(self):
        from state_helpers import _build_instance_state

        instance_state = _build_instance_state(
            {
                "instance_id": "vmrt-vm-1",
                "private_ip": "10.200.0.110",
                "ssh_key_secret_arn": "projects/test/secrets/vmrt-ssh-key",
                "ssh_username": "Administrator",
                "subnet_name": "scenario-a",
                "gdc_vm_name": "vmrt-vm-1",
                "gdc_namespace": "range-42",
                "gdc_network_name": "scenario-a-net",
                "gdc_ip": "10.200.0.110",
                "vmruntime_disk_name": "vmrt-vm-1-disk",
            },
            provider="gcp",
        )

        assert instance_state["provider_metadata"] == {
            "gcp": {
                "vm_name": "vmrt-vm-1",
                "namespace": "range-42",
                "network_name": "scenario-a-net",
                "ip": "10.200.0.110",
                "disk_name": "vmrt-vm-1-disk",
            }
        }

    def test_build_instance_state_propagates_rdp_password_secret_arn_aws(self):
        # Per #762: the AWS Terraform range module emits a per-instance
        # rdp_password_secret_arn alongside ssh_key_secret_arn. The
        # state writer must propagate it so engine.services can resolve
        # it through shared.cloud at access time.
        from state_helpers import _build_instance_state

        rdp_arn = "arn:aws:secretsmanager:us-east-2:1:secret:shifter/dev/range/1/victim-abc-rdp-password"
        ssh_arn = "arn:aws:secretsmanager:us-east-2:1:secret:shifter/dev/range/1/victim-abc-ssh-key"
        instance_state = _build_instance_state(
            {
                "instance_id": "i-abc123",
                "private_ip": "10.1.1.10",
                "ssh_key_secret_arn": ssh_arn,
                "rdp_password_secret_arn": rdp_arn,
                "subnet_name": "attack",
            },
            provider="aws",
        )

        assert instance_state["rdp_password_secret_arn"] == rdp_arn

    def test_build_instance_state_propagates_rdp_password_secret_ref_gcp(self):
        # Per #762: GDC VM Runtime creates a per-instance Secret Manager
        # secret for the RDP password and stores the resource path in
        # the asset payload as rdp_password_secret_arn. The state writer
        # surfaces it both at the top level (for engine.services'
        # symmetric resolver) and inside provider_metadata.gcp (for
        # state-shape consistency with ssh_key_secret_arn).
        from state_helpers import _build_instance_state

        rdp_ref = "projects/test/secrets/shifter-gcp-dev-range-42-victim-abc-rdp-password"
        instance_state = _build_instance_state(
            {
                "asset_type": "vm_runtime_vm",
                "instance_id": "vmrt-vm-1",
                "private_ip": "10.200.0.110",
                "ssh_key_secret_arn": "projects/test/secrets/vmrt-ssh-key",
                "rdp_password_secret_arn": rdp_ref,
                "ssh_username": "ubuntu",
                "subnet_name": "attack",
                "gdc_vm_name": "vmrt-vm-1",
                "gdc_namespace": "range-42",
                "gdc_ip": "10.200.0.110",
                "gdc_rdp_password_secret_ref": rdp_ref,
            },
            provider="gcp",
        )

        assert instance_state["rdp_password_secret_arn"] == rdp_ref
        assert instance_state["provider_metadata"]["gcp"].get("rdp_password_secret_ref") == rdp_ref

    def test_build_provisioned_instance_payload_keeps_legacy_fields_and_adds_provider_metadata(self):
        from state_helpers import _build_provisioned_instance_payload

        payload = _build_provisioned_instance_payload(
            {
                "uuid": "inst-123",
                "name": "workstation-1",
                "asset_type": "vm_runtime_vm",
                "role": "victim",
                "os": "windows",
                "subnet_name": "victims",
                "instance_id": "vmrt-vm-1",
                "private_ip": "10.200.0.110",
                "ssh_key_secret_arn": "projects/test/secrets/vmrt-ssh-key",
                "ssh_username": "Administrator",
                "gdc_vm_name": "vmrt-vm-1",
                "gdc_namespace": "range-42",
            },
            provider="gcp",
        )

        assert payload["uuid"] == "inst-123"
        assert payload["asset_type"] == "vm_runtime_vm"
        assert payload["os_type"] == "windows"
        assert payload["instance_id"] == "vmrt-vm-1"
        assert payload["ssh_key_secret_arn"] == "projects/test/secrets/vmrt-ssh-key"
        assert payload["ssh_username"] == "Administrator"
        assert payload["cloud_provider"] == "gcp"
        assert payload["provider_metadata"] == {"gcp": {"vm_name": "vmrt-vm-1", "namespace": "range-42"}}

    def test_build_provisioned_instance_payload_propagates_rdp_password_secret_arn(self):
        # Per #762: Range.provisioned_instances entries carry the
        # rdp_password_secret_arn so engine.services can resolve a
        # guest password through shared.cloud at access time.
        from state_helpers import _build_provisioned_instance_payload

        rdp_arn = "arn:aws:secretsmanager:us-east-2:1:secret:shifter/dev/range/1/victim-abc-rdp-password"
        ssh_arn = "arn:aws:secretsmanager:us-east-2:1:secret:shifter/dev/range/1/victim-abc-ssh-key"
        payload = _build_provisioned_instance_payload(
            {
                "uuid": "inst-456",
                "name": "victim-1",
                "asset_type": "ec2_instance",
                "role": "victim",
                "os": "kali",
                "subnet_name": "attack",
                "instance_id": "i-abc",
                "private_ip": "10.1.1.10",
                "ssh_key_secret_arn": ssh_arn,
                "rdp_password_secret_arn": rdp_arn,
                "ssh_username": "kali",
            },
            provider="aws",
        )

        assert payload["rdp_password_secret_arn"] == rdp_arn

    def test_get_cloud_provider_defaults_to_aws(self):
        from state_helpers import _get_cloud_provider

        with pytest.MonkeyPatch.context() as mp:
            mp.delenv("CLOUD_PROVIDER", raising=False)
            assert _get_cloud_provider() == "aws"

    def test_get_cloud_provider_reads_env(self):
        from state_helpers import _get_cloud_provider

        with pytest.MonkeyPatch.context() as mp:
            mp.setenv("CLOUD_PROVIDER", "gcp")
            assert _get_cloud_provider() == "gcp"

    def test_write_provisioned_state_persists_gcp_metadata_blocks(self, monkeypatch):
        from provisioner_db import write_provisioned_state

        mock_cursor = MagicMock()
        mock_cursor.rowcount = 1
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)

        subnets = {
            "attack": {
                "uuid": "subnet-123",
                "subnet_id": "range-42-attack",
                "subnet_cidr": "10.200.0.96/28",
                "security_group_id": "",
                "route_table_id": "",
                "gdc_namespace": "range-42",
                "gdc_network_name": "range-42-attack",
                "gdc_nad_name": "range-42-attack",
                "gdc_gateway_ip": "10.200.0.97",
            }
        }
        instances = [
            {
                "uuid": "inst-123",
                "name": "workstation-1",
                "asset_type": "vm_runtime_vm",
                "role": "victim",
                "os": "windows",
                "subnet_name": "attack",
                "instance_id": "vmrt-vm-1",
                "private_ip": "10.200.0.110",
                "ssh_key_secret_arn": "projects/test/secrets/vmrt-ssh-key",
                "gdc_vm_name": "vmrt-vm-1",
                "gdc_namespace": "range-42",
                "gdc_network_name": "range-42-attack",
                "gdc_ip": "10.200.0.110",
                "vmruntime_disk_name": "vmrt-vm-1-disk",
            }
        ]

        monkeypatch.setenv("CLOUD_PROVIDER", "gcp")
        monkeypatch.setattr("provisioner_db.get_db_connection", MagicMock(return_value=mock_conn))
        with patch.dict("os.environ", {"CLOUD_PROVIDER": "gcp"}, clear=True):
            write_provisioned_state(range_id=42, subnets=subnets, instances=instances, ngfw_instance_id=None)

        subnet_state = json.loads(mock_cursor.execute.call_args_list[0].args[1][0])
        instance_state = json.loads(mock_cursor.execute.call_args_list[1].args[1][0])
        provisioned_instances = json.loads(mock_cursor.execute.call_args_list[2].args[1][0])

        assert subnet_state["cloud_provider"] == "gcp"
        assert subnet_state["aws_subnet_id"] is None
        assert subnet_state["provider_metadata"]["gcp"]["network_name"] == "range-42-attack"
        assert instance_state["cloud_provider"] == "gcp"
        assert instance_state["aws_instance_id"] is None
        assert instance_state["provider_metadata"]["gcp"]["namespace"] == "range-42"
        assert provisioned_instances[0]["cloud_provider"] == "gcp"
        assert provisioned_instances[0]["asset_type"] == "vm_runtime_vm"
        assert provisioned_instances[0]["instance_id"] == "vmrt-vm-1"
        assert provisioned_instances[0]["provider_metadata"]["gcp"]["vm_name"] == "vmrt-vm-1"


class TestGdcProvisioning:
    """Tests for the active GDC VM Runtime range path."""

    def test_run_terraform_provision_runs_setup_and_writes_state_for_gdc_ranges(self, monkeypatch):
        from config import RangeNetworkConfig
        from terraform_ops import _run_terraform_provision

        range_spec = {
            "subnets": [
                {
                    "name": "attack",
                    "uuid": "subnet-123",
                    "instances": [
                        {
                            "uuid": "inst-123",
                            "name": "attacker",
                            "asset_type": "vm_runtime_vm",
                            "role": "attacker",
                            "os_type": "kali",
                        }
                    ],
                }
            ]
        }

        terraform_output = {
            "subnets": {
                "attack": {
                    "uuid": "subnet-123",
                    "subnet_id": "range-42-attack",
                    "subnet_cidr": "10.200.0.96/28",
                    "gdc_namespace": "range-42",
                    "gdc_network_name": "range-42-attack",
                }
            },
            "instances": [
                {
                    "uuid": "inst-123",
                    "name": "attacker",
                    "asset_type": "vm_runtime_vm",
                    "role": "attacker",
                    "os": "kali",
                    "subnet_name": "attack",
                    "instance_id": "range-42-attack-attacker-1234",
                    "private_ip": "10.200.0.104",
                    "public_key": "ssh-rsa AAAA",
                    "ssh_key_secret_arn": "projects/test/secrets/range-42-attacker-ssh",
                    "ssh_username": "kali",
                    "gdc_vm_name": "range-42-attack-attacker-1234",
                    "gdc_namespace": "range-42",
                    "gdc_network_name": "range-42-attack",
                    "gdc_ip": "10.200.0.104",
                    "vmruntime_disk_name": "range-42-attack-attacker-1234-boot",
                }
            ],
        }

        mock_setup = MagicMock()
        mock_write_state = MagicMock()
        monkeypatch.setattr("terraform_ops.publish_status_update", MagicMock())
        monkeypatch.setattr(
            "terraform_ops.load_range_network_config",
            MagicMock(return_value=RangeNetworkConfig("cluster1", "10.200.0.0/24", "us-central1")),
        )
        monkeypatch.setattr("terraform_ops._update_range_config", MagicMock())
        monkeypatch.setattr(
            "terraform_ops._build_range_terraform_variables",
            MagicMock(return_value={"range_id": 42, "subnets": range_spec["subnets"]}),
        )
        monkeypatch.setattr(
            "terraform_ops.range_terraform_runner.apply_range",
            MagicMock(return_value=terraform_output),
        )
        monkeypatch.setattr("terraform_ops.run_instance_setup", mock_setup)
        monkeypatch.setattr("terraform_ops.write_provisioned_state", mock_write_state)
        monkeypatch.setattr(
            "terraform_ops.get_range_data_by_request_id",
            MagicMock(return_value={"ngfw_instance_id": None}),
        )
        monkeypatch.setattr("terraform_ops.publish_ready", MagicMock())
        with (
            patch.dict("os.environ", {"CLOUD_PROVIDER": "gcp"}, clear=True),
            patch("components.network.allocate_subnets", return_value=["10.200.0.96/28"]),
        ):
            _run_terraform_provision("req-123", 42, 7, range_spec)

        mock_setup.assert_called_once_with(instances_output=terraform_output["instances"], range_spec=range_spec)
        mock_write_state.assert_called_once_with(
            range_id=42,
            subnets=terraform_output["subnets"],
            instances=terraform_output["instances"],
            ngfw_instance_id=None,
        )

    def test_run_instance_setup_skips_pod_backed_assets(self, monkeypatch):
        from instance_orchestrator import run_instance_setup

        mock_dc_setup = MagicMock()
        mock_single_setup = MagicMock()
        monkeypatch.setattr("instance_orchestrator._run_dc_setup", mock_dc_setup)
        monkeypatch.setattr("instance_orchestrator._run_single_instance_setup", mock_single_setup)
        run_instance_setup(
            instances_output=[
                {
                    "uuid": "pod-uuid-1",
                    "asset_type": "scenario_pod",
                    "role": "victim",
                    "os": "ubuntu",
                    "instance_id": "range-42-mixed-victim-pod-uuid-1-pod",
                    "private_ip": "10.200.0.107",
                }
            ],
            range_spec={
                "subnets": [
                    {
                        "instances": [
                            {
                                "uuid": "pod-uuid-1",
                                "name": "lower-fidelity-target",
                                "asset_type": "scenario_pod",
                                "role": "victim",
                                "os_type": "ubuntu",
                            }
                        ]
                    }
                ]
            },
        )

        mock_dc_setup.assert_not_called()
        mock_single_setup.assert_not_called()

    def test_polaris_bootstrap_runs_before_container_password_push(self, monkeypatch):
        from instance_orchestrator import _setup_one_other_instance

        events = []

        def record_single_setup(*, instance_data, instance_id, spec):
            events.append(("setup", spec.set_local_password))
            assert instance_id == "i-polaris"
            assert instance_data["instance_id"] == "i-polaris"
            assert spec.set_local_password is False

        def record_bootstrap(*, instance_id, dc_ip, public_key):
            events.append(("bootstrap", dc_ip, public_key))

        def record_container_password(*, instance_data, instance_id, container_name, ssh_user):
            events.append(("password", container_name, ssh_user))

        monkeypatch.setattr("instance_orchestrator.get_agent_presigned_url", MagicMock(return_value=""))
        monkeypatch.setattr(
            "instance_orchestrator._run_single_instance_setup",
            MagicMock(side_effect=record_single_setup),
        )
        monkeypatch.setattr(
            "instance_orchestrator._run_polaris_range_bootstrap",
            MagicMock(side_effect=record_bootstrap),
        )
        monkeypatch.setattr(
            "instance_orchestrator._set_attacker_container_password_after_bootstrap",
            MagicMock(side_effect=record_container_password),
        )
        result = _setup_one_other_instance(
            {
                "uuid": "inst-polaris",
                "asset_type": "vm_runtime_vm",
                "role": "attacker",
                "os": "kali",
                "instance_id": "i-polaris",
                "hostname": "kali",
                "name": "kali",
                "public_key": "ssh-rsa AAAA",
            },
            {"inst-polaris": {"ami_key": "polaris-vm"}},
            actual_dc_ip="10.1.2.8",
            actual_domain="boreas.local",
            range_id=9,
        )

        assert result == ("i-polaris", True, None)
        assert events == [
            ("setup", False),
            ("bootstrap", "10.1.2.8", "ssh-rsa AAAA"),
            ("password", "a14-kali", "kali"),
        ]

    def test_build_range_terraform_variables_includes_gcp_ngfw_attachment(self):
        from terraform_vars import _build_range_terraform_variables

        # GCP path uses GDC VM Runtime + GCP Secret Manager and does not
        # consume SECRETS_KMS_KEY_ARN — verify by omitting it from the env.
        with pytest.MonkeyPatch.context() as mp:
            mp.setenv("CLOUD_PROVIDER", "gcp")
            mp.setenv("ENVIRONMENT", "gcp-dev")
            mp.setenv("RANGE_NETWORK_ID", "cluster1")
            mp.setenv("RANGE_NETWORK_CIDR", "10.200.0.0/24")
            mp.setenv("RANGE_NETWORK_REGION", "us-central1")
            mp.setattr(
                "terraform_vars.get_user_ngfw_data",
                MagicMock(
                    return_value={
                        "cloud_provider": "gcp",
                        "ngfw_request_id": "ngfw-req-1",
                        "management_ip": "10.200.0.10",
                        "ssh_key_secret_arn": "projects/test/secrets/ngfw-admin",
                        "route_next_hop_ip": "10.200.0.2",
                        "attachment_mode": "gdc-static-route",
                        "provider_metadata": {"gcp": {"namespace": "ngfw-user-1"}},
                    }
                ),
            )
            mp.setattr("terraform_vars.generate_presigned_url", MagicMock(return_value=""))
            mp.setattr("terraform_vars.get_range_availability_zone", MagicMock(return_value="us-central1-a"))
            mp.setattr("terraform_vars._get_kali_instance_type", MagicMock(return_value="n2-standard-2"))
            mp.setattr("terraform_vars._get_victim_instance_type", MagicMock(return_value="n2-standard-2"))
            mp.setattr("terraform_vars._get_windows_instance_type", MagicMock(return_value="n2-standard-4"))
            mp.setattr("terraform_vars._get_dc_instance_type", MagicMock(return_value="n2-standard-4"))

            variables = _build_range_terraform_variables(
                request_id="req-123",
                range_id=42,
                user_id=7,
                range_spec={
                    "ngfw": True,
                    "subnets": [
                        {
                            "name": "attack",
                            "uuid": "subnet-1",
                            "connected_to": [],
                            "instances": [
                                {
                                    "uuid": "inst-1",
                                    "name": "attacker",
                                    "role": "attacker",
                                    "os_type": "kali",
                                }
                            ],
                        }
                    ],
                },
            )

        assert variables["ngfw_data_eni_id"] == ""
        assert variables["ngfw_attachment"]["cloud_provider"] == "gcp"
        assert variables["ngfw_attachment"]["route_next_hop_ip"] == "10.200.0.2"
        # GCP path must NOT include the AWS-only Secrets Manager CMK ARN (#213).
        assert "secrets_kms_key_arn" not in variables

    def test_build_range_terraform_variables_aws_includes_secrets_kms_key_arn(self):
        """AWS range tfvars include the Secrets Manager CMK ARN (#213).

        Mirrors the NGFW positive coverage in test_terraform_runner.py: the
        runtime range Terraform module's `aws_secretsmanager_secret.ssh_key`
        resource depends on this variable.
        """
        from terraform_vars import _build_range_terraform_variables

        with pytest.MonkeyPatch.context() as mp:
            mp.setenv("CLOUD_PROVIDER", "aws")
            mp.setenv("ENVIRONMENT", "dev")
            mp.setenv("SECRETS_KMS_KEY_ARN", "arn:aws:kms:us-east-2:123456789012:key/abcd-1234")
            mp.setenv("RANGE_INSTANCE_PROFILE_NAME", "shifter-dev-range-profile")
            mp.setattr(
                "terraform_vars.load_range_network_config",
                MagicMock(
                    return_value=SimpleNamespace(
                        network_id="vpc-test",
                        network_cidr="10.1.0.0/16",
                        primary_portal_cidr="10.0.0.0/16",
                    )
                ),
            )
            mp.setattr("terraform_vars.get_range_availability_zone", MagicMock(return_value="us-east-2a"))
            mp.setattr("terraform_vars.get_ami_id", MagicMock(return_value="ami-deadbeef"))
            mp.setattr("terraform_vars.generate_presigned_url", MagicMock(return_value=""))

            variables = _build_range_terraform_variables(
                request_id="req-aws-1",
                range_id=1,
                user_id=2,
                range_spec={"ngfw": False, "subnets": []},
            )

        assert variables["secrets_kms_key_arn"] == "arn:aws:kms:us-east-2:123456789012:key/abcd-1234"
        assert variables["kali_ami_id"] == "ami-deadbeef"

    def test_build_range_terraform_variables_aws_raises_when_secrets_kms_key_arn_missing(self):
        """Fail-fast on missing SECRETS_KMS_KEY_ARN for AWS range path (#213)."""
        from terraform_vars import _build_range_terraform_variables

        with pytest.MonkeyPatch.context() as mp:
            mp.setenv("CLOUD_PROVIDER", "aws")
            mp.setenv("ENVIRONMENT", "dev")
            mp.setenv("RANGE_INSTANCE_PROFILE_NAME", "shifter-dev-range-profile")
            mp.delenv("SECRETS_KMS_KEY_ARN", raising=False)
            mp.setattr(
                "terraform_vars.load_range_network_config",
                MagicMock(
                    return_value=SimpleNamespace(
                        network_id="vpc-test",
                        network_cidr="10.1.0.0/16",
                        primary_portal_cidr="10.0.0.0/16",
                    )
                ),
            )
            mp.setattr("terraform_vars.get_range_availability_zone", MagicMock(return_value="us-east-2a"))
            mp.setattr("terraform_vars.get_ami_id", MagicMock(return_value="ami-deadbeef"))
            mp.setattr("terraform_vars.generate_presigned_url", MagicMock(return_value=""))

            with pytest.raises(KeyError, match="SECRETS_KMS_KEY_ARN"):
                _build_range_terraform_variables(
                    request_id="req-aws-2",
                    range_id=1,
                    user_id=2,
                    range_spec={"ngfw": False, "subnets": []},
                )

    def test_run_range_terraform_rejects_non_ready_gcp_ngfw(self, monkeypatch):
        from terraform_ops import run_range_terraform

        monkeypatch.setattr(
            "terraform_ops.get_range_data_by_request_id",
            MagicMock(return_value={"range_id": 42, "user_id": 7, "spec": {"ngfw": True}}),
        )
        monkeypatch.setattr(
            "terraform_ops.get_user_ngfw_data",
            MagicMock(
                return_value={
                    "cloud_provider": "gcp",
                    "management_ip": "10.200.0.10",
                    "status": "paused",
                    "ngfw_request_id": "ngfw-req-1",
                }
            ),
        )

        with pytest.raises(RuntimeError, match="already be in ready state"):
            run_range_terraform("up", "req-123")

    def test_record_and_remove_ngfw_range_attachment_updates_state(self, monkeypatch):
        from provisioner_db_ngfw import _record_ngfw_range_attachment, _remove_ngfw_range_attachment

        monkeypatch.setattr(
            "provisioner_db_ngfw.get_ngfw_data_by_request_id",
            MagicMock(
                side_effect=[
                    {"state": {"attached_ranges": [{"range_id": 10}]}},
                    {"state": {"attached_ranges": [{"range_id": 10}, {"range_id": 42}]}},
                ]
            ),
        )
        mock_update = MagicMock()
        monkeypatch.setattr("ngfw_runtime.update_instance_state", mock_update)

        attachment_record = {
            "range_id": 42,
            "request_id": "req-123",
            "cloud_provider": "gcp",
            "subnets": [{"name": "attack", "cidr": "10.200.0.96/28", "connected_to": []}],
        }

        _record_ngfw_range_attachment(
            ngfw_request_id="ngfw-req-1",
            ngfw_status="ready",
            attachment_record=attachment_record,
        )
        _remove_ngfw_range_attachment(
            ngfw_request_id="ngfw-req-1",
            ngfw_status="ready",
            range_id=42,
        )

        assert mock_update.call_args_list[0].args[:2] == ("ngfw-req-1", "ready")
        assert mock_update.call_args_list[0].kwargs["attached_ranges"] == [{"range_id": 10}, attachment_record]
        assert mock_update.call_args_list[1].kwargs["attached_ranges"] == [{"range_id": 10}]


class TestPollForSerialAndCert:
    """Tests for poll_for_serial_and_cert function."""

    def test_returns_serial_when_both_present(self, mocker):
        """Returns serial when both serial and cert are valid."""
        from ngfw_polling import poll_for_serial_and_cert

        mock_ssh = MagicMock()
        mock_ssh.run_command.return_value = MagicMock(stdout="serial: 007200001267\ndevice-certificate-status: Valid")

        serial = poll_for_serial_and_cert(
            ssh_executor=mock_ssh,
            host="10.1.4.10",
            timeout_seconds=60,
            poll_interval=5,
        )

        assert serial == "007200001267"

    def test_retries_until_both_present(self, mocker):
        """Retries when serial present but cert missing."""
        mocker.patch("time.sleep")
        from ngfw_polling import poll_for_serial_and_cert

        mock_ssh = MagicMock()
        mock_ssh.run_command.side_effect = [
            MagicMock(stdout="serial: 007200001267"),
            MagicMock(stdout="serial: 007200001267\ndevice-certificate-status: Valid"),
        ]

        serial = poll_for_serial_and_cert(
            ssh_executor=mock_ssh,
            host="10.1.4.10",
            timeout_seconds=600,
            poll_interval=30,
        )

        assert serial == "007200001267"
        assert mock_ssh.run_command.call_count == 2

    def test_raises_after_timeout(self, mocker):
        """Raises RuntimeError after timeout with details."""
        mocker.patch("time.sleep")
        from ngfw_polling import poll_for_serial_and_cert

        mock_ssh = MagicMock()
        mock_ssh.run_command.return_value = MagicMock(stdout="serial: unknown")

        with pytest.raises(RuntimeError, match="verification failed"):
            poll_for_serial_and_cert(
                ssh_executor=mock_ssh,
                host="10.1.4.10",
                timeout_seconds=0,
                poll_interval=30,
            )


class TestDcSetupRouting:
    """Tests for provider-aware DC setup behavior."""

    def test_should_promote_dc_at_runtime_defaults_by_provider(self):
        from state_helpers import _should_promote_dc_at_runtime

        with pytest.MonkeyPatch.context() as mp:
            mp.delenv("DC_RUNTIME_PROMOTION", raising=False)
            assert _should_promote_dc_at_runtime("aws") is False
            assert _should_promote_dc_at_runtime("gcp") is True

    def test_should_promote_dc_at_runtime_honors_override(self):
        from state_helpers import _should_promote_dc_at_runtime

        with pytest.MonkeyPatch.context() as mp:
            mp.setenv("DC_RUNTIME_PROMOTION", "false")
            assert _should_promote_dc_at_runtime("gcp") is False

        with pytest.MonkeyPatch.context() as mp:
            mp.setenv("DC_RUNTIME_PROMOTION", "true")
            assert _should_promote_dc_at_runtime("aws") is True

    def test_run_dc_setup_bootstraps_and_promotes_for_gcp(self, monkeypatch):
        from dc_setup import _run_dc_setup

        mock_execution = MagicMock()
        mock_execution.target = "10.50.1.10"
        mock_execution.document_name = "AWS-RunPowerShellScript"
        mock_execution.transport_name = "ssh"
        mock_execution.executor = MagicMock()
        mock_execution.executor.run_command.return_value = MagicMock(success=True, stderr="")

        mock_orchestrator = MagicMock()
        mock_orchestrator.orchestrate.return_value = MagicMock(success=True, error=None)

        mock_bootstrap_plan = MagicMock()
        mock_bootstrap_plan.get_context.return_value = {"hostname": "dc-01", "public_key": "ssh-rsa AAAA"}
        mock_dc_plan = MagicMock()
        mock_dc_plan.get_context.return_value = {
            "domain_name": "range.local",
            "netbios_name": "RANGE",
            "dsrm_password": "Secret123!",
            "domain_admin_password": "Secret123!",
        }

        build_context = MagicMock(return_value=mock_execution)
        bootstrap_plan_cls = MagicMock(return_value=mock_bootstrap_plan)
        dc_plan_cls = MagicMock(return_value=mock_dc_plan)
        monkeypatch.setattr("dc_setup.build_guest_execution_context", build_context)
        monkeypatch.setattr("dc_setup.SetupOrchestrator", MagicMock(return_value=mock_orchestrator))
        monkeypatch.setattr("dc_setup.BootstrapPlan", bootstrap_plan_cls)
        monkeypatch.setattr("dc_setup.DCSetupPlan", dc_plan_cls)
        monkeypatch.setattr("dc_setup._should_run_dc_bootstrap_plan", MagicMock(return_value=True))
        monkeypatch.setattr("dc_setup._should_promote_dc_at_runtime", MagicMock(return_value=True))
        monkeypatch.setenv("DC_DOMAIN_PASSWORD", "Secret123!")

        _run_dc_setup(
            instance_data={"hostname": "dc-01", "name": "dc-01", "public_key": "ssh-rsa AAAA"},
            instance_id="gcp-dc-01",
            dc_config={"domain_name": "range.local", "netbios_name": "RANGE"},
            agent_presigned_url="",
            public_key="ssh-rsa AAAA",
        )

        build_context.assert_called_once()
        bootstrap_plan_cls.assert_called_once_with()
        dc_plan_cls.assert_called_once_with(runtime_promotion=True)
        assert mock_orchestrator.orchestrate.call_count == 2
        mock_execution.close.assert_called_once_with()

    def test_run_dc_setup_keeps_prebaked_mode_for_aws(self, monkeypatch):
        from dc_setup import _run_dc_setup

        mock_execution = MagicMock()
        mock_execution.target = "i-1234567890"
        mock_execution.document_name = "AWS-RunPowerShellScript"
        mock_execution.transport_name = "ssm"
        mock_execution.executor = MagicMock()
        mock_execution.executor.run_command.return_value = MagicMock(success=True, stderr="")

        mock_orchestrator = MagicMock()
        mock_orchestrator.orchestrate.return_value = MagicMock(success=True, error=None)

        mock_dc_plan = MagicMock()
        mock_dc_plan.get_context.return_value = {
            "domain_name": "range.local",
            "netbios_name": "RANGE",
            "dsrm_password": "Secret123!",
            "domain_admin_password": "Secret123!",
        }

        bootstrap_plan_cls = MagicMock()
        dc_plan_cls = MagicMock(return_value=mock_dc_plan)
        monkeypatch.setattr("dc_setup.build_guest_execution_context", MagicMock(return_value=mock_execution))
        monkeypatch.setattr("dc_setup.SetupOrchestrator", MagicMock(return_value=mock_orchestrator))
        monkeypatch.setattr("dc_setup.BootstrapPlan", bootstrap_plan_cls)
        monkeypatch.setattr("dc_setup.DCSetupPlan", dc_plan_cls)
        monkeypatch.setattr("dc_setup._should_run_dc_bootstrap_plan", MagicMock(return_value=False))
        monkeypatch.setattr("dc_setup._should_promote_dc_at_runtime", MagicMock(return_value=False))
        monkeypatch.setenv("DC_DOMAIN_PASSWORD", "Secret123!")

        _run_dc_setup(
            instance_data={"hostname": "dc-01", "name": "dc-01", "public_key": "ssh-rsa AAAA"},
            instance_id="i-1234567890",
            dc_config={"domain_name": "range.local", "netbios_name": "RANGE"},
            agent_presigned_url="",
            public_key="ssh-rsa AAAA",
        )

        bootstrap_plan_cls.assert_not_called()
        dc_plan_cls.assert_called_once_with(runtime_promotion=False)
        assert mock_orchestrator.orchestrate.call_count == 1
        mock_execution.close.assert_called_once_with()


class TestNgfwRuntimeOperations:
    """Tests for provider-aware NGFW runtime ops."""

    def test_run_ngfw_operation_runs_gdc_vmseries_power_operation(self, monkeypatch):
        from ngfw_runtime_ops import run_ngfw_operation

        state = {
            "cloud_provider": "gcp",
            "management_ip": "10.200.0.10",
            "ssh_key_secret_id": "projects/test/secrets/ngfw-admin",
            "route_next_hop_ip": "10.200.0.2",
            "provider_metadata": {
                "gcp": {
                    "namespace": "ngfw-user-42",
                    "vm_name": "ngfw-user-42-abcdef",
                }
            },
        }
        monkeypatch.setattr(
            "ngfw_runtime_ops.get_ngfw_data_by_request_id",
            MagicMock(
                return_value={
                    "instance_id": "ngfw-inst-1",
                    "app_id": "ngfw-app-1",
                    "state": state,
                }
            ),
        )
        mock_update = MagicMock()
        mock_publish = MagicMock()
        mock_power = MagicMock()
        monkeypatch.setattr("ngfw_runtime_ops.update_instance_state", mock_update)
        monkeypatch.setattr("ngfw_runtime_ops.publish_ngfw_event", mock_publish)
        monkeypatch.setattr("gdc_vmseries_ngfw.run_power_operation", mock_power)

        run_ngfw_operation("start", "ngfw-req-1")

        mock_power.assert_called_once_with("start", state)
        assert mock_update.call_args_list[0].args[:2] == ("ngfw-req-1", "resuming")
        assert mock_update.call_args_list[1].args[:2] == ("ngfw-req-1", "ready")
        assert [call.kwargs["status"] for call in mock_publish.call_args_list] == ["resuming", "ready"]
