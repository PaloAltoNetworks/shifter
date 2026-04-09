"""Tests for provider-aware Terraform backend helpers."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


class TestBackendResolution:
    """Tests for Terraform backend selection and state key layout."""

    @patch.dict("os.environ", {}, clear=True)
    def test_get_backend_type_defaults_to_s3(self):
        from terraform_base import get_backend_type

        assert get_backend_type() == "s3"

    @patch.dict("os.environ", {"CLOUD_PROVIDER": "gcp"}, clear=True)
    def test_get_backend_type_uses_gcs_for_gcp(self):
        from terraform_base import get_backend_type

        assert get_backend_type() == "gcs"

    @patch.dict("os.environ", {"STATE_BUCKET_URL": "gs://shifter-gcp-dev-terraform-state"}, clear=True)
    def test_get_state_bucket_parses_gcs_backend_url(self):
        from terraform_base import get_state_bucket

        assert get_state_bucket() == "shifter-gcp-dev-terraform-state"

    @patch.dict("os.environ", {"CLOUD_PROVIDER": "gcp"}, clear=True)
    def test_get_state_key_uses_gcs_state_filename(self):
        from terraform_base import get_state_key

        assert get_state_key("gcp/ranges", "req-123") == "gcp/ranges/req-123/default.tfstate"


class TestWorkspaceInitialization:
    """Tests for backend-specific terraform init arguments."""

    @patch.dict("os.environ", {"TF_STATE_BUCKET": "shifter-dev-pulumi-state"}, clear=True)
    @patch("terraform_base.run_terraform")
    def test_init_workspace_uses_s3_backend_config(self, mock_run):
        from terraform_base import init_workspace

        init_workspace("ranges", "req-123", MagicMock(), "Range")

        init_args = mock_run.call_args.args[0]
        assert "-backend-config=bucket=shifter-dev-pulumi-state" in init_args
        assert "-backend-config=key=ranges/req-123/terraform.tfstate" in init_args
        assert "-backend-config=dynamodb_table=shifter-dev-pulumi-locks" in init_args
        assert not any(arg.startswith("-backend-config=prefix=") for arg in init_args)

    @patch.dict(
        "os.environ",
        {"CLOUD_PROVIDER": "gcp", "TF_STATE_BUCKET": "shifter-gcp-dev-terraform-state"},
        clear=True,
    )
    @patch("terraform_base.run_terraform")
    def test_init_workspace_uses_gcs_backend_config(self, mock_run):
        from terraform_base import init_workspace

        init_workspace("gcp/ranges", "req-123", MagicMock(), "Range")

        init_args = mock_run.call_args.args[0]
        assert "-backend-config=bucket=shifter-gcp-dev-terraform-state" in init_args
        assert "-backend-config=prefix=gcp/ranges/req-123" in init_args
        assert not any(arg.startswith("-backend-config=key=") for arg in init_args)
        assert not any("dynamodb_table=" in arg for arg in init_args)


class TestStateCleanup:
    """Tests for provider-aware cleanup behavior."""

    @patch.dict(
        "os.environ",
        {"CLOUD_PROVIDER": "gcp", "TF_STATE_BUCKET": "shifter-gcp-dev-terraform-state"},
        clear=True,
    )
    @patch("terraform_base.get_object_storage")
    def test_cleanup_state_skips_lock_cleanup_for_gcs(self, mock_get_storage):
        from terraform_base import cleanup_state

        storage = MagicMock()
        mock_get_storage.return_value = storage

        cleanup_state("gcp/ranges", "req-123", "Range")

        storage.delete_object.assert_called_once_with(
            bucket="shifter-gcp-dev-terraform-state",
            key="gcp/ranges/req-123/default.tfstate",
        )
