"""Tests for terraform_runner module.

Covers destroy_ngfw variable passing and _build_tf_variables helper.
"""

from pathlib import Path
from unittest.mock import MagicMock, mock_open, patch

import pytest


class TestDestroyNgfw:
    """Test destroy_ngfw passes variables correctly."""

    @patch("terraform_base.run_terraform")
    @patch("terraform_base.init_workspace")
    def test_destroy_with_variables_writes_tfvars(self, mock_init, mock_run, tmp_path):
        """When variables are provided, destroy should write tfvars and pass -var-file."""
        from terraform_runner import destroy_ngfw

        working_dir = tmp_path / "test-module"
        working_dir.mkdir()
        variables = {"name_prefix": "ngfw-user-1", "user_id": 1}

        with patch("builtins.open", mock_open()) as mocked_file, patch.object(Path, "unlink"):
            destroy_ngfw("req-123", working_dir, variables=variables)

        # Verify tfvars file was written
        mocked_file.assert_called_once_with(working_dir / "terraform.tfvars.json", "w")
        written_data = mocked_file().write.call_args_list
        # json.dump writes in chunks; just verify it was called
        assert len(written_data) > 0

        # Verify -var-file was passed to terraform
        destroy_args = mock_run.call_args[0][0]
        assert any("-var-file=" in arg for arg in destroy_args)

    @patch("terraform_base.run_terraform")
    @patch("terraform_base.init_workspace")
    def test_destroy_without_variables_no_var_file(self, mock_init, mock_run, tmp_path):
        """When no variables provided, destroy should not pass -var-file."""
        from terraform_runner import destroy_ngfw

        working_dir = tmp_path / "test-module"
        working_dir.mkdir()

        destroy_ngfw("req-123", working_dir)

        destroy_args = mock_run.call_args[0][0]
        assert not any("-var-file=" in arg for arg in destroy_args)
        assert "-auto-approve" in destroy_args

    @patch("terraform_base.run_terraform", side_effect=RuntimeError("destroy failed"))
    @patch("terraform_base.init_workspace")
    def test_destroy_cleans_up_tfvars_on_failure(self, mock_init, mock_run, tmp_path):
        """Tfvars file should be cleaned up even if destroy fails."""
        from terraform_runner import destroy_ngfw

        working_dir = tmp_path / "test-module"
        working_dir.mkdir()
        variables = {"name_prefix": "ngfw-user-1"}
        mock_unlink = MagicMock()

        with (
            patch("builtins.open", mock_open()),
            patch.object(Path, "unlink", mock_unlink),
            pytest.raises(RuntimeError, match="destroy failed"),
        ):
            destroy_ngfw("req-123", working_dir, variables=variables)

        mock_unlink.assert_called_once_with(missing_ok=True)


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
