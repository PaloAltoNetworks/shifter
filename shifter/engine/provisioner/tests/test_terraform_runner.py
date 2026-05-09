"""Tests for terraform_runner module.

Covers destroy_ngfw variable passing and _build_tf_variables helper.
"""

import os
from unittest.mock import patch

import pytest


class TestDestroyNgfw:
    """Test destroy_ngfw passes variables correctly.

    Issue #1103: destroy() stages a writable workspace under TERRAFORM_WORKSPACE_DIR,
    runs terraform from the staged path, and cleans the staged tree up on success and
    failure. NGFW Terraform shares the same image as range Terraform — the staging
    contract MUST cover both paths or NGFW provision/deprovision breaks under
    readOnlyRootFilesystem.
    """

    @patch.dict(os.environ, {"TF_STATE_BUCKET": "shifter-dev-pulumi-state"}, clear=True)
    @patch("terraform_base.run_terraform")
    def test_destroy_with_variables_writes_tfvars(self, mock_run, tmp_path, monkeypatch):
        """When variables are provided, destroy should write tfvars and pass -var-file."""
        from terraform_runner import destroy_ngfw

        source = tmp_path / "src" / "modules" / "ngfw"
        source.mkdir(parents=True)
        (source / "main.tf").write_text("# main\n")
        workspace_root = tmp_path / "workspace"
        monkeypatch.setenv("TERRAFORM_WORKSPACE_DIR", str(workspace_root))
        monkeypatch.setenv("TF_STATE_BUCKET", "shifter-dev-pulumi-state")

        variables = {"name_prefix": "ngfw-user-1", "user_id": 1}
        destroy_ngfw("req-123", source, variables=variables)

        destroy_args = mock_run.call_args[0][0]
        assert any("-var-file=" in arg for arg in destroy_args)
        assert not (workspace_root / "req-123").exists()

    @patch.dict(os.environ, {"TF_STATE_BUCKET": "shifter-dev-pulumi-state"}, clear=True)
    @patch("terraform_base.run_terraform")
    def test_destroy_without_variables_no_var_file(self, mock_run, tmp_path, monkeypatch):
        """When no variables provided, destroy should not pass -var-file."""
        from terraform_runner import destroy_ngfw

        source = tmp_path / "src" / "modules" / "ngfw"
        source.mkdir(parents=True)
        (source / "main.tf").write_text("# main\n")
        workspace_root = tmp_path / "workspace"
        monkeypatch.setenv("TERRAFORM_WORKSPACE_DIR", str(workspace_root))
        monkeypatch.setenv("TF_STATE_BUCKET", "shifter-dev-pulumi-state")

        destroy_ngfw("req-123", source)

        destroy_args = mock_run.call_args[0][0]
        assert not any("-var-file=" in arg for arg in destroy_args)
        assert "-auto-approve" in destroy_args
        assert not (workspace_root / "req-123").exists()

    @patch.dict(os.environ, {"TF_STATE_BUCKET": "shifter-dev-pulumi-state"}, clear=True)
    def test_destroy_cleans_up_workspace_on_failure(self, tmp_path, monkeypatch):
        """Staged workspace must be removed even when terraform destroy fails."""
        from terraform_runner import destroy_ngfw

        source = tmp_path / "src" / "modules" / "ngfw"
        source.mkdir(parents=True)
        (source / "main.tf").write_text("# main\n")
        workspace_root = tmp_path / "workspace"
        monkeypatch.setenv("TERRAFORM_WORKSPACE_DIR", str(workspace_root))
        monkeypatch.setenv("TF_STATE_BUCKET", "shifter-dev-pulumi-state")

        with (
            patch("terraform_base.run_terraform", side_effect=RuntimeError("destroy failed")),
            pytest.raises(RuntimeError, match="destroy failed"),
        ):
            destroy_ngfw("req-123", source, variables={"name_prefix": "ngfw-user-1"})

        assert not (workspace_root / "req-123").exists()


class TestBuildTfVariables:
    """Test _build_tf_variables helper."""

    @patch.dict(
        "os.environ",
        {
            "ENVIRONMENT": "prod",
            "NGFW_SUBNET_ID": "subnet-abc",
            "NGFW_MGMT_SECURITY_GROUP_ID": "sg-mgmt",
            "NGFW_DATA_SECURITY_GROUP_ID": "sg-data",
            "NGFW_AMI_ID": "ami-123",
            "NGFW_BOOTSTRAP_BUCKET": "my-bucket",
            "NGFW_INSTANCE_TYPE": "m5.2xlarge",
            "NGFW_INSTANCE_PROFILE_NAME": "my-profile",
        },
        clear=False,
    )
    def test_builds_variables_from_env_and_app_spec(self):
        """Should combine env vars and app_spec into tf_variables dict."""
        from ngfw_terraform import _build_tf_variables

        app_spec = {
            "user_id": 42,
            "scm_pin_id": "pin-1",
            "scm_pin_value": "val-1",
            "scm_folder_name": "folder-1",
            "authcode": "auth-abc",
        }

        result = _build_tf_variables("req-999", "inst-555", app_spec)

        assert result["name_prefix"] == "ngfw-user-42"
        assert result["user_id"] == 42
        assert result["instance_uuid"] == "inst-555"
        assert result["request_uuid"] == "req-999"
        assert result["environment"] == "prod"
        assert result["subnet_id"] == "subnet-abc"
        assert result["ami_id"] == "ami-123"
        assert result["instance_profile_name"] == "my-profile"
        assert result["scm_pin_id"] == "pin-1"
        assert result["authcode"] == "auth-abc"

    @patch.dict("os.environ", {}, clear=True)
    def test_defaults_when_env_vars_missing(self):
        """Should use defaults when env vars are not set."""
        from ngfw_terraform import _build_tf_variables

        result = _build_tf_variables("req-1", "inst-1", {})

        assert result["user_id"] == 0
        assert result["name_prefix"] == "ngfw-user-0"
        assert result["environment"] == "dev"
        assert result["subnet_id"] == ""
        assert result["instance_type"] == "m5.xlarge"
        assert result["instance_profile_name"] is None


class TestBuildProviderState:
    """Test provider-neutral NGFW state payload generation."""

    @patch.dict("os.environ", {"CLOUD_PROVIDER": "aws"}, clear=False)
    def test_builds_provider_neutral_state_for_aws_ngfw(self):
        """AWS NGFW outputs should expose attachment metadata for later range binding."""
        from ngfw_terraform import _build_provider_state

        state = _build_provider_state(
            {
                "management_ip": "10.1.5.10",
                "dataplane_ip": "10.1.4.10",
                "data_eni_id": "eni-123",
                "ssh_key_secret_arn": "arn:aws:secretsmanager:us-east-2:123:secret:key",
            }
        )

        assert state["cloud_provider"] == "aws"
        assert state["route_next_hop_ip"] == "10.1.4.10"
        assert state["data_attachment_id"] == "eni-123"
        assert state["attached_ranges"] == []
        assert state["provider_metadata"]["aws"]["attachment_mode"] == "aws-route-table-eni"

    @patch.dict("os.environ", {"CLOUD_PROVIDER": "gcp"}, clear=False)
    def test_builds_provider_neutral_state_for_gdc_vmseries_ngfw(self):
        """GDC Palo Alto VM-Series outputs should expose the VM Runtime attachment contract."""
        from ngfw_terraform import _build_provider_state

        state = _build_provider_state(
            {
                "cloud_provider": "gcp",
                "route_next_hop_ip": "10.200.1.1",
                "attachment_mode": "gdc-vmruntime-palo-alto-vmseries",
                "data_attachment_id": "ngfw-user-42/vmseries:eth1",
                "provider_metadata": {
                    "gcp": {
                        "product": "palo-alto-vm-series",
                        "namespace": "ngfw-user-42",
                        "vm_name": "vmseries",
                    }
                },
            }
        )

        assert state["cloud_provider"] == "gcp"
        assert state["route_next_hop_ip"] == "10.200.1.1"
        assert state["attachment_mode"] == "gdc-vmruntime-palo-alto-vmseries"
        assert state["data_attachment_id"] == "ngfw-user-42/vmseries:eth1"
        assert state["attached_ranges"] == []
        assert state["provider_metadata"]["gcp"]["product"] == "palo-alto-vm-series"
