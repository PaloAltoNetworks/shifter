"""Tests for terraform_runner module.

Covers destroy_ngfw variable passing and _build_tf_variables helper.
"""

import os
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

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
            "SECRETS_KMS_KEY_ARN": "arn:aws:kms:us-east-2:123456789012:key/abcd-1234",
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
        assert result["secrets_kms_key_arn"] == "arn:aws:kms:us-east-2:123456789012:key/abcd-1234"
        assert result["subnet_id"] == "subnet-abc"
        assert result["ami_id"] == "ami-123"
        assert result["instance_profile_name"] == "my-profile"
        assert result["scm_pin_id"] == "pin-1"
        assert result["authcode"] == "auth-abc"

    @patch.dict(
        "os.environ",
        {"SECRETS_KMS_KEY_ARN": "arn:aws:kms:us-east-2:123456789012:key/abcd-1234"},
        clear=True,
    )
    def test_defaults_when_optional_env_vars_missing(self):
        """Should use defaults for optional env vars; mandatory KMS ARN is supplied."""
        from ngfw_terraform import _build_tf_variables

        result = _build_tf_variables("req-1", "inst-1", {})

        assert result["user_id"] == 0
        assert result["name_prefix"] == "ngfw-user-0"
        assert result["environment"] == "dev"
        assert result["secrets_kms_key_arn"] == "arn:aws:kms:us-east-2:123456789012:key/abcd-1234"
        assert result["subnet_id"] == ""
        assert result["instance_type"] == "m5.xlarge"
        assert result["instance_profile_name"] is None

    @patch.dict("os.environ", {}, clear=True)
    def test_raises_keyerror_when_secrets_kms_key_arn_missing(self):
        """Fail-fast on missing SECRETS_KMS_KEY_ARN.

        Mandatory env var; runtime tfvars must not silently fall back to
        AWS-managed keys (CKV_AWS_149 / #213).
        """
        import pytest

        from ngfw_terraform import _build_tf_variables

        with pytest.raises(KeyError, match="SECRETS_KMS_KEY_ARN"):
            _build_tf_variables("req-1", "inst-1", {})


class TestCleanupNgfwBootstrapObjects:
    """Test post-ready cleanup of sensitive NGFW S3 bootstrap objects."""

    @patch.dict(
        "os.environ",
        {
            "CLOUD_PROVIDER": "aws",
            "NGFW_BOOTSTRAP_BUCKET": "bootstrap-bucket",
        },
        clear=False,
    )
    @patch("cloud.get_object_storage")
    def test_deletes_sensitive_bootstrap_objects(self, mock_get_object_storage):
        """Cleanup removes init-cfg.txt and authcodes from the instance bootstrap prefix."""
        from ngfw_terraform import _cleanup_ngfw_bootstrap_objects

        storage = mock_get_object_storage.return_value

        _cleanup_ngfw_bootstrap_objects("inst-555")

        assert storage.delete_object.call_args_list == [
            call(bucket="bootstrap-bucket", key="bootstrap/ngfw/inst-555/config/init-cfg.txt"),
            call(bucket="bootstrap-bucket", key="bootstrap/ngfw/inst-555/license/authcodes"),
        ]

    @patch.dict("os.environ", {"CLOUD_PROVIDER": "gcp", "NGFW_BOOTSTRAP_BUCKET": "bootstrap-bucket"}, clear=False)
    @patch("cloud.get_object_storage")
    def test_skips_non_aws_provider(self, mock_get_object_storage):
        """Cleanup is S3-specific and should not run for GCP VM-Series provisioning."""
        from ngfw_terraform import _cleanup_ngfw_bootstrap_objects

        _cleanup_ngfw_bootstrap_objects("inst-555")

        mock_get_object_storage.assert_not_called()

    @patch.dict(
        "os.environ",
        {
            "CLOUD_PROVIDER": "aws",
            "NGFW_BOOTSTRAP_BUCKET": "bootstrap-bucket",
        },
        clear=False,
    )
    @patch("cloud.get_object_storage")
    def test_attempts_all_sensitive_bootstrap_objects_before_raising(self, mock_get_object_storage):
        """Cleanup should try every sensitive key even when one delete fails."""
        from ngfw_terraform import _cleanup_ngfw_bootstrap_objects

        storage = mock_get_object_storage.return_value
        storage.delete_object.side_effect = [RuntimeError("denied"), None]

        with pytest.raises(RuntimeError, match=r"config/init-cfg\.txt"):
            _cleanup_ngfw_bootstrap_objects("inst-555")

        assert storage.delete_object.call_args_list == [
            call(bucket="bootstrap-bucket", key="bootstrap/ngfw/inst-555/config/init-cfg.txt"),
            call(bucket="bootstrap-bucket", key="bootstrap/ngfw/inst-555/license/authcodes"),
        ]

    @patch.dict("os.environ", {"CLOUD_PROVIDER": "aws"}, clear=True)
    def test_requires_bootstrap_bucket_for_aws_cleanup(self):
        """AWS cleanup should fail loudly rather than silently retaining bootstrap secrets."""
        from ngfw_terraform import _cleanup_ngfw_bootstrap_objects

        with pytest.raises(RuntimeError, match="NGFW_BOOTSTRAP_BUCKET"):
            _cleanup_ngfw_bootstrap_objects("inst-555")


class TestNgfwTerraformOrchestrationHelpers:
    """Test NGFW Terraform orchestration branches touched by the Sonar follow-up."""

    @patch("ngfw_terraform._run_deprovision")
    @patch("ngfw_terraform._run_gdc_deprovision")
    @patch("ngfw_terraform._run_provision")
    @patch("ngfw_terraform._run_gdc_provision")
    def test_provider_dispatch_routes_operations(
        self,
        mock_gdc_provision,
        mock_aws_provision,
        mock_gdc_deprovision,
        mock_aws_deprovision,
        monkeypatch,
    ):
        """Provider dispatch should route up/destroy without early-return branches."""
        from ngfw_terraform import _run_ngfw_operation_for_provider

        app_spec = {"user_id": 7}
        monkeypatch.setenv("CLOUD_PROVIDER", "aws")
        _run_ngfw_operation_for_provider("up", "req-1", "inst-1", "app-1", app_spec, "americas")
        _run_ngfw_operation_for_provider("destroy", "req-1", "inst-1", "app-1", app_spec, "americas")

        monkeypatch.setenv("CLOUD_PROVIDER", "gcp")
        _run_ngfw_operation_for_provider("up", "req-2", "inst-2", "app-2", app_spec, "europe")
        _run_ngfw_operation_for_provider("destroy", "req-2", "inst-2", "app-2", app_spec, "europe")

        mock_aws_provision.assert_called_once_with("req-1", "inst-1", "app-1", app_spec, "americas")
        mock_aws_deprovision.assert_called_once_with("req-1", "inst-1", "app-1")
        mock_gdc_provision.assert_called_once_with("req-2", "inst-2", "app-2", app_spec, "europe")
        mock_gdc_deprovision.assert_called_once_with("req-2", "inst-2", "app-2")

        with pytest.raises(ValueError, match="Unknown operation"):
            _run_ngfw_operation_for_provider("rotate", "req-3", "inst-3", "app-3", app_spec, "americas")

    @patch.dict(
        "os.environ",
        {
            "CLOUD_PROVIDER": "aws",
            "SECRETS_KMS_KEY_ARN": "arn:aws:kms:us-east-2:123456789012:key/abcd-1234",
        },
        clear=True,
    )
    @patch("ngfw_terraform.terraform_runner.cleanup_ngfw_state")
    @patch("ngfw_terraform.terraform_runner.destroy_ngfw")
    def test_cleanup_failed_ngfw_provision_destroys_aws_terraform(self, mock_destroy_ngfw, mock_cleanup_state):
        """AWS provision cleanup should destroy Terraform with the same variable contract."""
        from ngfw_terraform import _cleanup_failed_ngfw_provision

        _cleanup_failed_ngfw_provision("req-1", "inst-1", {"user_id": 7})

        destroy_variables = mock_destroy_ngfw.call_args.kwargs["variables"]
        assert destroy_variables["name_prefix"] == "ngfw-user-7"
        mock_cleanup_state.assert_called_once_with("req-1")

    @patch.dict("os.environ", {"CLOUD_PROVIDER": "gcp"}, clear=True)
    def test_cleanup_failed_ngfw_provision_destroys_gdc_state(self, monkeypatch):
        """GCP provision cleanup should call the GDC VM-Series destroy helper when state exists."""
        from ngfw_terraform import _cleanup_failed_ngfw_provision

        fake_state = {"vm_name": "vmseries"}
        fake_gdc = SimpleNamespace(destroy_ngfw=MagicMock())
        monkeypatch.setattr("ngfw_terraform.get_ngfw_data_by_request_id", MagicMock(return_value={"state": fake_state}))
        monkeypatch.setitem(sys.modules, "gdc_vmseries_ngfw", fake_gdc)

        _cleanup_failed_ngfw_provision("req-1", "inst-1", {})

        fake_gdc.destroy_ngfw.assert_called_once_with(fake_state)

    @patch("ngfw_terraform._run_ngfw_operation_for_provider")
    def test_run_ngfw_terraform_dispatches_database_payload(self, mock_dispatch, monkeypatch):
        """run_ngfw_terraform should load DB data and pass the normalized app spec to dispatch."""
        from ngfw_terraform import run_ngfw_terraform

        monkeypatch.setattr(
            "ngfw_terraform.get_ngfw_data_by_request_id",
            MagicMock(
                return_value={
                    "instance_id": "inst-1",
                    "app_id": "app-1",
                    "app_spec": {"sls_region": "americas", "user_id": 7},
                }
            ),
        )

        run_ngfw_terraform("up", "req-1")

        mock_dispatch.assert_called_once_with(
            "up",
            "req-1",
            "inst-1",
            "app-1",
            {"sls_region": "americas", "user_id": 7},
            "americas",
        )

    @patch("ngfw_terraform.publish_ngfw_event")
    @patch("ngfw_terraform._cleanup_failed_ngfw_provision")
    @patch("ngfw_terraform._run_ngfw_operation_for_provider", side_effect=RuntimeError("apply failed"))
    def test_run_ngfw_terraform_marks_failed_and_cleans_up_provision(
        self,
        _mock_dispatch,
        mock_cleanup,
        mock_publish_ngfw_event,
        monkeypatch,
    ):
        """Provision failures should best-effort cleanup, mark failed, and republish failure."""
        from ngfw_terraform import run_ngfw_terraform

        app_spec = {"sls_region": "americas", "user_id": 7}
        monkeypatch.setattr(
            "ngfw_terraform.get_ngfw_data_by_request_id",
            MagicMock(return_value={"instance_id": "inst-1", "app_id": "app-1", "app_spec": app_spec}),
        )
        mock_update_instance_state = MagicMock()
        monkeypatch.setattr("ngfw_terraform.update_instance_state", mock_update_instance_state)

        with pytest.raises(RuntimeError, match="apply failed"):
            run_ngfw_terraform("up", "req-1")

        mock_cleanup.assert_called_once_with("req-1", "inst-1", app_spec)
        mock_update_instance_state.assert_called_once_with(
            "req-1",
            "failed",
            error_message="apply failed",
        )
        mock_publish_ngfw_event.assert_called_once_with(
            request_id="req-1",
            instance_id="inst-1",
            app_id="app-1",
            status="failed",
        )

    @patch("ngfw_terraform.publish_ngfw_event")
    def test_short_circuit_local_dev_post_provision_marks_ready_then_paused(self, mock_publish_ngfw_event):
        """Local-dev post-provision should emit ready and paused states without PAN-OS calls."""
        from ngfw_terraform import _short_circuit_local_dev_post_provision

        update_instance_state = MagicMock()
        _short_circuit_local_dev_post_provision(
            request_id="req-1",
            instance_id="inst-1",
            app_id="app-1",
            output_data={"cloud_provider": "gcp", "route_next_hop_ip": "10.0.0.1"},
            update_instance_state=update_instance_state,
        )

        update_instance_state.assert_has_calls(
            [
                call(
                    "req-1",
                    "ready",
                    cloud_provider="gcp",
                    route_next_hop_ip="10.0.0.1",
                    attachment_mode="gdc-vmruntime-palo-alto-vmseries",
                    data_attachment_id="",
                    attached_ranges=[],
                    provider_metadata={},
                ),
                call("req-1", "paused"),
            ]
        )
        assert mock_publish_ngfw_event.call_count == 2

    @patch("ngfw_terraform._run_pan_os_post_provision")
    @patch("ngfw_terraform.publish_ngfw_event")
    @patch("ngfw_terraform.terraform_runner.apply_ngfw")
    def test_run_provision_logs_only_redacted_output_summary(
        self,
        mock_apply_ngfw,
        mock_publish_ngfw_event,
        mock_post_provision,
        monkeypatch,
    ):
        """AWS provision should not log full Terraform output dictionaries."""
        from ngfw_terraform import _run_provision

        mock_update_instance_state = MagicMock()
        monkeypatch.setattr("ngfw_terraform.update_instance_state", mock_update_instance_state)
        monkeypatch.setenv("SECRETS_KMS_KEY_ARN", "arn:aws:kms:us-east-2:123456789012:key/abcd-1234")
        mock_apply_ngfw.return_value = {
            "management_ip": "10.1.1.10",
            "ssh_key_secret_arn": "arn:aws:secretsmanager:us-east-2:123:secret:key",
        }

        _run_provision("req-1", "inst-1", "app-1", {"user_id": 7}, "americas")

        mock_update_instance_state.assert_called_once_with("req-1", "provisioning")
        mock_publish_ngfw_event.assert_called_once_with(
            request_id="req-1",
            instance_id="inst-1",
            app_id="app-1",
            status="provisioning",
        )
        mock_post_provision.assert_called_once_with(
            request_id="req-1",
            instance_id="inst-1",
            app_id="app-1",
            output_data=mock_apply_ngfw.return_value,
            sls_region="americas",
        )

    @patch("ngfw_terraform._run_pan_os_post_provision")
    @patch("ngfw_terraform.publish_ngfw_event")
    def test_run_gdc_provision_persists_state_before_post_provision(
        self,
        mock_publish_ngfw_event,
        mock_post_provision,
        monkeypatch,
    ):
        """GDC provision should persist VM Runtime output state before PAN-OS setup."""
        from ngfw_terraform import _run_gdc_provision

        output_data = {
            "cloud_provider": "gcp",
            "route_next_hop_ip": "10.200.1.1",
            "attachment_mode": "gdc-vmruntime-palo-alto-vmseries",
            "data_attachment_id": "ngfw-user-42/vmseries:eth1",
        }
        fake_gdc = SimpleNamespace(apply_ngfw=MagicMock(return_value=output_data))
        mock_update_instance_state = MagicMock()
        monkeypatch.setattr("ngfw_terraform.update_instance_state", mock_update_instance_state)
        monkeypatch.setitem(sys.modules, "gdc_vmseries_ngfw", fake_gdc)

        _run_gdc_provision("req-1", "inst-1", "app-1", {"user_id": 7}, "americas")

        assert mock_update_instance_state.call_count == 2
        persisted_state = mock_update_instance_state.call_args_list[1].kwargs
        assert persisted_state["route_next_hop_ip"] == "10.200.1.1"
        assert persisted_state["data_attachment_id"] == "ngfw-user-42/vmseries:eth1"
        assert mock_publish_ngfw_event.call_count == 1
        mock_post_provision.assert_called_once_with(
            request_id="req-1",
            instance_id="inst-1",
            app_id="app-1",
            output_data=output_data,
            sls_region="americas",
        )


class TestNgfwTerraformCleanupHelpers:
    """Test NGFW Terraform cleanup and deprovision helper paths."""

    @patch("ngfw_terraform_cleanup.NGFWExecutor")
    @patch("cloud.get_secrets_store")
    def test_deactivate_vmseries_license_fetches_secret_and_runs_command(
        self,
        mock_get_secrets_store,
        mock_executor_class,
    ):
        """License deactivation should load the private key and run the PAN-OS request."""
        from ngfw_terraform_cleanup import _deactivate_vmseries_license

        mock_get_secrets_store.return_value.get_secret.return_value = "private-key"
        mock_executor = mock_executor_class.return_value

        _deactivate_vmseries_license(
            management_ip="10.1.1.10",
            ssh_key_secret_arn="arn:aws:secretsmanager:us-east-2:123:secret:key",
        )

        mock_get_secrets_store.return_value.get_secret.assert_called_once_with(
            "arn:aws:secretsmanager:us-east-2:123:secret:key"
        )
        mock_executor.wait_for_agent.assert_called_once_with("10.1.1.10", timeout_seconds=300)
        mock_executor.run_command.assert_called_once_with(
            instance_id="10.1.1.10",
            script="",
            stdin_input="request license deactivate VM-Capacity mode auto\n",
            timeout_seconds=120,
        )

    @patch("ngfw_terraform_cleanup._deactivate_vmseries_license")
    @patch("ngfw_terraform_cleanup.boto3.client")
    def test_deactivate_aws_vmseries_license_starts_stopped_instance(
        self,
        mock_boto_client,
        mock_deactivate_license,
    ):
        """Stopped AWS NGFW instances must be started before license deactivation."""
        from ngfw_terraform_cleanup import _deactivate_aws_vmseries_license

        ec2_client = mock_boto_client.return_value
        ec2_client.describe_instances.return_value = {"Reservations": [{"Instances": [{"State": {"Name": "stopped"}}]}]}
        waiter = ec2_client.get_waiter.return_value

        _deactivate_aws_vmseries_license(
            {
                "management_ip": "10.1.1.10",
                "ssh_key_secret_arn": "arn:aws:secretsmanager:us-east-2:123:secret:key",
                "ec2_instance_id": "i-123",
            }
        )

        ec2_client.start_instances.assert_called_once_with(InstanceIds=["i-123"])
        waiter.wait.assert_called_once_with(InstanceIds=["i-123"])
        mock_deactivate_license.assert_called_once_with(
            management_ip="10.1.1.10",
            ssh_key_secret_arn="arn:aws:secretsmanager:us-east-2:123:secret:key",
        )

    @patch("ngfw_terraform_cleanup.boto3.client")
    def test_deactivate_aws_vmseries_license_skips_missing_state_fields(self, mock_boto_client):
        """Missing runtime state should skip deactivation without touching EC2."""
        from ngfw_terraform_cleanup import _deactivate_aws_vmseries_license

        _deactivate_aws_vmseries_license({"management_ip": "10.1.1.10"})

        mock_boto_client.assert_not_called()

    @patch("ngfw_terraform_cleanup.publish_ngfw_event")
    @patch("ngfw_terraform_cleanup._deactivate_vmseries_license")
    def test_run_gdc_deprovision_powers_on_deactivates_and_destroys(
        self,
        mock_deactivate_license,
        mock_publish_ngfw_event,
        monkeypatch,
    ):
        """GDC deprovision should start the VM-Series appliance before license cleanup."""
        from ngfw_terraform_cleanup import _run_gdc_deprovision

        fake_state = {
            "management_ip": "10.200.1.10",
            "ssh_key_secret_arn": "projects/demo/secrets/ngfw-key",
        }
        fake_gdc = SimpleNamespace(
            run_power_operation=MagicMock(),
            destroy_ngfw=MagicMock(),
        )
        monkeypatch.setattr(
            "ngfw_terraform_cleanup.get_ngfw_data_by_request_id",
            MagicMock(return_value={"state": fake_state}),
        )
        mock_update_instance_state = MagicMock()
        monkeypatch.setattr("ngfw_terraform_cleanup.update_instance_state", mock_update_instance_state)
        monkeypatch.setitem(sys.modules, "gdc_vmseries_ngfw", fake_gdc)

        _run_gdc_deprovision("req-1", "inst-1", "app-1")

        mock_update_instance_state.assert_has_calls([call("req-1", "destroying"), call("req-1", "destroyed")])
        fake_gdc.run_power_operation.assert_called_once_with("start", fake_state)
        mock_deactivate_license.assert_called_once_with(
            management_ip="10.200.1.10",
            ssh_key_secret_arn="projects/demo/secrets/ngfw-key",
        )
        fake_gdc.destroy_ngfw.assert_called_once_with(fake_state)
        assert mock_publish_ngfw_event.call_count == 2

    @patch.dict(
        "os.environ",
        {"SECRETS_KMS_KEY_ARN": "arn:aws:kms:us-east-2:123456789012:key/abcd-1234"},
        clear=True,
    )
    @patch("ngfw_terraform_cleanup.publish_ngfw_event")
    @patch("ngfw_terraform_cleanup._deactivate_aws_vmseries_license")
    @patch("ngfw_terraform_cleanup.terraform_runner.cleanup_ngfw_state")
    @patch("ngfw_terraform_cleanup.terraform_runner.destroy_ngfw")
    def test_run_deprovision_deactivates_license_then_destroys_terraform(
        self,
        mock_destroy_ngfw,
        mock_cleanup_state,
        mock_deactivate_license,
        mock_publish_ngfw_event,
        monkeypatch,
    ):
        """AWS deprovision should deactivate the license, destroy Terraform, and mark destroyed."""
        from ngfw_terraform_cleanup import _run_deprovision

        current_state = {
            "management_ip": "10.1.1.10",
            "ssh_key_secret_arn": "arn:aws:secretsmanager:us-east-2:123:secret:key",
            "ec2_instance_id": "i-123",
        }
        monkeypatch.setattr(
            "ngfw_terraform_cleanup.get_ngfw_data_by_request_id",
            MagicMock(return_value={"state": current_state, "app_spec": {"user_id": 7, "authcode": "auth-1"}}),
        )
        mock_update_instance_state = MagicMock()
        monkeypatch.setattr("ngfw_terraform_cleanup.update_instance_state", mock_update_instance_state)

        _run_deprovision("req-1", "inst-1", "app-1")

        mock_deactivate_license.assert_called_once_with(current_state)
        destroy_variables = mock_destroy_ngfw.call_args.kwargs["variables"]
        assert destroy_variables["name_prefix"] == "ngfw-user-7"
        assert destroy_variables["authcode"] == "auth-1"
        mock_cleanup_state.assert_called_once_with("req-1")
        mock_update_instance_state.assert_has_calls([call("req-1", "destroying"), call("req-1", "destroyed")])
        assert mock_publish_ngfw_event.call_count == 2


class TestRunPanOsPostProvision:
    """Test PAN-OS post-provision lifecycle behavior."""

    @patch.dict(
        "os.environ",
        {
            "CLOUD_PROVIDER": "aws",
            "NGFW_SSH_WAIT_TIMEOUT": "1",
            "NGFW_CERT_POLL_TIMEOUT": "1",
        },
        clear=False,
    )
    @patch("ngfw_terraform.publish_ngfw_event")
    @patch("ngfw_terraform._cleanup_ngfw_bootstrap_objects", side_effect=RuntimeError("cleanup failed"))
    @patch("ngfw_terraform.time.sleep")
    @patch("ngfw_terraform.SetupOrchestrator")
    @patch("ngfw_terraform.NGFWExecutor")
    @patch("cloud.get_secrets_store")
    def test_cleanup_failure_does_not_skip_auto_stop(
        self,
        mock_get_secrets_store,
        mock_ngfw_executor_class,
        mock_setup_orchestrator_class,
        _mock_sleep,
        _mock_cleanup,
        _mock_publish_ngfw_event,
        monkeypatch,
    ):
        """Bootstrap cleanup failures should surface only after auto-stop is attempted."""
        from ngfw_terraform import _run_pan_os_post_provision

        mock_update_instance_state = MagicMock()
        mock_run_ngfw_operation = MagicMock()
        monkeypatch.setattr("ngfw_terraform.poll_for_serial_number", MagicMock(return_value="serial-1"))
        monkeypatch.setattr("ngfw_terraform.poll_for_serial_and_cert", MagicMock(return_value="serial-2"))
        monkeypatch.setattr("ngfw_terraform.run_ngfw_operation", mock_run_ngfw_operation)
        monkeypatch.setattr("ngfw_terraform.update_instance_state", mock_update_instance_state)
        mock_get_secrets_store.return_value.get_secret.return_value = "private-key"
        mock_ngfw_executor = mock_ngfw_executor_class.return_value
        mock_ngfw_executor.run_command.return_value = MagicMock(success=True, stdout="", stderr="")
        mock_setup_orchestrator_class.return_value.orchestrate.return_value = MagicMock(success=True)

        with pytest.raises(RuntimeError, match="bootstrap object cleanup failed"):
            _run_pan_os_post_provision(
                request_id="req-1",
                instance_id="inst-1",
                app_id="app-1",
                output_data={
                    "management_ip": "10.1.1.10",
                    "dataplane_ip": "10.1.2.10",
                    "data_eni_id": "eni-1",
                    "ssh_key_secret_arn": "arn:aws:secretsmanager:us-east-2:123:secret:key",
                },
                sls_region="americas",
            )

        mock_run_ngfw_operation.assert_called_once_with("stop", "req-1")


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
