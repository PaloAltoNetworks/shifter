"""Tests for SSHExecutor host-key handling."""

import logging
from unittest.mock import MagicMock, PropertyMock

import paramiko

from executors.ssh_executor import SSHExecutor


def test_create_client_enforces_host_key_verification(mocker):
    """SSHExecutor should reject hosts missing from configured known_hosts."""
    fake_client = MagicMock()
    mocker.patch("executors.ssh_executor.paramiko.SSHClient", return_value=fake_client)

    executor = SSHExecutor.__new__(SSHExecutor)
    client = executor._create_client()

    assert client is fake_client
    fake_client.load_system_host_keys.assert_called_once_with()
    fake_client.set_missing_host_key_policy.assert_called_once()
    policy = fake_client.set_missing_host_key_policy.call_args.args[0]
    assert isinstance(policy, paramiko.RejectPolicy)


def test_run_command_does_not_log_secret_text(mocker, caplog):
    """Command text and device output containing secrets must not appear in logs.

    SSHExecutor mirrors NGFWExecutor's discipline: only byte counts are logged,
    never the raw command string or device output (PAN-OS commands the provisioner
    constructs can include passwords; device output echoes them back).
    """
    secret = "SuperSecretP@ss1234!"

    # Fake channel: delivers one secret-bearing chunk then signals EOF.
    # recv_ready() → True once (chunk delivered), then False.
    # recv(4096) → secret bytes from _read_until_eof, then b"" from _drain_channel.
    # eof_received → False first pass, True second pass.
    # exit_status_ready() → True; recv_exit_status() → 0.
    fake_channel = MagicMock()
    recv_ready_results = [True, False]
    fake_channel.recv_ready.side_effect = lambda: recv_ready_results.pop(0) if recv_ready_results else False
    recv_results = [secret.encode("utf-8"), b""]
    fake_channel.recv.side_effect = lambda n: recv_results.pop(0) if recv_results else b""
    eof_values = [False, True]
    type(fake_channel).eof_received = PropertyMock(side_effect=eof_values)
    fake_channel.exit_status_ready.return_value = True
    fake_channel.recv_exit_status.return_value = 0

    fake_client = MagicMock()
    fake_client.invoke_shell.return_value = fake_channel
    mocker.patch("executors.ssh_executor.paramiko.SSHClient", return_value=fake_client)

    executor = SSHExecutor.__new__(SSHExecutor)
    executor._username = "admin"
    executor._port = 22
    executor._pkey = MagicMock()
    executor._poll_interval = 30

    with caplog.at_level(logging.DEBUG, logger="executors.ssh_executor"):
        result = executor.run_command(
            instance_id="192.168.1.1",
            script=f"set mgt-config users admin password {secret}",
        )

    assert secret not in caplog.text, "Secret must not appear in any log record"
    assert "bytes" in caplog.text, "Byte-count log line must be present"
    assert result.success is True
