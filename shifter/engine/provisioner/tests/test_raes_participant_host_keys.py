"""Separate guest-management and participant SSH servers must not share an assumed key."""

from unittest.mock import Mock

import pytest

from executors.base import CommandResult
from raes_participant_host_keys import observe_participant_host_keys
from utils.crypto import generate_ssh_host_keypair


def instance(port=2222):
    return {
        "uuid": "node.host#0",
        "os": "linux",
        "private_ip": "10.9.0.4",
        "participant_access_channels": ["ssh"],
        "host_ssh_port": port,
        "host_public_key": generate_ssh_host_keypair()[1],
    }


def test_separate_participant_server_key_is_observed_over_pinned_management_channel():
    output = instance()
    key = generate_ssh_host_keypair()[1]
    context = Mock()
    context.wait_for_ready.return_value = True
    context.executor.run_command.return_value = CommandResult(True, 0, "127.0.0.1 " + key + "\n", "")
    builder = Mock(return_value=context)
    observe_participant_host_keys([output], execution_builder=builder)
    assert output["participant_ssh_host_public_key"] == key
    assert output["participant_ssh_host_public_key"] != output["host_public_key"]
    builder.assert_called_once_with(output, os_type="linux")
    context.close.assert_called_once()


def test_same_server_reuses_its_already_pinned_host_identity():
    output = instance(port=22)
    builder = Mock()
    observe_participant_host_keys([output], execution_builder=builder)
    assert output["participant_ssh_host_public_key"] == output["host_public_key"]
    builder.assert_not_called()


@pytest.mark.parametrize(
    "result",
    [
        CommandResult(False, 1, "", "private error"),
        CommandResult(True, 0, "", ""),
        CommandResult(True, 0, "127.0.0.1 ssh-ed25519 AAAA", ""),
    ],
)
def test_failed_or_malformed_observation_never_falls_back_to_management_identity(result):
    output = instance()
    context = Mock()
    context.executor.run_command.return_value = result
    with pytest.raises(ValueError):
        observe_participant_host_keys([output], execution_builder=Mock(return_value=context))
    assert "participant_ssh_host_public_key" not in output
    context.close.assert_called_once()
