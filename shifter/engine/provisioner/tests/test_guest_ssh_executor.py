"""Tests for GuestSSHExecutor."""

from __future__ import annotations

import base64
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
        # With no provisioner-supplied host key, no known_hosts pinning is added.
        assert not any(a.startswith("UserKnownHostsFile=") for a in ssh_args)
        assert not any(a.startswith("HostKeyAlgorithms=") for a in ssh_args)
        assert mock_run.call_args.kwargs["input"].decode("utf-8").startswith("set -euo pipefail\necho ok")

    def test_seeded_host_key_uses_bracketed_form_for_non_default_port(self, tmp_path):
        # A Docker-host guest reached on the management port (e.g. the Polaris
        # range host on :2222) must be seeded as [host]:port, else OpenSSH's
        # known_hosts lookup misses the entry and strict checking fails.
        executor = GuestSSHExecutor(
            private_key="PRIVATE KEY",
            username="ubuntu",
            port=2222,
            host_public_key="ssh-ed25519 AAAAHOSTKEY host",
            known_hosts_host="10.200.2.10",
        )
        try:
            with open(executor._known_hosts_path, encoding="utf-8") as fh:
                assert fh.read() == "[10.200.2.10]:2222 ssh-ed25519 AAAAHOSTKEY host\n"
        finally:
            executor.close()

    def test_seeded_host_key_pins_known_hosts_and_keeps_strict_checking(self, mocker, tmp_path):
        # D31: when the provisioner supplies the guest's host key, the executor
        # validates strictly against a single-entry known_hosts (no TOFU) and
        # pins ed25519 so the cloud-init-installed host key is the one matched.
        mock_run = mocker.patch("executors.guest_ssh_executor.subprocess.run")
        mock_run.return_value = MagicMock(returncode=0, stdout=b"ok\n", stderr=b"")

        host_pubkey = "ssh-ed25519 AAAAHOSTKEY guest"
        executor = GuestSSHExecutor(
            private_key="PRIVATE KEY",
            username="kali",
            host_public_key=host_pubkey,
            known_hosts_host="10.200.2.10",
        )
        try:
            known_hosts_path = executor._known_hosts_path
            assert known_hosts_path is not None
            with open(known_hosts_path, encoding="utf-8") as fh:
                assert fh.read() == "10.200.2.10 ssh-ed25519 AAAAHOSTKEY guest\n"

            executor.run_command(instance_id="10.200.2.10", script="echo ok")
            ssh_args = mock_run.call_args.args[0]
            assert "StrictHostKeyChecking=yes" in ssh_args
            assert f"UserKnownHostsFile={known_hosts_path}" in ssh_args
            assert "GlobalKnownHostsFile=/dev/null" in ssh_args
            assert "HostKeyAlgorithms=ssh-ed25519" in ssh_args
        finally:
            executor.close()
        # close() removes the temp known_hosts file.
        import os

        assert not os.path.exists(known_hosts_path)

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

    def test_windows_secret_stdin_is_separate_from_non_secret_encoded_source(self, mocker):
        mock_run = mocker.patch("executors.guest_ssh_executor.subprocess.run")
        mock_run.return_value = MagicMock(returncode=0, stdout=b"ok\n", stderr=b"")
        script = "$secret = [Console]::In.ReadToEnd(); Write-Output 'ok'"
        secret_input = "TOP-SECRET-RUNTIME-DATA\n"

        executor = GuestSSHExecutor(private_key="PRIVATE KEY", username="Administrator")
        try:
            executor.run_command(
                instance_id="10.10.1.10",
                script=script,
                stdin_input=secret_input,
                document_name="AWS-RunPowerShellScript",
            )
        finally:
            executor.close()

        ssh_args = mock_run.call_args.args[0]
        assert "-EncodedCommand" in ssh_args
        encoded = ssh_args[ssh_args.index("-EncodedCommand") + 1]
        assert base64.b64decode(encoded).decode("utf-16-le") == script
        assert secret_input.strip() not in " ".join(ssh_args)
        assert mock_run.call_args.kwargs["input"].decode("utf-8") == secret_input

    def test_linux_secret_stdin_is_separate_from_non_secret_encoded_source(self, mocker):
        mock_run = mocker.patch("executors.guest_ssh_executor.subprocess.run")
        mock_run.return_value = MagicMock(returncode=0, stdout=b"ok\n", stderr=b"")
        script = 'IFS= read -r secret; printf "received"'
        secret_input = "TOP-SECRET-RUNTIME-DATA\n"

        executor = GuestSSHExecutor(private_key="PRIVATE KEY", username="ubuntu")
        try:
            executor.run_command(
                instance_id="10.10.1.5",
                script=script,
                stdin_input=secret_input,
                document_name="AWS-RunShellScript",
            )
        finally:
            executor.close()

        ssh_args = mock_run.call_args.args[0]
        encoded = ssh_args[-1]
        assert base64.b64decode(encoded).decode() == script
        assert secret_input.strip() not in " ".join(ssh_args)
        assert mock_run.call_args.kwargs["input"].decode("utf-8") == secret_input

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

    def test_probe_ready_captures_failure_detail(self, mocker):
        mock_run = mocker.patch("executors.guest_ssh_executor.subprocess.run")
        mock_run.return_value = MagicMock(returncode=255, stdout=b"", stderr=b"Host key verification failed.\n")
        executor = GuestSSHExecutor(private_key="PRIVATE KEY", username="ubuntu")
        try:
            assert executor._probe_ready("10.10.1.5", "AWS-RunShellScript") is False
            assert "Host key verification failed" in executor._last_probe_detail
            assert "exit=255" in executor._last_probe_detail
        finally:
            executor.close()

    def test_wait_for_ready_timeout_includes_probe_detail(self, mocker):
        mocker.patch("time.sleep")
        mocker.patch("time.time", side_effect=[0.0, 0.0, 100.0])
        mock_run = mocker.patch("executors.guest_ssh_executor.subprocess.run")
        mock_run.return_value = MagicMock(returncode=255, stdout=b"", stderr=b"Host key verification failed.\n")
        executor = GuestSSHExecutor(private_key="PRIVATE KEY", username="ubuntu", poll_interval_seconds=0)
        try:
            with pytest.raises(TimeoutError, match="Host key verification failed"):
                executor.wait_for_ready("10.10.1.5", timeout_seconds=30)
        finally:
            executor.close()

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


class TestGuestSSHExecutorProbeBranches:
    """Cover the probe success/exception branches and OSError mapping."""

    def test_probe_ready_returns_true_on_ready_output(self, mocker):
        mock_run = mocker.patch("executors.guest_ssh_executor.subprocess.run")
        mock_run.return_value = MagicMock(returncode=0, stdout=b"ready\n", stderr=b"")
        executor = GuestSSHExecutor(private_key="PRIVATE KEY", username="ubuntu")
        try:
            assert executor._probe_ready("10.10.1.5", "AWS-RunShellScript") is True
            assert executor._last_probe_detail == ""
        finally:
            executor.close()

    def test_probe_ready_captures_connection_error_detail(self, mocker):
        executor = GuestSSHExecutor(private_key="PRIVATE KEY", username="ubuntu")
        mocker.patch.object(executor, "run_command", side_effect=GuestSSHConnectionError("connection refused"))
        try:
            assert executor._probe_ready("10.10.1.5", "AWS-RunShellScript") is False
            assert "GuestSSHConnectionError" in executor._last_probe_detail
            assert "connection refused" in executor._last_probe_detail
        finally:
            executor.close()

    def test_os_error_maps_to_connection_error(self, mocker):
        mocker.patch("executors.guest_ssh_executor.subprocess.run", side_effect=OSError("broken pipe"))
        executor = GuestSSHExecutor(private_key="PRIVATE KEY", username="ubuntu")
        try:
            with pytest.raises(GuestSSHConnectionError, match="SSH subprocess failed"):
                executor.run_command(instance_id="10.10.1.5", script="echo ok")
        finally:
            executor.close()
