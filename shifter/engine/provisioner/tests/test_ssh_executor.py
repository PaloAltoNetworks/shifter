"""Tests for SSHExecutor host-key handling."""

from unittest.mock import MagicMock

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
