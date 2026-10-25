"""Native EC2 guests use pinned private SSH, without a guest SSM identity."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from executors.factory import build_guest_execution_context
from executors.guest_ssh_executor import GuestSSHExecutor


@pytest.fixture(autouse=True)
def no_cloud_clients(mocker):
    # Real transport selection, with the external AWS SDK prevented from discovery.
    return mocker.patch("boto3.Session", return_value=SimpleNamespace(client=lambda _: object()))


def instance(**changes):
    value = {
        "asset_type": "ec2_vm",
        "instance_id": "i-0123456789abcdef0",
        "private_ip": "10.80.2.17",
        "os": "linux",
        "host_ssh_key_secret_ref": "/shifter/test/range/7/node-1-management-key",
        "host_ssh_username": "shifter",
        "host_ssh_port": 2222,
        "host_public_key": "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExampleSyntheticHostKey",
    }
    value.update(changes)
    return value


def test_native_ec2_management_uses_pinned_ssh_and_cleans_temporary_material(monkeypatch, mocker):
    monkeypatch.setenv("CLOUD_PROVIDER", "aws")
    reader = mocker.Mock(return_value="synthetic SSH private material")
    context = build_guest_execution_context(instance(), secret_reader=reader)
    try:
        assert isinstance(context.executor, GuestSSHExecutor)
        assert context.transport_name == "ssh"
        assert context.target == "10.80.2.17"
        assert context.executor._username == "shifter"
        assert context.executor._port == 2222
        known_hosts = Path(context.executor._known_hosts_path)
        key = Path(context.executor._key_path)
        assert known_hosts.read_text() == "[10.80.2.17]:2222 " + instance()["host_public_key"] + "\n"
        assert key.stat().st_mode & 0o777 == 0o600
        reader.assert_called_once_with(instance()["host_ssh_key_secret_ref"])
    finally:
        context.close()
    assert not key.exists() and not known_hosts.exists()


@pytest.mark.parametrize(
    "change",
    [
        {"host_public_key": ""},
        {"host_ssh_key_secret_ref": ""},
        {"host_ssh_username": ""},
        {"private_ip": "169.254.169.254"},
        {"private_ip": "203.0.113.2"},
        {"host_ssh_username": "-oProxyCommand=bad"},
        {"host_ssh_port": True},
        {"host_ssh_port": 0},
        {"host_public_key": "ssh-ed25519 key\nother-host key"},
    ],
)
def test_invalid_native_access_fails_before_secret_lookup_or_ssm_fallback(change, monkeypatch, mocker):
    monkeypatch.setenv("CLOUD_PROVIDER", "aws")
    reader = mocker.Mock()
    with pytest.raises(ValueError):
        build_guest_execution_context(instance(**change), secret_reader=reader)
    reader.assert_not_called()
