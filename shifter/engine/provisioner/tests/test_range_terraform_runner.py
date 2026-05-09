"""Tests for range_terraform_runner module.

Covers destroy_range variable passing (mirrors test_terraform_runner.py for NGFW).
"""

import os
from unittest.mock import patch

import pytest


class TestProviderRouting:
    """Test provider-routed module and state prefix selection."""

    def test_get_range_module_path_defaults_to_aws(self):
        from range_terraform_runner import AWS_RANGE_MODULE_PATH, get_range_module_path

        with patch.dict(os.environ, {}, clear=True):
            assert get_range_module_path() == AWS_RANGE_MODULE_PATH

    def test_get_range_module_path_fails_fast_for_gcp(self):
        from range_terraform_runner import get_range_module_path

        with (
            patch.dict(os.environ, {"CLOUD_PROVIDER": "gcp"}, clear=True),
            pytest.raises(RuntimeError, match="does not expose a Terraform module path"),
        ):
            get_range_module_path()

    @patch(
        "range_terraform_runner.gdc_vmruntime_assets.apply_range_assets",
        return_value=[{"instance_id": "range-42-attack-attacker-1234"}],
    )
    @patch(
        "range_terraform_runner.gdc_scenario_pods.apply_range_assets",
        return_value=[{"instance_id": "range-42-attack-victim-5678-pod"}],
    )
    @patch(
        "range_terraform_runner.gdc_range_networks.apply_range_networks",
        return_value={"subnets": {"attack": {"subnet_id": "range-42-attack"}}, "instances": []},
    )
    def test_apply_range_dispatches_to_gdc_network_and_asset_runners(
        self,
        mock_network_apply,
        mock_pod_apply,
        mock_vm_apply,
    ):
        from range_terraform_runner import apply_range

        with patch.dict(os.environ, {"CLOUD_PROVIDER": "gcp"}, clear=True):
            result = apply_range("req-123", {"range_id": 42, "subnets": []})

        assert result == {
            "subnets": {"attack": {"subnet_id": "range-42-attack"}},
            "instances": [
                {"instance_id": "range-42-attack-attacker-1234"},
                {"instance_id": "range-42-attack-victim-5678-pod"},
            ],
        }
        mock_network_apply.assert_called_once_with("req-123", {"range_id": 42, "subnets": []})
        mock_vm_apply.assert_called_once_with(
            "req-123",
            {"range_id": 42, "subnets": []},
            {"attack": {"subnet_id": "range-42-attack"}},
        )
        mock_pod_apply.assert_called_once_with(
            "req-123",
            {"range_id": 42, "subnets": []},
            {"attack": {"subnet_id": "range-42-attack"}},
        )

    @patch("range_terraform_runner.gdc_range_networks.destroy_range_networks")
    @patch("range_terraform_runner.gdc_vmruntime_assets.destroy_range_assets")
    @patch("range_terraform_runner.gdc_scenario_pods.destroy_range_assets")
    def test_destroy_range_dispatches_to_gdc_asset_then_network_runner(
        self,
        mock_pod_destroy,
        mock_asset_destroy,
        mock_network_destroy,
    ):
        from range_terraform_runner import destroy_range

        with patch.dict(os.environ, {"CLOUD_PROVIDER": "gcp"}, clear=True):
            destroy_range("req-123", variables={"range_id": 42, "subnets": []})

        mock_pod_destroy.assert_called_once_with("req-123", {"range_id": 42, "subnets": []})
        mock_asset_destroy.assert_called_once_with("req-123", {"range_id": 42, "subnets": []})
        mock_network_destroy.assert_called_once_with("req-123", {"range_id": 42, "subnets": []})

    def test_get_range_state_key_prefix_uses_provider_specific_paths(self):
        from range_terraform_runner import get_range_state_key_prefix

        with patch.dict(os.environ, {}, clear=True):
            assert get_range_state_key_prefix() == "ranges"

        with patch.dict(os.environ, {"CLOUD_PROVIDER": "gcp"}, clear=True):
            assert get_range_state_key_prefix() == "gcp/gdc-ranges"


class TestDestroyRange:
    """Test destroy_range passes variables correctly.

    Issue #1103: destroy() stages a writable workspace under TERRAFORM_WORKSPACE_DIR,
    runs terraform from the staged path, and cleans the staged tree up on success and
    failure. These tests cover the public destroy_range contract: var-file is passed
    iff variables are supplied, and the staged workspace is removed when the call
    returns.
    """

    @patch.dict(os.environ, {"TF_STATE_BUCKET": "shifter-dev-pulumi-state"}, clear=True)
    @patch("terraform_base.run_terraform")
    def test_destroy_with_variables_writes_tfvars(self, mock_run, tmp_path, monkeypatch):
        """When variables are provided, destroy should write tfvars and pass -var-file."""
        from range_terraform_runner import destroy_range

        source = tmp_path / "src" / "modules" / "range"
        source.mkdir(parents=True)
        (source / "main.tf").write_text("# main\n")
        workspace_root = tmp_path / "workspace"
        monkeypatch.setenv("TERRAFORM_WORKSPACE_DIR", str(workspace_root))
        monkeypatch.setenv("TF_STATE_BUCKET", "shifter-dev-pulumi-state")

        variables = {"range_id": 42, "user_id": 1, "request_uuid": "req-123"}
        destroy_range("req-123", source, variables=variables)

        # Last call to run_terraform was the destroy command; assert -var-file present.
        destroy_args = mock_run.call_args[0][0]
        assert any("-var-file=" in arg for arg in destroy_args)
        # The staged workspace must be cleaned up.
        assert not (workspace_root / "req-123").exists()

    @patch.dict(os.environ, {"TF_STATE_BUCKET": "shifter-dev-pulumi-state"}, clear=True)
    @patch("terraform_base.run_terraform")
    def test_destroy_without_variables_no_var_file(self, mock_run, tmp_path, monkeypatch):
        """When no variables provided, destroy should not pass -var-file."""
        from range_terraform_runner import destroy_range

        source = tmp_path / "src" / "modules" / "range"
        source.mkdir(parents=True)
        (source / "main.tf").write_text("# main\n")
        workspace_root = tmp_path / "workspace"
        monkeypatch.setenv("TERRAFORM_WORKSPACE_DIR", str(workspace_root))
        monkeypatch.setenv("TF_STATE_BUCKET", "shifter-dev-pulumi-state")

        destroy_range("req-123", source)

        destroy_args = mock_run.call_args[0][0]
        assert not any("-var-file=" in arg for arg in destroy_args)
        assert "-auto-approve" in destroy_args
        assert not (workspace_root / "req-123").exists()

    @patch.dict(os.environ, {"TF_STATE_BUCKET": "shifter-dev-pulumi-state"}, clear=True)
    def test_destroy_cleans_up_workspace_on_failure(self, tmp_path, monkeypatch):
        """Staged workspace must be removed even when terraform destroy fails — otherwise
        terraform.tfvars.json (which can carry secrets) would persist on the volume."""
        from range_terraform_runner import destroy_range

        source = tmp_path / "src" / "modules" / "range"
        source.mkdir(parents=True)
        (source / "main.tf").write_text("# main\n")
        workspace_root = tmp_path / "workspace"
        monkeypatch.setenv("TERRAFORM_WORKSPACE_DIR", str(workspace_root))
        monkeypatch.setenv("TF_STATE_BUCKET", "shifter-dev-pulumi-state")

        with (
            patch("terraform_base.run_terraform", side_effect=RuntimeError("destroy failed")),
            pytest.raises(RuntimeError, match="destroy failed"),
        ):
            destroy_range("req-123", source, variables={"range_id": 42})

        assert not (workspace_root / "req-123").exists()
