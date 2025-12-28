"""Tests for SSMExecutor Linux document support."""

from unittest.mock import MagicMock

import pytest

from components.ssm_executor import SSMExecutor, CommandError


class TestSSMExecutorLinuxDocument:
    """Test SSMExecutor supports Linux shell script document."""

    def test_run_command_uses_shell_script_document(self):
        """run_command uses AWS-RunShellScript when specified."""
        mock_ssm = MagicMock()
        mock_ec2 = MagicMock()

        mock_ssm.send_command.return_value = {"Command": {"CommandId": "cmd-12345"}}
        mock_ssm.get_command_invocation.return_value = {
            "Status": "Success",
            "ResponseCode": 0,
            "StandardOutputContent": "ok",
            "StandardErrorContent": "",
        }

        executor = SSMExecutor(ssm_client=mock_ssm, ec2_client=mock_ec2)
        result = executor.run_command(
            instance_id="i-12345",
            script="hostnamectl set-hostname test",
            document_name="AWS-RunShellScript",
        )

        assert result.success is True
        call_args = mock_ssm.send_command.call_args
        assert call_args.kwargs["DocumentName"] == "AWS-RunShellScript"

    def test_default_document_is_powershell(self):
        """Default document remains PowerShell for backwards compatibility."""
        mock_ssm = MagicMock()
        mock_ec2 = MagicMock()

        mock_ssm.send_command.return_value = {"Command": {"CommandId": "cmd-12345"}}
        mock_ssm.get_command_invocation.return_value = {
            "Status": "Success",
            "ResponseCode": 0,
            "StandardOutputContent": "",
            "StandardErrorContent": "",
        }

        executor = SSMExecutor(ssm_client=mock_ssm, ec2_client=mock_ec2)
        executor.run_command(instance_id="i-12345", script="Write-Host 'test'")

        call_args = mock_ssm.send_command.call_args
        assert call_args.kwargs["DocumentName"] == "AWS-RunPowerShellScript"

    def test_shell_script_failure_raises_command_error(self):
        """Shell script failure raises CommandError with stderr."""
        mock_ssm = MagicMock()
        mock_ec2 = MagicMock()

        mock_ssm.send_command.return_value = {"Command": {"CommandId": "cmd-12345"}}
        mock_ssm.get_command_invocation.return_value = {
            "Status": "Failed",
            "ResponseCode": 1,
            "StandardOutputContent": "",
            "StandardErrorContent": "command not found",
        }

        executor = SSMExecutor(ssm_client=mock_ssm, ec2_client=mock_ec2)

        with pytest.raises(CommandError) as exc_info:
            executor.run_command(
                instance_id="i-12345",
                script="nonexistent-command",
                document_name="AWS-RunShellScript",
            )

        assert exc_info.value.exit_code == 1
        assert "command not found" in exc_info.value.stderr
