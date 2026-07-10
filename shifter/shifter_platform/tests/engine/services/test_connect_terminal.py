"""Behavior tests for connect_terminal() in engine/services.

connect_terminal builds an SSHConnection from get_ssh_connection_info. Driven
against a real active ``Range`` (resolved via ``get_active_for_user``) with the
SSH key fetched over the ``boto3`` Secrets Manager boundary, instead of patching
``Range.objects`` / ``get_ssh_key``.
"""

import logging

import pytest
from django.contrib.auth import get_user_model

from engine.models import Range

from .conftest import SSH_KEY_PEM, boto3_secrets, make_secrets_client

pytestmark = pytest.mark.django_db

User = get_user_model()

SSH_ARN = "arn:aws:secretsmanager:us-east-2:123:secret:key"


@pytest.fixture
def user(db):
    return User.objects.create_user(username="engine-connterm@example.com", email="engine-connterm@example.com")


def _instance(uuid, *, os_type=None, **extra):
    data = {"uuid": uuid, "role": "attacker", "private_ip": "10.1.1.10", "ssh_key_secret_arn": SSH_ARN, **extra}
    if os_type is not None:
        data["os_type"] = os_type
    return data


def _active_range(user, instance, *, status=Range.Status.READY):
    return Range.objects.create(user=user, status=status, provisioned_instances=[instance])


class TestConnectTerminalOutputs:
    def test_returns_ssh_connection(self, settings, user):
        from engine import connect_terminal
        from engine.ssh import SSHConnection

        settings.CLOUD_PROVIDER = "aws"
        _active_range(user, _instance("instance-uuid-123"))
        with boto3_secrets(make_secrets_client()):
            result = connect_terminal(user, "instance-uuid-123")
        assert isinstance(result, SSHConnection)

    def test_resolves_the_requested_instance(self, settings, user):
        from engine import connect_terminal

        settings.CLOUD_PROVIDER = "aws"
        # Two instances in the range; the requested uuid is the one connected to.
        range_obj = Range.objects.create(
            user=user,
            status=Range.Status.READY,
            provisioned_instances=[
                _instance("other-uuid", private_ip="10.9.9.9"),
                _instance("victim-uuid-456", os_type="ubuntu", private_ip="10.1.1.20"),
            ],
        )
        assert range_obj  # sanity
        with boto3_secrets(make_secrets_client()):
            result = connect_terminal(user, "victim-uuid-456")
        assert result.host == "10.1.1.20"

    def test_builds_connection_with_gcp_provider_metadata(self, settings, user):
        from engine import connect_terminal

        settings.CLOUD_PROVIDER = "aws"
        instance = _instance(
            "gcp-instance-uuid-123",
            os_type="ubuntu",
            private_ip="10.200.0.110",
            cloud_provider="gcp",
            provider_metadata={"gcp": {"vm_name": "vmrt-vm-1", "namespace": "range-42"}},
        )
        _active_range(user, instance)
        with boto3_secrets(make_secrets_client()):
            result = connect_terminal(user, "gcp-instance-uuid-123")
        assert result.host == "10.200.0.110"
        assert result.username == "ubuntu"
        assert result.private_key == SSH_KEY_PEM


class TestConnectTerminalInputValidation:
    def test_requires_user_argument(self):
        from engine import connect_terminal

        with pytest.raises(TypeError):
            connect_terminal(instance_uuid="uuid-123")

    def test_raises_on_none_user(self):
        from engine import connect_terminal

        with pytest.raises((TypeError, ValueError)):
            connect_terminal(None, "uuid-123")

    def test_raises_on_none_instance_uuid(self, user):
        from engine import connect_terminal

        with pytest.raises((TypeError, ValueError)):
            connect_terminal(user, None)

    def test_raises_on_empty_instance_uuid(self, user):
        from engine import connect_terminal

        with pytest.raises((TypeError, ValueError)):
            connect_terminal(user, "")


class TestConnectTerminalErrorStates:
    def test_raises_when_no_active_range(self, user):
        from engine import connect_terminal

        with pytest.raises(ValueError, match="No active range"):
            connect_terminal(user, "non-existent-uuid")

    @pytest.mark.parametrize("status", [Range.Status.PROVISIONING, Range.Status.PAUSED])
    def test_raises_when_range_not_ready(self, user, status):
        from engine import connect_terminal

        _active_range(user, _instance("u-1"), status=status)
        with pytest.raises(ValueError, match="not ready"):
            connect_terminal(user, "u-1")

    def test_raises_when_instance_uuid_not_found_in_range(self, user):
        from engine import connect_terminal

        _active_range(user, _instance("present"))
        with pytest.raises(ValueError, match=r"(?i)instance.*not found"):
            connect_terminal(user, "non-existent-uuid")


class TestConnectTerminalLogging:
    def test_logs_debug_on_entry(self, settings, user, caplog):
        from engine import connect_terminal

        settings.CLOUD_PROVIDER = "aws"
        _active_range(user, _instance("instance-uuid-123"))
        with boto3_secrets(make_secrets_client()), caplog.at_level(logging.DEBUG, logger="engine"):
            connect_terminal(user, "instance-uuid-123")
        assert "instance-uuid-123" in caplog.text

    def test_logs_error_when_no_active_range(self, user, caplog):
        from engine import connect_terminal

        with caplog.at_level(logging.ERROR, logger="engine"), pytest.raises(ValueError):
            connect_terminal(user, "missing-uuid")
        assert "error" in caplog.text.lower() or "no active range" in caplog.text.lower()


class TestConnectTerminalUsernameMapping:
    @pytest.mark.parametrize(
        ("os_type", "expected_username"),
        [
            ("kali", "kali"),
            ("ubuntu", "ubuntu"),
            ("amazon-linux", "ec2-user"),
            ("KALI", "kali"),
            ("windows", "Administrator"),
            (None, "ubuntu"),  # default
        ],
    )
    def test_username_for_os_type(self, settings, user, os_type, expected_username):
        from engine import connect_terminal

        settings.CLOUD_PROVIDER = "aws"
        _active_range(user, _instance("os-uuid", os_type=os_type, private_ip="10.1.1.50"))
        with boto3_secrets(make_secrets_client()):
            result = connect_terminal(user, "os-uuid")
        assert result.username == expected_username


class TestConnectTerminalSessionIds:
    @pytest.mark.parametrize("os_type", ["kali", "ubuntu"])
    def test_sets_session_id_for_tmux_capable_instances(self, settings, user, os_type):
        from engine import connect_terminal

        settings.CLOUD_PROVIDER = "aws"
        _active_range(user, _instance("sess-uuid", os_type=os_type))
        with boto3_secrets(make_secrets_client()):
            result = connect_terminal(user, "sess-uuid")
        assert result.session_id == "sess-uuid"

    def test_no_session_id_for_windows_instances(self, settings, user):
        from engine import connect_terminal

        settings.CLOUD_PROVIDER = "aws"
        _active_range(user, _instance("win-uuid", os_type="windows", private_ip="10.1.1.60"))
        with boto3_secrets(make_secrets_client()):
            result = connect_terminal(user, "win-uuid")
        assert result.session_id is None
