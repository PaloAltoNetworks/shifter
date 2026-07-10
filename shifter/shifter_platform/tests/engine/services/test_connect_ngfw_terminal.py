"""Behavior tests for connect_ngfw_terminal() in engine/services.

Driven against real ``Instance`` / ``Request`` rows (the service resolves the
NGFW via the normal ``Instance.objects.select_related("request").get`` query)
with the SSH-key secret fetched over the ``boto3`` Secrets Manager boundary,
instead of patching ``Instance.objects`` / ``get_ssh_key``.
"""

import logging
from uuid import uuid4

import pytest
from botocore.exceptions import ClientError
from django.contrib.auth import get_user_model

from engine.models import Instance, Request
from shared.enums import RequestType, ResourceStatus

from .conftest import boto3_secrets, make_secrets_client

pytestmark = pytest.mark.django_db

User = get_user_model()

AWS_STATE = {
    "management_ip": "10.1.5.10",
    "ssh_key_secret_arn": "arn:aws:secretsmanager:us-east-2:123:secret:key",
}


@pytest.fixture
def user(db):
    return User.objects.create_user(username="engine-ngfwterm@example.com", email="engine-ngfwterm@example.com")


def _ngfw(user, *, status=ResourceStatus.READY.value, state=None, owner=None, with_request=True):
    request = None
    if with_request:
        request = Request.objects.create(request_id=uuid4(), request_type=RequestType.NGFW.value, user=owner or user)
    return Instance.objects.create(
        uuid=uuid4(),
        request=request,
        role=Instance.Role.NGFW,
        os_type=Instance.OSType.PANOS,
        status=status,
        state=AWS_STATE if state is None else state,
    )


class TestConnectNGFWTerminalOutputs:
    def test_returns_ssh_connection_for_ready_ngfw(self, settings, user):
        from engine import connect_ngfw_terminal
        from engine.ssh import SSHConnection

        settings.CLOUD_PROVIDER = "aws"
        ngfw = _ngfw(user)
        with boto3_secrets(make_secrets_client()):
            result = connect_ngfw_terminal(user, str(ngfw.uuid))

        assert isinstance(result, SSHConnection)
        assert result.host == "10.1.5.10"
        assert result.username == "admin"
        assert result.port == 22
        assert result.session_id is None  # PAN-OS doesn't support tmux

    def test_resolves_gcp_ngfw_management_state_from_provider_metadata(self, settings, user):
        from engine import connect_ngfw_terminal

        settings.CLOUD_PROVIDER = "aws"  # active store is the portal's AWS store
        ref = "projects/test/secrets/ngfw-admin"
        ngfw = _ngfw(
            user,
            state={
                "cloud_provider": "gcp",
                "provider_metadata": {"gcp": {"management_ip": "10.200.0.10", "ssh_key_secret_id": ref}},
            },
        )
        client = make_secrets_client()
        with boto3_secrets(client):
            result = connect_ngfw_terminal(user, str(ngfw.uuid))

        client.get_secret_value.assert_called_once_with(SecretId=ref)
        assert result.host == "10.200.0.10"


class TestConnectNGFWTerminalInputValidation:
    def test_does_not_modify_instance(self, settings, user):
        from engine import connect_ngfw_terminal

        settings.CLOUD_PROVIDER = "aws"
        ngfw = _ngfw(user)
        with boto3_secrets(make_secrets_client()):
            connect_ngfw_terminal(user, str(ngfw.uuid))
        before = ngfw.updated_at
        ngfw.refresh_from_db()
        assert ngfw.updated_at == before  # no save() occurred

    def test_requires_user_argument(self):
        from engine import connect_ngfw_terminal

        with pytest.raises(TypeError):
            connect_ngfw_terminal(ngfw_uuid="uuid-123")

    def test_raises_on_none_user(self):
        from engine import connect_ngfw_terminal

        with pytest.raises(ValueError, match="user is required"):
            connect_ngfw_terminal(None, "uuid-123")

    def test_raises_on_none_ngfw_uuid(self, user):
        from engine import connect_ngfw_terminal

        with pytest.raises(ValueError, match="ngfw_uuid is required"):
            connect_ngfw_terminal(user, None)

    def test_raises_on_empty_ngfw_uuid(self, user):
        from engine import connect_ngfw_terminal

        with pytest.raises(ValueError, match="ngfw_uuid is required"):
            connect_ngfw_terminal(user, "")


class TestConnectNGFWTerminalAuthorizationErrors:
    def test_raises_when_ngfw_not_found(self, user):
        from engine import connect_ngfw_terminal

        with pytest.raises(ValueError, match=r"NGFW instance.*not found"):
            connect_ngfw_terminal(user, str(uuid4()))

    def test_raises_when_ngfw_has_no_request(self, user):
        from engine import connect_ngfw_terminal

        ngfw = _ngfw(user, with_request=False)
        with pytest.raises(ValueError, match=r"has no associated request"):
            connect_ngfw_terminal(user, str(ngfw.uuid))

    def test_raises_permission_error_for_non_owner(self, user, django_user_model):
        from engine import connect_ngfw_terminal

        other = django_user_model.objects.create_user(username="ngfw-other@e.com", email="ngfw-other@e.com")
        ngfw = _ngfw(user, owner=other)
        with pytest.raises(PermissionError, match=r"do not have permission"):
            connect_ngfw_terminal(user, str(ngfw.uuid))


class TestConnectNGFWTerminalStateErrors:
    @pytest.mark.parametrize(
        "status",
        [ResourceStatus.PROVISIONING.value, ResourceStatus.FAILED.value, ResourceStatus.PAUSED.value],
    )
    def test_raises_when_ngfw_not_ready(self, user, status):
        from engine import connect_ngfw_terminal

        ngfw = _ngfw(user, status=status)
        with pytest.raises(ValueError, match=r"not accessible"):
            connect_ngfw_terminal(user, str(ngfw.uuid))

    def test_raises_when_no_state(self, user):
        from engine import connect_ngfw_terminal

        ngfw = _ngfw(user, state={})
        with pytest.raises(ValueError, match=r"no infrastructure state"):
            connect_ngfw_terminal(user, str(ngfw.uuid))

    def test_raises_when_no_management_ip(self, user):
        from engine import connect_ngfw_terminal

        ngfw = _ngfw(user, state={"ssh_key_secret_arn": "arn:aws:secretsmanager:us-east-2:123:secret:key"})
        with pytest.raises(ValueError, match=r"no management IP"):
            connect_ngfw_terminal(user, str(ngfw.uuid))

    def test_raises_when_no_ssh_key_arn(self, user):
        from engine import connect_ngfw_terminal

        ngfw = _ngfw(user, state={"management_ip": "10.1.5.10"})
        with pytest.raises(ValueError, match=r"no SSH key"):
            connect_ngfw_terminal(user, str(ngfw.uuid))

    def test_raises_when_secrets_manager_fails(self, settings, user):
        from engine import connect_ngfw_terminal
        from engine.secrets import SecretsError

        settings.CLOUD_PROVIDER = "aws"
        ngfw = _ngfw(user)
        client = make_secrets_client()
        client.get_secret_value.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "Secrets Manager error"}}, "GetSecretValue"
        )
        with boto3_secrets(client), pytest.raises(SecretsError):
            connect_ngfw_terminal(user, str(ngfw.uuid))


class TestConnectNGFWTerminalLogging:
    def test_logs_debug_on_entry(self, settings, user, caplog):
        from engine import connect_ngfw_terminal

        settings.CLOUD_PROVIDER = "aws"
        ngfw = _ngfw(user)
        with boto3_secrets(make_secrets_client()), caplog.at_level(logging.DEBUG, logger="engine"):
            connect_ngfw_terminal(user, str(ngfw.uuid))
        assert str(ngfw.uuid) in caplog.text

    def test_logs_info_on_success(self, settings, user, caplog):
        from engine import connect_ngfw_terminal

        settings.CLOUD_PROVIDER = "aws"
        ngfw = _ngfw(user)
        with boto3_secrets(make_secrets_client()), caplog.at_level(logging.INFO, logger="engine"):
            connect_ngfw_terminal(user, str(ngfw.uuid))
        assert "Creating SSH connection" in caplog.text or str(ngfw.uuid) in caplog.text

    def test_logs_error_when_ngfw_not_found(self, user, caplog):
        from engine import connect_ngfw_terminal

        with caplog.at_level(logging.ERROR, logger="engine"), pytest.raises(ValueError):
            connect_ngfw_terminal(user, str(uuid4()))
        assert "error" in caplog.text.lower() or "not found" in caplog.text.lower()

    def test_logs_error_when_permission_denied(self, user, django_user_model, caplog):
        from engine import connect_ngfw_terminal

        other = django_user_model.objects.create_user(username="ngfw-other2@e.com", email="ngfw-other2@e.com")
        ngfw = _ngfw(user, owner=other)
        with caplog.at_level(logging.ERROR, logger="engine"), pytest.raises(PermissionError):
            connect_ngfw_terminal(user, str(ngfw.uuid))
        assert "permission" in caplog.text.lower() or "does not own" in caplog.text.lower()

    def test_logs_error_when_ngfw_not_accessible(self, user, caplog):
        from engine import connect_ngfw_terminal

        ngfw = _ngfw(user, status=ResourceStatus.PROVISIONING.value)
        with caplog.at_level(logging.ERROR, logger="engine"), pytest.raises(ValueError):
            connect_ngfw_terminal(user, str(ngfw.uuid))
        assert "error" in caplog.text.lower() or "not accessible" in caplog.text.lower()
