"""Tests for main.py parsing and utility functions.

Only tests for pure logic - no mock-heavy integration tests.
"""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestParseSerialNumber:
    """Tests for parse_serial_number helper function."""

    def test_extracts_serial_from_system_info(self):
        """Extracts serial from PAN-OS show system info output."""
        from main import parse_serial_number

        system_info = """hostname: PA-VM
serial: 007200001267
software-version: 11.1.0
"""
        assert parse_serial_number(system_info) == "007200001267"

    def test_extracts_serial_case_insensitive(self):
        """Handles case variations."""
        from main import parse_serial_number

        assert parse_serial_number("SERIAL: ABC123DEF456") == "ABC123DEF456"

    def test_extracts_serial_with_extra_whitespace(self):
        """Handles extra whitespace."""
        from main import parse_serial_number

        result = parse_serial_number("serial:   007200001267   ")
        assert result == "007200001267"

    def test_returns_none_when_not_found(self):
        """Returns None when serial not in output."""
        from main import parse_serial_number

        result = parse_serial_number("hostname: PA-VM\nsoftware-version: 11.1.0")
        assert result is None

    def test_returns_none_for_unknown_placeholder(self):
        """Returns None for 'unknown' placeholder."""
        from main import parse_serial_number

        assert parse_serial_number("serial: unknown") is None

    def test_returns_none_for_none_placeholder(self):
        """Returns None for 'none' placeholder."""
        from main import parse_serial_number

        assert parse_serial_number("serial: none") is None

    def test_returns_none_for_empty_output(self):
        """Returns None for empty output."""
        from main import parse_serial_number

        assert parse_serial_number("") is None


class TestParseDeviceCertificateStatus:
    """Tests for parse_device_certificate_status helper function."""

    def test_extracts_valid_cert_status(self):
        """Extracts 'Valid' certificate status."""
        from main import parse_device_certificate_status

        system_info = "device-certificate-status: Valid"
        assert parse_device_certificate_status(system_info) == "Valid"

    def test_extracts_cert_status_case_insensitive(self):
        """Handles case variations in field name."""
        from main import parse_device_certificate_status

        result = parse_device_certificate_status("DEVICE-CERTIFICATE-STATUS: Valid")
        assert result == "Valid"

    def test_returns_none_when_not_found(self):
        """Returns None when cert status not in output."""
        from main import parse_device_certificate_status

        assert parse_device_certificate_status("serial: 12345") is None

    def test_returns_none_for_empty_output(self):
        """Returns None for empty output."""
        from main import parse_device_certificate_status

        assert parse_device_certificate_status("") is None


class TestRangeStatePayloads:
    """Tests for provider-aware range state serialization helpers."""

    def test_build_subnet_state_preserves_aws_fields(self):
        from main import _build_subnet_state

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

    def test_build_subnet_state_persists_gcp_metadata_without_aws_aliases(self):
        from main import _build_subnet_state

        subnet_state = _build_subnet_state(
            {
                "subnet_id": "projects/test/regions/us-central1/subnetworks/range-1",
                "subnet_cidr": "10.50.1.0/28",
                "security_group_id": "shifter-target-tag",
                "route_table_id": "",
                "gcp_subnetwork_name": "range-1",
                "gcp_subnetwork_id": "1234567890",
                "gcp_subnetwork_self_link": "projects/test/regions/us-central1/subnetworks/range-1",
                "gcp_target_tag": "shifter-target-tag",
            },
            provider="gcp",
        )

        assert subnet_state["cloud_provider"] == "gcp"
        assert subnet_state["subnet_id"] == "projects/test/regions/us-central1/subnetworks/range-1"
        assert subnet_state["aws_subnet_id"] is None
        assert subnet_state["provider_metadata"] == {
            "gcp": {
                "subnetwork_name": "range-1",
                "subnetwork_id": "1234567890",
                "subnetwork_self_link": "projects/test/regions/us-central1/subnetworks/range-1",
                "target_tag": "shifter-target-tag",
            }
        }

    def test_build_instance_state_preserves_aws_instance_alias(self):
        from main import _build_instance_state

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

    def test_build_instance_state_collects_gcp_metadata(self):
        from main import _build_instance_state

        instance_state = _build_instance_state(
            {
                "instance_id": "shifter-range-vm-1",
                "private_ip": "10.50.1.10",
                "ssh_key_secret_arn": "projects/test/secrets/range-ssh-key",
                "ssh_username": "ubuntu",
                "subnet_name": "attack",
                "gcp_instance_name": "shifter-range-vm-1",
                "gcp_instance_id": "9988776655",
                "gcp_instance_self_link": "projects/test/zones/us-central1-b/instances/shifter-range-vm-1",
                "gcp_private_ip": "10.50.1.10",
                "gcp_ssh_key_secret_id": "projects/test/secrets/range-ssh-key",
                "gcp_ssh_username": "ubuntu",
                "gcp_zone": "us-central1-b",
                "gcp_subnetwork": "projects/test/regions/us-central1/subnetworks/range-1",
            },
            provider="gcp",
        )

        assert instance_state["cloud_provider"] == "gcp"
        assert instance_state["aws_instance_id"] is None
        assert instance_state["ssh_username"] == "ubuntu"
        assert instance_state["provider_metadata"] == {
            "gcp": {
                "instance_name": "shifter-range-vm-1",
                "instance_id": "9988776655",
                "instance_self_link": "projects/test/zones/us-central1-b/instances/shifter-range-vm-1",
                "private_ip": "10.50.1.10",
                "ssh_key_secret_id": "projects/test/secrets/range-ssh-key",
                "ssh_username": "ubuntu",
                "zone": "us-central1-b",
                "subnetwork": "projects/test/regions/us-central1/subnetworks/range-1",
            }
        }

    def test_build_instance_state_collects_gdc_alias_metadata_under_gcp_provider(self):
        from main import _build_instance_state

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

    def test_build_provisioned_instance_payload_keeps_legacy_fields_and_adds_provider_metadata(self):
        from main import _build_provisioned_instance_payload

        payload = _build_provisioned_instance_payload(
            {
                "uuid": "inst-123",
                "name": "workstation-1",
                "role": "victim",
                "os": "windows",
                "subnet_name": "victims",
                "instance_id": "shifter-range-vm-1",
                "private_ip": "10.50.1.10",
                "ssh_key_secret_arn": "projects/test/secrets/range-ssh-key",
                "ssh_username": "Administrator",
                "gcp_instance_id": "9988776655",
            },
            provider="gcp",
        )

        assert payload["uuid"] == "inst-123"
        assert payload["os_type"] == "windows"
        assert payload["instance_id"] == "shifter-range-vm-1"
        assert payload["ssh_key_secret_arn"] == "projects/test/secrets/range-ssh-key"
        assert payload["ssh_username"] == "Administrator"
        assert payload["cloud_provider"] == "gcp"
        assert payload["provider_metadata"] == {"gcp": {"instance_id": "9988776655"}}

    def test_get_cloud_provider_defaults_to_aws(self):
        from main import _get_cloud_provider

        with pytest.MonkeyPatch.context() as mp:
            mp.delenv("CLOUD_PROVIDER", raising=False)
            assert _get_cloud_provider() == "aws"

    def test_get_cloud_provider_reads_env(self):
        from main import _get_cloud_provider

        with pytest.MonkeyPatch.context() as mp:
            mp.setenv("CLOUD_PROVIDER", "gcp")
            assert _get_cloud_provider() == "gcp"

    def test_write_provisioned_state_persists_gcp_metadata_blocks(self):
        from main import write_provisioned_state

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
                "subnet_id": "projects/test/regions/us-central1/subnetworks/range-1",
                "subnet_cidr": "10.50.1.0/28",
                "security_group_id": "shifter-target-tag",
                "route_table_id": "",
                "gcp_subnetwork_name": "range-1",
                "gcp_subnetwork_id": "1234567890",
                "gcp_subnetwork_self_link": "projects/test/regions/us-central1/subnetworks/range-1",
                "gcp_target_tag": "shifter-target-tag",
            }
        }
        instances = [
            {
                "uuid": "inst-123",
                "name": "workstation-1",
                "role": "victim",
                "os": "windows",
                "subnet_name": "attack",
                "instance_id": "shifter-range-vm-1",
                "private_ip": "10.50.1.10",
                "ssh_key_secret_arn": "projects/test/secrets/range-ssh-key",
                "gcp_instance_name": "shifter-range-vm-1",
                "gcp_instance_id": "9988776655",
                "gcp_instance_self_link": "projects/test/zones/us-central1-b/instances/shifter-range-vm-1",
                "gcp_zone": "us-central1-b",
                "gcp_subnetwork": "projects/test/regions/us-central1/subnetworks/range-1",
            }
        ]

        with (
            patch.dict("os.environ", {"CLOUD_PROVIDER": "gcp"}, clear=True),
            patch("main.get_db_connection", return_value=mock_conn),
        ):
            write_provisioned_state(range_id=42, subnets=subnets, instances=instances, ngfw_instance_id=None)

        subnet_state = json.loads(mock_cursor.execute.call_args_list[0].args[1][0])
        instance_state = json.loads(mock_cursor.execute.call_args_list[1].args[1][0])
        provisioned_instances = json.loads(mock_cursor.execute.call_args_list[2].args[1][0])

        assert subnet_state["cloud_provider"] == "gcp"
        assert subnet_state["aws_subnet_id"] is None
        assert subnet_state["provider_metadata"]["gcp"]["subnetwork_id"] == "1234567890"
        assert instance_state["cloud_provider"] == "gcp"
        assert instance_state["aws_instance_id"] is None
        assert instance_state["provider_metadata"]["gcp"]["zone"] == "us-central1-b"
        assert provisioned_instances[0]["cloud_provider"] == "gcp"
        assert provisioned_instances[0]["instance_id"] == "shifter-range-vm-1"
        assert provisioned_instances[0]["provider_metadata"]["gcp"]["instance_id"] == "9988776655"


class TestPollForSerialAndCert:
    """Tests for poll_for_serial_and_cert function."""

    def test_returns_serial_when_both_present(self, mocker):
        """Returns serial when both serial and cert are valid."""
        from main import poll_for_serial_and_cert

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
        from main import poll_for_serial_and_cert

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
        from main import poll_for_serial_and_cert

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
        from main import _should_promote_dc_at_runtime

        with pytest.MonkeyPatch.context() as mp:
            mp.delenv("DC_RUNTIME_PROMOTION", raising=False)
            assert _should_promote_dc_at_runtime("aws") is False
            assert _should_promote_dc_at_runtime("gcp") is True

    def test_should_promote_dc_at_runtime_honors_override(self):
        from main import _should_promote_dc_at_runtime

        with pytest.MonkeyPatch.context() as mp:
            mp.setenv("DC_RUNTIME_PROMOTION", "false")
            assert _should_promote_dc_at_runtime("gcp") is False

        with pytest.MonkeyPatch.context() as mp:
            mp.setenv("DC_RUNTIME_PROMOTION", "true")
            assert _should_promote_dc_at_runtime("aws") is True

    def test_run_dc_setup_bootstraps_and_promotes_for_gcp(self, mocker):
        from main import _run_dc_setup

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

        build_context = mocker.patch("main.build_guest_execution_context", return_value=mock_execution)
        mocker.patch("main.SetupOrchestrator", return_value=mock_orchestrator)
        bootstrap_plan_cls = mocker.patch("main.BootstrapPlan", return_value=mock_bootstrap_plan)
        dc_plan_cls = mocker.patch("main.DCSetupPlan", return_value=mock_dc_plan)
        mocker.patch("main._should_run_dc_bootstrap_plan", return_value=True)
        mocker.patch("main._should_promote_dc_at_runtime", return_value=True)
        mocker.patch.dict("os.environ", {"DC_DOMAIN_PASSWORD": "Secret123!"}, clear=False)

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

    def test_run_dc_setup_keeps_prebaked_mode_for_aws(self, mocker):
        from main import _run_dc_setup

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

        mocker.patch("main.build_guest_execution_context", return_value=mock_execution)
        mocker.patch("main.SetupOrchestrator", return_value=mock_orchestrator)
        bootstrap_plan_cls = mocker.patch("main.BootstrapPlan")
        dc_plan_cls = mocker.patch("main.DCSetupPlan", return_value=mock_dc_plan)
        mocker.patch("main._should_run_dc_bootstrap_plan", return_value=False)
        mocker.patch("main._should_promote_dc_at_runtime", return_value=False)
        mocker.patch.dict("os.environ", {"DC_DOMAIN_PASSWORD": "Secret123!"}, clear=False)

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
