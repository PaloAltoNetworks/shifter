"""Tests for range_terraform_runner module.

Covers destroy_range variable passing (mirrors test_terraform_runner.py for NGFW).
"""

from pathlib import Path
from unittest.mock import MagicMock, mock_open, patch

import pytest


class TestDestroyRange:
    """Test destroy_range passes variables correctly."""

    @patch("range_terraform_runner._run_terraform")
    @patch("range_terraform_runner.init_range_workspace")
    def test_destroy_with_variables_writes_tfvars(self, mock_init, mock_run, tmp_path):
        """When variables are provided, destroy should write tfvars and pass -var-file."""
        from range_terraform_runner import destroy_range

        working_dir = tmp_path / "test-module"
        working_dir.mkdir()
        variables = {"range_id": 42, "user_id": 1, "request_uuid": "req-123"}

        with patch("builtins.open", mock_open()) as mocked_file, patch.object(Path, "unlink"):
            destroy_range("req-123", working_dir, variables=variables)

        mocked_file.assert_called_once_with(working_dir / "terraform.tfvars.json", "w")
        written_data = mocked_file().write.call_args_list
        assert len(written_data) > 0

        destroy_args = mock_run.call_args[0][0]
        assert any("-var-file=" in arg for arg in destroy_args)

    @patch("range_terraform_runner._run_terraform")
    @patch("range_terraform_runner.init_range_workspace")
    def test_destroy_without_variables_no_var_file(self, mock_init, mock_run, tmp_path):
        """When no variables provided, destroy should not pass -var-file."""
        from range_terraform_runner import destroy_range

        working_dir = tmp_path / "test-module"
        working_dir.mkdir()

        destroy_range("req-123", working_dir)

        destroy_args = mock_run.call_args[0][0]
        assert not any("-var-file=" in arg for arg in destroy_args)
        assert "-auto-approve" in destroy_args

    @patch("range_terraform_runner._run_terraform", side_effect=RuntimeError("destroy failed"))
    @patch("range_terraform_runner.init_range_workspace")
    def test_destroy_cleans_up_tfvars_on_failure(self, mock_init, mock_run, tmp_path):
        """Tfvars file should be cleaned up even if destroy fails."""
        from range_terraform_runner import destroy_range

        working_dir = tmp_path / "test-module"
        working_dir.mkdir()
        variables = {"range_id": 42}
        mock_unlink = MagicMock()

        with (
            patch("builtins.open", mock_open()),
            patch.object(Path, "unlink", mock_unlink),
            pytest.raises(RuntimeError, match="destroy failed"),
        ):
            destroy_range("req-123", working_dir, variables=variables)

        mock_unlink.assert_called_once_with(missing_ok=True)

    @patch("range_terraform_runner._run_terraform")
    @patch("range_terraform_runner.init_range_workspace")
    def test_destroy_without_variables_does_not_create_tfvars(self, mock_init, mock_run, tmp_path):
        """When no variables provided, no tfvars file should be created or cleaned up."""
        from range_terraform_runner import destroy_range

        working_dir = tmp_path / "test-module"
        working_dir.mkdir()
        mock_unlink = MagicMock()

        with patch.object(Path, "unlink", mock_unlink):
            destroy_range("req-123", working_dir)

        mock_unlink.assert_not_called()
