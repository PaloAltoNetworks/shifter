"""Tests for range_terraform_runner module.

Covers destroy_range variable passing (mirrors test_terraform_runner.py for NGFW).
"""

import os
from unittest.mock import Mock, call, patch

import pytest


def _range_cell_variables():
    from shared.range_cells import build_gcp_vm_range_cell_request, build_scenario_artifact

    artifact = build_scenario_artifact(
        {
            "spec_schema": "range_spec",
            "spec_version": "1",
            "payload": {"scenario_id": "scenario-a", "user_id": 7, "subnets": []},
        }
    )
    return build_gcp_vm_range_cell_request(
        request_id="req-123",
        range_id=42,
        scenario_artifact=artifact,
        network_bindings=[],
    )


class TestProviderRouting:
    """Test provider-routed module and state prefix selection."""

    def test_get_range_module_path_defaults_to_aws(self):
        from range_terraform_runner import AWS_RANGE_MODULE_PATH, get_range_module_path

        with patch.dict(os.environ, {"CLOUD_PROVIDER": "aws"}, clear=True):
            assert get_range_module_path() == AWS_RANGE_MODULE_PATH

    def test_get_range_module_path_fails_fast_for_gcp(self):
        from range_terraform_runner import get_range_module_path

        with (
            patch.dict(os.environ, {"CLOUD_PROVIDER": "gcp"}, clear=True),
            pytest.raises(RuntimeError, match="does not expose a Terraform module path"),
        ):
            get_range_module_path()

    def test_get_range_module_path_raises_for_unsupported_provider(self, monkeypatch):
        """A future third backend must not silently receive the AWS Terraform
        module path (the previous ``gcp ? raise : AWS_RANGE_MODULE_PATH`` shape
        treated any non-gcp value as AWS)."""
        import range_terraform_runner
        from cloud.exceptions import CloudProviderNotImplementedError

        monkeypatch.setattr(range_terraform_runner, "resolve_cloud_provider", lambda *a, **k: "azure")

        with pytest.raises(CloudProviderNotImplementedError, match="azure"):
            range_terraform_runner.get_range_module_path()

    def test_get_range_state_key_prefix_raises_for_unsupported_provider(self, monkeypatch):
        """A future third backend must not silently inherit the AWS ``"ranges"``
        state key prefix."""
        import range_terraform_runner
        from cloud.exceptions import CloudProviderNotImplementedError

        monkeypatch.setattr(range_terraform_runner, "resolve_cloud_provider", lambda *a, **k: "azure")

        with pytest.raises(CloudProviderNotImplementedError, match="azure"):
            range_terraform_runner.get_range_state_key_prefix()

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
    def test_apply_range_gdc_purpose_gate(self, mock_network_apply, mock_pod_apply, mock_vm_apply):
        # Issue #1348 / ADR-030: the retained GDC substrate is reachable only under the
        # explicit non-user validation purpose. A generic (default live-fire) provision
        # is denied by the provisioner defense-in-depth check BEFORE any gdc_* apply
        # call, carrying the stable identity-or-policy code. Both branches share this
        # single patch set so no first-party seam mock count grows (ADR-019-R1).
        from shared.range_instantiation_policy import POLICY_DENIAL_CODE, InstantiationPurpose

        from cloud.exceptions import CloudError
        from range_terraform_runner import apply_range

        variables = {"range_id": 42, "subnets": []}
        subnets = {"attack": {"subnet_id": "range-42-attack"}}

        # Validation purpose: routes through the retained GDC runners.
        with patch.dict(os.environ, {"CLOUD_PROVIDER": "gcp", "GCP_RANGE_BACKEND": "gdc"}, clear=True):
            result = apply_range("req-123", variables, purpose=InstantiationPurpose.NON_USER_VALIDATION)

        assert result == {
            "subnets": subnets,
            "instances": [
                {"instance_id": "range-42-attack-attacker-1234"},
                {"instance_id": "range-42-attack-victim-5678-pod"},
            ],
        }
        mock_network_apply.assert_called_once_with("req-123", variables)
        mock_vm_apply.assert_called_once_with("req-123", variables, subnets)
        mock_pod_apply.assert_called_once_with("req-123", variables, subnets)

        mock_network_apply.reset_mock()
        mock_vm_apply.reset_mock()
        mock_pod_apply.reset_mock()

        # Default (live-fire) purpose: denied before any gdc_* apply call, and the
        # CloudError carries the permanent identity-or-policy classification.
        with (
            patch.dict(os.environ, {"CLOUD_PROVIDER": "gcp", "GCP_RANGE_BACKEND": "gdc"}, clear=True),
            pytest.raises(CloudError, match=r"not admitted for instantiation purpose 'live_fire'") as denial,
        ):
            apply_range("req-123", variables)

        assert denial.value.code == POLICY_DENIAL_CODE
        mock_network_apply.assert_not_called()
        mock_vm_apply.assert_not_called()
        mock_pod_apply.assert_not_called()

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

        order = Mock()
        order.attach_mock(mock_pod_destroy, "pod_destroy")
        order.attach_mock(mock_asset_destroy, "vm_destroy")
        order.attach_mock(mock_network_destroy, "network_destroy")

        with patch.dict(os.environ, {"CLOUD_PROVIDER": "gcp", "GCP_RANGE_BACKEND": "gdc"}, clear=True):
            destroy_range("req-123", variables={"range_id": 42, "subnets": []})

        mock_pod_destroy.assert_called_once_with("req-123", {"range_id": 42, "subnets": []})
        mock_asset_destroy.assert_called_once_with("req-123", {"range_id": 42, "subnets": []})
        mock_network_destroy.assert_called_once_with("req-123", {"range_id": 42, "subnets": []})
        assert order.mock_calls == [
            call.pod_destroy("req-123", {"range_id": 42, "subnets": []}),
            call.vm_destroy("req-123", {"range_id": 42, "subnets": []}),
            call.network_destroy("req-123", {"range_id": 42, "subnets": []}),
        ]

    def test_get_range_state_key_prefix_uses_provider_specific_paths(self):
        from range_terraform_runner import get_range_state_key_prefix

        with patch.dict(os.environ, {"CLOUD_PROVIDER": "aws"}, clear=True):
            assert get_range_state_key_prefix() == "ranges"

        with patch.dict(os.environ, {"CLOUD_PROVIDER": "gcp", "GCP_RANGE_BACKEND": "gdc"}, clear=True):
            assert get_range_state_key_prefix() == "gcp/gdc-ranges"

        with patch.dict(os.environ, {"CLOUD_PROVIDER": "gcp", "GCP_RANGE_BACKEND": "gce"}, clear=True):
            assert get_range_state_key_prefix() == "gcp/gce-range-cells"

    def test_apply_range_dispatches_to_gce_range_cell_backend(self):
        from range_terraform_runner import apply_range

        variables = _range_cell_variables()
        calls = []

        def fake_apply(request_uuid, received_variables):
            calls.append((request_uuid, received_variables))
            return {"subnets": {"attack": {"subnet_id": "shifter-r-42-attack"}}, "instances": []}

        with patch.dict(os.environ, {"CLOUD_PROVIDER": "gcp", "GCP_RANGE_BACKEND": "gce"}, clear=True):
            result = apply_range("req-123", variables, gce_apply_range_cell=fake_apply)

        assert result == {"subnets": {"attack": {"subnet_id": "shifter-r-42-attack"}}, "instances": []}
        assert calls == [("req-123", variables)]

    def test_apply_range_uses_bound_gce_backend_after_selector_flip(self):
        from range_terraform_runner import apply_range

        variables = _range_cell_variables()

        # Exercise the real GCE dispatch and config loader. The persisted binding
        # must override the flipped deploy selector, reaching GCE config
        # validation (and no cloud boundary) rather than the GDC denial path.
        with (
            patch.dict(os.environ, {"CLOUD_PROVIDER": "gcp", "GCP_RANGE_BACKEND": "gdc"}, clear=True),
            pytest.raises(RuntimeError, match="Missing required GCE range-cell configuration"),
        ):
            apply_range("req-123", variables, backend="gce")

    def test_destroy_range_dispatches_to_gce_range_cell_backend(self):
        from range_terraform_runner import destroy_range

        variables = _range_cell_variables()
        calls = []

        def fake_destroy(request_uuid, received_variables):
            calls.append((request_uuid, received_variables))

        with patch.dict(os.environ, {"CLOUD_PROVIDER": "gcp", "GCP_RANGE_BACKEND": "gce"}, clear=True):
            destroy_range("req-123", variables=variables, gce_destroy_range_cell=fake_destroy)

        assert calls == [("req-123", variables)]

    def test_destroy_range_uses_bound_gce_backend_after_selector_flip(self):
        from range_terraform_runner import destroy_range

        variables = _range_cell_variables()

        # As above, the authored config error is observable evidence that real
        # destroy dispatch forwarded backend="gce" through to the GCE loader.
        with (
            patch.dict(os.environ, {"CLOUD_PROVIDER": "gcp", "GCP_RANGE_BACKEND": "gdc"}, clear=True),
            pytest.raises(RuntimeError, match="Missing required GCE range-cell configuration"),
        ):
            destroy_range("req-123", variables=variables, backend="gce")

    def test_has_terraform_state_short_circuits_provider_native_gcp_backends(self):
        from range_terraform_runner import has_terraform_state

        with patch.dict(os.environ, {"CLOUD_PROVIDER": "gcp"}, clear=True):
            assert has_terraform_state("req-123") is False

        with patch.dict(os.environ, {"CLOUD_PROVIDER": "gcp", "GCP_RANGE_BACKEND": "gce"}, clear=True):
            assert has_terraform_state("req-123") is False


class TestDestroyRange:
    """Test destroy_range passes variables correctly.

    Issue #1103: destroy() stages a writable workspace under TERRAFORM_WORKSPACE_DIR,
    runs terraform from the staged path, and cleans the staged tree up on success and
    failure. These tests cover the public destroy_range contract: var-file is passed
    iff variables are supplied, and the staged workspace is removed when the call
    returns.
    """

    @patch.dict(os.environ, {"TF_STATE_BUCKET": "shifter-dev-pulumi-state", "CLOUD_PROVIDER": "aws"}, clear=True)
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

    @patch.dict(os.environ, {"TF_STATE_BUCKET": "shifter-dev-pulumi-state", "CLOUD_PROVIDER": "aws"}, clear=True)
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

    @patch.dict(os.environ, {"TF_STATE_BUCKET": "shifter-dev-pulumi-state", "CLOUD_PROVIDER": "aws"}, clear=True)
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
