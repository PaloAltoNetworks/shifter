"""Tests for GuestSSHExecutor."""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock

import pytest

from executors.guest_ssh_executor import GuestSSHConnectionError, GuestSSHExecutor, TimeoutError


class TestGuestSSHExecutorRunCommand:
    """Tests for direct SSH command execution."""

    def test_linux_run_command_uses_bash_transport(self, mocker):
        mock_run = mocker.patch("executors.guest_ssh_executor.subprocess.run")
        mock_run.return_value = MagicMock(returncode=0, stdout=b"ok\n", stderr=b"")

        executor = GuestSSHExecutor(private_key="PRIVATE KEY", username="ubuntu")
        try:
            result = executor.run_command(
                instance_id="10.10.1.5",
                script="echo ok",
                document_name="AWS-RunShellScript",
            )
        finally:
            executor.close()

        assert result.success is True
        ssh_args = mock_run.call_args.args[0]
        assert ssh_args[-2:] == ["bash", "-se"]
        assert "ubuntu@10.10.1.5" in ssh_args
        assert "StrictHostKeyChecking=yes" in ssh_args
        assert "BatchMode=yes" in ssh_args
        assert "StrictHostKeyChecking=no" not in ssh_args
        assert "UserKnownHostsFile=/dev/null" not in ssh_args
        assert mock_run.call_args.kwargs["input"].decode("utf-8").startswith("set -euo pipefail\necho ok")

    def test_windows_run_command_uses_powershell_transport(self, mocker):
        mock_run = mocker.patch("executors.guest_ssh_executor.subprocess.run")
        mock_run.return_value = MagicMock(returncode=0, stdout=b"ok\n", stderr=b"")

        executor = GuestSSHExecutor(private_key="PRIVATE KEY", username="Administrator")
        try:
            result = executor.run_command(
                instance_id="10.10.1.10",
                script='Write-Output "ok"',
                document_name="AWS-RunPowerShellScript",
            )
        finally:
            executor.close()

        assert result.success is True
        ssh_args = mock_run.call_args.args[0]
        assert ssh_args[-7:] == [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            "-",
        ]
        assert "Administrator@10.10.1.10" in ssh_args
        assert mock_run.call_args.kwargs["input"].decode("utf-8") == 'Write-Output "ok"\n'

    def test_timeout_maps_to_executor_timeout(self, mocker):
        mocker.patch(
            "executors.guest_ssh_executor.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="ssh", timeout=5),
        )

        executor = GuestSSHExecutor(private_key="PRIVATE KEY", username="ubuntu")
        try:
            with pytest.raises(TimeoutError):
                executor.run_command(
                    instance_id="10.10.1.5",
                    script="sleep 60",
                    timeout_seconds=5,
                )
        finally:
            executor.close()

    def test_missing_ssh_binary_maps_to_connection_error(self, mocker):
        mocker.patch("executors.guest_ssh_executor.subprocess.run", side_effect=FileNotFoundError("ssh"))

        executor = GuestSSHExecutor(private_key="PRIVATE KEY", username="ubuntu")
        try:
            with pytest.raises(GuestSSHConnectionError):
                executor.run_command(instance_id="10.10.1.5", script="echo ok")
        finally:
            executor.close()


class TestGuestSSHExecutorReadiness:
    """Tests for readiness and reboot primitives."""

    def test_wait_for_ready_retries_until_probe_succeeds(self, mocker):
        mocker.patch("time.sleep")
        executor = GuestSSHExecutor(private_key="PRIVATE KEY", username="ubuntu", poll_interval_seconds=0)
        mocker.patch.object(executor, "_probe_ready", side_effect=[False, False, True])

        try:
            assert executor.wait_for_ready("10.10.1.5", timeout_seconds=30) is True
        finally:
            executor.close()

        assert executor._probe_ready.call_count == 3

    def test_reboot_and_wait_observes_offline_then_ready(self, mocker):
        mocker.patch("time.sleep")
        executor = GuestSSHExecutor(private_key="PRIVATE KEY", username="ubuntu", poll_interval_seconds=0)
        run_command = mocker.patch.object(executor, "run_command")
        mocker.patch.object(executor, "_probe_ready", side_effect=[False, True])

        try:
            assert executor.reboot_and_wait("10.10.1.5", timeout_seconds=30) is True
        finally:
            executor.close()

        run_command.assert_called_once()
