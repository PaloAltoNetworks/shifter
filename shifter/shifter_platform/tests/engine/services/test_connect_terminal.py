"""Behavior tests for connect_terminal() in engine/services.

connect_terminal builds an SSHConnection from get_ssh_connection_info. Driven
against a real active ``Range`` (resolved via ``get_active_for_user``) with the
SSH key fetched over the ``boto3`` Secrets Manager boundary, instead of patching
``Range.objects`` / ``get_ssh_key``.
"""

import logging
import uuid

import pytest
from django.contrib.auth import get_user_model

from engine.models import Range

from .conftest import SSH_KEY_PEM, boto3_secrets, make_secrets_client

# Opaque #1325 workspace scope binding (ADR-046-R3). These suites do not
# exercise tenancy; a fixed scalar stands in for the value the CMS launch
# facade resolves in production.
_WORKSPACE_ID = 1

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
    return Range.objects.create(workspace_id=_WORKSPACE_ID, user=user, status=status, provisioned_instances=[instance])


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
            workspace_id=_WORKSPACE_ID,
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
            gcp_host_public_key="ssh-ed25519 AAAATESTHOSTKEY shifter",
            provider_metadata={"gcp": {"vm_name": "vmrt-vm-1", "namespace": "range-42"}},
        )
        _active_range(user, instance)
        with boto3_secrets(make_secrets_client()):
            result = connect_terminal(user, "gcp-instance-uuid-123")
        assert result.host == "10.200.0.110"
        assert result.username == "ubuntu"
        assert result.private_key == SSH_KEY_PEM
        assert result.host_public_key == "ssh-ed25519 AAAATESTHOSTKEY shifter"


class TestConnectTerminalFactoryInjection:
    """The injected ``connection_factory`` seam (issue #993).

    A caller may substitute the SSH transport with a fake without patching
    ``engine.ssh`` or bypassing ownership/READY/channel authorization. The
    factory receives the already-authorized connection facts and returns a
    ``TerminalConnection``. Production defaults to a real ``SSHConnection``.
    """

    def test_uses_injected_factory_with_authorized_facts(self, settings, user):
        from engine import connect_terminal

        settings.CLOUD_PROVIDER = "aws"
        _active_range(user, _instance("fact-uuid", os_type="ubuntu", private_ip="10.1.1.77"))
        captured: dict[str, object] = {}
        sentinel = object()

        def fake_factory(**kwargs):
            captured.update(kwargs)
            return sentinel

        with boto3_secrets(make_secrets_client()):
            result = connect_terminal(user, "fact-uuid", connection_factory=fake_factory)

        assert result is sentinel
        assert captured["host"] == "10.1.1.77"
        assert captured["username"] == "ubuntu"
        assert captured["private_key"] == SSH_KEY_PEM
        assert captured["port"] == 22
        assert captured["session_id"] == "fact-uuid"

    def test_default_factory_builds_real_ssh_connection(self, settings, user):
        from engine import connect_terminal
        from engine.ssh import SSHConnection

        settings.CLOUD_PROVIDER = "aws"
        _active_range(user, _instance("default-uuid", os_type="ubuntu"))
        with boto3_secrets(make_secrets_client()):
            result = connect_terminal(user, "default-uuid")
        assert isinstance(result, SSHConnection)

    def test_factory_not_invoked_when_authorization_fails(self, user):
        from engine import connect_terminal

        called = False

        def fake_factory(**_kwargs):
            nonlocal called
            called = True
            return object()

        with pytest.raises(ValueError, match="No active range"):
            connect_terminal(user, "missing-uuid", connection_factory=fake_factory)
        assert called is False


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


class TestGetOwnedInstanceRequestRef:
    """Ownership resolution for realized range instances (issue #1978).

    ``get_owned_instance_request_ref`` is the engine seam CMS uses to resolve a
    range instance's owning request ref; it returns the request's ``request_id``
    UUID only for an instance the user actually owns.
    """

    def test_returns_the_owning_request_ref(self, user):
        from engine.models import Instance, Request
        from engine.services import get_owned_instance_request_ref

        request = Request.objects.create(request_id=uuid.uuid4(), request_type="range", user=user)
        instance = Instance.objects.create(uuid=str(uuid.uuid4()), request=request, role="attacker", status="ready")

        assert get_owned_instance_request_ref(user, instance.uuid) == str(request.request_id)

    def test_none_for_an_instance_owned_by_another_user(self, user):
        from engine.models import Instance, Request
        from engine.services import get_owned_instance_request_ref

        request = Request.objects.create(request_id=uuid.uuid4(), request_type="range", user=user)
        instance = Instance.objects.create(uuid=str(uuid.uuid4()), request=request, role="attacker", status="ready")
        stranger = User.objects.create_user(username="ref-stranger@example.com", email="ref-stranger@example.com")

        assert get_owned_instance_request_ref(stranger, instance.uuid) is None

    def test_none_when_user_is_unsaved_or_uuid_is_empty(self, user):
        """The guard returns None before any query for a null user id or empty uuid."""
        from django.contrib.auth import get_user_model

        from engine.services import get_owned_instance_request_ref

        assert get_owned_instance_request_ref(get_user_model()(), "some-uuid") is None
        assert get_owned_instance_request_ref(user, "") is None
