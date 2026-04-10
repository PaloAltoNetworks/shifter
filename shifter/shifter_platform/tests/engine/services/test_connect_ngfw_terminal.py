"""Tests for connect_ngfw_terminal() in engine/services.py."""

import logging
from unittest.mock import Mock, patch

import pytest

from shared.enums import ResourceStatus


class TestConnectNGFWTerminal:
    """Tests for connect_ngfw_terminal() in engine/services.py.

    Tests the service contract:
    - Inputs: user (required), ngfw_uuid (required string)
    - Outputs: SSHConnection for the NGFW management interface
    - Side effects: none (read-only operation)
    - Errors: validates inputs, ownership, status, state fields
    - Logging: DEBUG/INFO on success, ERROR on failures

    The function looks up NGFW Instance by UUID and validates ownership via
    Instance → Request → User chain.
    """

    # -------------------------------------------------------------------------
    # Outputs - returns SSHConnection
    # -------------------------------------------------------------------------

    def test_returns_ssh_connection_for_ready_ngfw(self):
        """Service returns SSHConnection for NGFW in ready status."""
        from engine import connect_ngfw_terminal
        from engine.models import Instance, Request
        from engine.ssh import SSHConnection

        mock_user = Mock(id=1)
        mock_request = Mock(spec=Request, user=mock_user)

        mock_ngfw = Mock(
            spec=Instance,
            uuid="ngfw-uuid-123",
            role=Instance.Role.NGFW,
            status=ResourceStatus.READY.value,
            state={
                "management_ip": "10.1.5.10",
                "ssh_key_secret_arn": "arn:aws:secretsmanager:us-east-2:123:secret:key",
            },
        )
        mock_ngfw.request = mock_request

        mock_queryset = Mock()
        mock_queryset.get = Mock(return_value=mock_ngfw)

        ssh_key = "fake-ssh-key-for-testing"
        with (
            patch.object(Instance.objects, "select_related", return_value=mock_queryset),
            patch("engine.secrets.get_ssh_key", return_value=ssh_key),
        ):
            result = connect_ngfw_terminal(mock_user, "ngfw-uuid-123")
            assert isinstance(result, SSHConnection)
            assert result.host == "10.1.5.10"
            assert result.username == "admin"
            assert result.port == 22
            assert result.session_id is None  # PAN-OS doesn't support tmux

    def test_resolves_gcp_ngfw_management_state_from_provider_metadata(self):
        """Service resolves management IP and secret ref from provider metadata."""
        from engine import connect_ngfw_terminal
        from engine.models import Instance, Request

        mock_user = Mock(id=1)
        mock_request = Mock(spec=Request, user=mock_user)

        mock_ngfw = Mock(
            spec=Instance,
            uuid="ngfw-uuid-123",
            role=Instance.Role.NGFW,
            status=ResourceStatus.READY.value,
            state={
                "cloud_provider": "gcp",
                "provider_metadata": {
                    "gcp": {
                        "management_ip": "10.200.0.10",
                        "ssh_key_secret_id": "projects/test/secrets/ngfw-admin",
                    }
                },
            },
        )
        mock_ngfw.request = mock_request

        mock_queryset = Mock()
        mock_queryset.get = Mock(return_value=mock_ngfw)

        with (
            patch.object(Instance.objects, "select_related", return_value=mock_queryset),
            patch("engine.secrets.get_ssh_key", return_value="fake-ssh-key-for-testing") as mock_get_key,
        ):
            result = connect_ngfw_terminal(mock_user, "ngfw-uuid-123")

        mock_get_key.assert_called_once_with("projects/test/secrets/ngfw-admin")
        assert result.host == "10.200.0.10"

    # -------------------------------------------------------------------------
    # Side effects - none expected (read-only)
    # -------------------------------------------------------------------------

    def test_does_not_modify_instance(self):
        """Service does not modify the Instance object."""
        from engine import connect_ngfw_terminal
        from engine.models import Instance, Request

        mock_user = Mock(id=1)
        mock_request = Mock(spec=Request, user=mock_user)

        mock_ngfw = Mock(
            spec=Instance,
            uuid="ngfw-uuid-123",
            role=Instance.Role.NGFW,
            status=ResourceStatus.READY.value,
            state={
                "management_ip": "10.1.5.10",
                "ssh_key_secret_arn": "arn:aws:secretsmanager:us-east-2:123:secret:key",
            },
        )
        mock_ngfw.request = mock_request

        mock_queryset = Mock()
        mock_queryset.get = Mock(return_value=mock_ngfw)

        ssh_key = "fake-ssh-key-for-testing"
        with (
            patch.object(Instance.objects, "select_related", return_value=mock_queryset),
            patch("engine.secrets.get_ssh_key", return_value=ssh_key),
        ):
            connect_ngfw_terminal(mock_user, "ngfw-uuid-123")
            mock_ngfw.save.assert_not_called()

    # -------------------------------------------------------------------------
    # Input validation - user parameter
    # -------------------------------------------------------------------------

    def test_requires_user_argument(self):
        """Service raises TypeError if user not provided."""
        from engine import connect_ngfw_terminal

        with pytest.raises(TypeError):
            connect_ngfw_terminal(ngfw_uuid="uuid-123")

    def test_raises_on_none_user(self):
        """Service raises ValueError if user is None."""
        from engine import connect_ngfw_terminal

        with pytest.raises(ValueError, match="user is required"):
            connect_ngfw_terminal(None, "uuid-123")

    # -------------------------------------------------------------------------
    # Input validation - ngfw_uuid parameter
    # -------------------------------------------------------------------------

    def test_raises_on_none_ngfw_uuid(self):
        """Service raises ValueError if ngfw_uuid is None."""
        from engine import connect_ngfw_terminal

        mock_user = Mock(id=1)

        with pytest.raises(ValueError, match="ngfw_uuid is required"):
            connect_ngfw_terminal(mock_user, None)

    def test_raises_on_empty_ngfw_uuid(self):
        """Service raises ValueError if ngfw_uuid is empty string."""
        from engine import connect_ngfw_terminal

        mock_user = Mock(id=1)

        with pytest.raises(ValueError, match="ngfw_uuid is required"):
            connect_ngfw_terminal(mock_user, "")

    # -------------------------------------------------------------------------
    # Error handling - NGFW not found
    # -------------------------------------------------------------------------

    def test_raises_when_ngfw_not_found(self):
        """Service raises ValueError when NGFW instance doesn't exist."""
        from engine import connect_ngfw_terminal
        from engine.models import Instance

        mock_user = Mock(id=1)

        mock_queryset = Mock()
        mock_queryset.get = Mock(side_effect=Instance.DoesNotExist)

        with (
            patch.object(Instance.objects, "select_related", return_value=mock_queryset),
            pytest.raises(ValueError, match=r"NGFW instance.*not found"),
        ):
            connect_ngfw_terminal(mock_user, "non-existent-uuid")

    # -------------------------------------------------------------------------
    # Authorization - user ownership
    # -------------------------------------------------------------------------

    def test_raises_when_ngfw_has_no_request(self):
        """Service raises ValueError when NGFW instance has no associated request."""
        from engine import connect_ngfw_terminal
        from engine.models import Instance

        mock_user = Mock(id=1)

        mock_ngfw = Mock(
            spec=Instance,
            uuid="ngfw-uuid-123",
            role=Instance.Role.NGFW,
            status=ResourceStatus.READY.value,
            state={
                "management_ip": "10.1.5.10",
                "ssh_key_secret_arn": "arn:aws:secretsmanager:us-east-2:123:secret:key",
            },
        )
        mock_ngfw.request = None  # No associated request

        mock_queryset = Mock()
        mock_queryset.get = Mock(return_value=mock_ngfw)

        with (
            patch.object(Instance.objects, "select_related", return_value=mock_queryset),
            pytest.raises(ValueError, match=r"has no associated request"),
        ):
            connect_ngfw_terminal(mock_user, "ngfw-uuid-123")

    def test_raises_permission_error_for_non_owner(self):
        """Service raises PermissionError when user doesn't own the NGFW."""
        from engine import connect_ngfw_terminal
        from engine.models import Instance, Request

        mock_user = Mock(id=1)
        mock_other_user = Mock(id=2)
        mock_request = Mock(spec=Request, user=mock_other_user)

        mock_ngfw = Mock(
            spec=Instance,
            uuid="ngfw-uuid-123",
            role=Instance.Role.NGFW,
            status=ResourceStatus.READY.value,
            state={
                "management_ip": "10.1.5.10",
                "ssh_key_secret_arn": "arn:aws:secretsmanager:us-east-2:123:secret:key",
            },
        )
        mock_ngfw.request = mock_request

        mock_queryset = Mock()
        mock_queryset.get = Mock(return_value=mock_ngfw)

        with (
            patch.object(Instance.objects, "select_related", return_value=mock_queryset),
            pytest.raises(PermissionError, match=r"do not have permission"),
        ):
            connect_ngfw_terminal(mock_user, "ngfw-uuid-123")

    # -------------------------------------------------------------------------
    # Status validation - must be ready
    # -------------------------------------------------------------------------

    def test_raises_when_ngfw_provisioning(self):
        """Service raises ValueError when NGFW is PROVISIONING."""
        from engine import connect_ngfw_terminal
        from engine.models import Instance, Request

        mock_user = Mock(id=1)
        mock_request = Mock(spec=Request, user=mock_user)

        mock_ngfw = Mock(
            spec=Instance,
            uuid="ngfw-uuid-123",
            role=Instance.Role.NGFW,
            status=ResourceStatus.PROVISIONING.value,
            state={
                "management_ip": "10.1.5.10",
                "ssh_key_secret_arn": "arn:aws:secretsmanager:us-east-2:123:secret:key",
            },
        )
        mock_ngfw.request = mock_request

        mock_queryset = Mock()
        mock_queryset.get = Mock(return_value=mock_ngfw)

        with (
            patch.object(Instance.objects, "select_related", return_value=mock_queryset),
            pytest.raises(ValueError, match=r"not accessible"),
        ):
            connect_ngfw_terminal(mock_user, "ngfw-uuid-123")

    def test_raises_when_ngfw_failed(self):
        """Service raises ValueError when NGFW is FAILED."""
        from engine import connect_ngfw_terminal
        from engine.models import Instance, Request

        mock_user = Mock(id=1)
        mock_request = Mock(spec=Request, user=mock_user)

        mock_ngfw = Mock(
            spec=Instance,
            uuid="ngfw-uuid-123",
            role=Instance.Role.NGFW,
            status=ResourceStatus.FAILED.value,
            state={
                "management_ip": "10.1.5.10",
                "ssh_key_secret_arn": "arn:aws:secretsmanager:us-east-2:123:secret:key",
            },
        )
        mock_ngfw.request = mock_request

        mock_queryset = Mock()
        mock_queryset.get = Mock(return_value=mock_ngfw)

        with (
            patch.object(Instance.objects, "select_related", return_value=mock_queryset),
            pytest.raises(ValueError, match=r"not accessible"),
        ):
            connect_ngfw_terminal(mock_user, "ngfw-uuid-123")

    def test_raises_when_ngfw_paused(self):
        """Service raises ValueError when NGFW is PAUSED."""
        from engine import connect_ngfw_terminal
        from engine.models import Instance, Request

        mock_user = Mock(id=1)
        mock_request = Mock(spec=Request, user=mock_user)

        mock_ngfw = Mock(
            spec=Instance,
            uuid="ngfw-uuid-123",
            role=Instance.Role.NGFW,
            status=ResourceStatus.PAUSED.value,
            state={
                "management_ip": "10.1.5.10",
                "ssh_key_secret_arn": "arn:aws:secretsmanager:us-east-2:123:secret:key",
            },
        )
        mock_ngfw.request = mock_request

        mock_queryset = Mock()
        mock_queryset.get = Mock(return_value=mock_ngfw)

        with (
            patch.object(Instance.objects, "select_related", return_value=mock_queryset),
            pytest.raises(ValueError, match=r"not accessible"),
        ):
            connect_ngfw_terminal(mock_user, "ngfw-uuid-123")

    # -------------------------------------------------------------------------
    # State validation - required fields
    # -------------------------------------------------------------------------

    def test_raises_when_no_state(self):
        """Service raises ValueError when NGFW has no state."""
        from engine import connect_ngfw_terminal
        from engine.models import Instance, Request

        mock_user = Mock(id=1)
        mock_request = Mock(spec=Request, user=mock_user)

        mock_ngfw = Mock(
            spec=Instance,
            uuid="ngfw-uuid-123",
            role=Instance.Role.NGFW,
            status=ResourceStatus.READY.value,
            state=None,
        )
        mock_ngfw.request = mock_request

        mock_queryset = Mock()
        mock_queryset.get = Mock(return_value=mock_ngfw)

        with (
            patch.object(Instance.objects, "select_related", return_value=mock_queryset),
            pytest.raises(ValueError, match=r"no infrastructure state"),
        ):
            connect_ngfw_terminal(mock_user, "ngfw-uuid-123")

    def test_raises_when_no_management_ip(self):
        """Service raises ValueError when state lacks management_ip."""
        from engine import connect_ngfw_terminal
        from engine.models import Instance, Request

        mock_user = Mock(id=1)
        mock_request = Mock(spec=Request, user=mock_user)

        mock_ngfw = Mock(
            spec=Instance,
            uuid="ngfw-uuid-123",
            role=Instance.Role.NGFW,
            status=ResourceStatus.READY.value,
            state={
                "ssh_key_secret_arn": "arn:aws:secretsmanager:us-east-2:123:secret:key",
                # management_ip intentionally missing
            },
        )
        mock_ngfw.request = mock_request

        mock_queryset = Mock()
        mock_queryset.get = Mock(return_value=mock_ngfw)

        with (
            patch.object(Instance.objects, "select_related", return_value=mock_queryset),
            pytest.raises(ValueError, match=r"no management IP"),
        ):
            connect_ngfw_terminal(mock_user, "ngfw-uuid-123")

    def test_raises_when_no_ssh_key_arn(self):
        """Service raises ValueError when state lacks ssh_key_secret_arn."""
        from engine import connect_ngfw_terminal
        from engine.models import Instance, Request

        mock_user = Mock(id=1)
        mock_request = Mock(spec=Request, user=mock_user)

        mock_ngfw = Mock(
            spec=Instance,
            uuid="ngfw-uuid-123",
            role=Instance.Role.NGFW,
            status=ResourceStatus.READY.value,
            state={
                "management_ip": "10.1.5.10",
                # ssh_key_secret_arn intentionally missing
            },
        )
        mock_ngfw.request = mock_request

        mock_queryset = Mock()
        mock_queryset.get = Mock(return_value=mock_ngfw)

        with (
            patch.object(Instance.objects, "select_related", return_value=mock_queryset),
            pytest.raises(ValueError, match=r"no SSH key"),
        ):
            connect_ngfw_terminal(mock_user, "ngfw-uuid-123")

    # -------------------------------------------------------------------------
    # Error handling - secrets manager failures
    # -------------------------------------------------------------------------

    def test_raises_when_secrets_manager_fails(self):
        """Service raises error when SSH key retrieval fails."""
        from engine import connect_ngfw_terminal
        from engine.models import Instance, Request

        mock_user = Mock(id=1)
        mock_request = Mock(spec=Request, user=mock_user)

        mock_ngfw = Mock(
            spec=Instance,
            uuid="ngfw-uuid-123",
            role=Instance.Role.NGFW,
            status=ResourceStatus.READY.value,
            state={
                "management_ip": "10.1.5.10",
                "ssh_key_secret_arn": "arn:aws:secretsmanager:us-east-2:123:secret:key",
            },
        )
        mock_ngfw.request = mock_request

        mock_queryset = Mock()
        mock_queryset.get = Mock(return_value=mock_ngfw)

        with (
            patch.object(Instance.objects, "select_related", return_value=mock_queryset),
            patch("engine.secrets.get_ssh_key", side_effect=Exception("Secrets Manager error")),
            pytest.raises(Exception, match="Secrets Manager error"),
        ):
            connect_ngfw_terminal(mock_user, "ngfw-uuid-123")

    # -------------------------------------------------------------------------
    # Logging - DEBUG/INFO on success
    # -------------------------------------------------------------------------

    def test_logs_debug_on_entry(self, caplog):
        """Service logs debug on entry with user_id and ngfw_uuid."""
        from engine import connect_ngfw_terminal
        from engine.models import Instance, Request

        mock_user = Mock(id=1)
        mock_request = Mock(spec=Request, user=mock_user)

        mock_ngfw = Mock(
            spec=Instance,
            uuid="ngfw-uuid-123",
            role=Instance.Role.NGFW,
            status=ResourceStatus.READY.value,
            state={
                "management_ip": "10.1.5.10",
                "ssh_key_secret_arn": "arn:aws:secretsmanager:us-east-2:123:secret:key",
            },
        )
        mock_ngfw.request = mock_request

        mock_queryset = Mock()
        mock_queryset.get = Mock(return_value=mock_ngfw)

        ssh_key = "fake-ssh-key-for-testing"
        with (
            patch.object(Instance.objects, "select_related", return_value=mock_queryset),
            patch("engine.secrets.get_ssh_key", return_value=ssh_key),
            caplog.at_level(logging.DEBUG, logger="engine"),
        ):
            connect_ngfw_terminal(mock_user, "ngfw-uuid-123")

        assert "ngfw-uuid-123" in caplog.text

    def test_logs_info_on_success(self, caplog):
        """Service logs info when successfully creating SSH connection."""
        from engine import connect_ngfw_terminal
        from engine.models import Instance, Request

        mock_user = Mock(id=1)
        mock_request = Mock(spec=Request, user=mock_user)

        mock_ngfw = Mock(
            spec=Instance,
            uuid="ngfw-uuid-456",
            role=Instance.Role.NGFW,
            status=ResourceStatus.READY.value,
            state={
                "management_ip": "10.1.5.20",
                "ssh_key_secret_arn": "arn:aws:secretsmanager:us-east-2:123:secret:key",
            },
        )
        mock_ngfw.request = mock_request

        mock_queryset = Mock()
        mock_queryset.get = Mock(return_value=mock_ngfw)

        ssh_key = "fake-ssh-key-for-testing"
        with (
            patch.object(Instance.objects, "select_related", return_value=mock_queryset),
            patch("engine.secrets.get_ssh_key", return_value=ssh_key),
            caplog.at_level(logging.INFO, logger="engine"),
        ):
            connect_ngfw_terminal(mock_user, "ngfw-uuid-456")

        assert "Creating SSH connection" in caplog.text or "ngfw-uuid-456" in caplog.text

    # -------------------------------------------------------------------------
    # Logging - ERROR on failures
    # -------------------------------------------------------------------------

    def test_logs_error_when_ngfw_not_found(self, caplog):
        """Service logs error when NGFW instance not found."""
        from engine import connect_ngfw_terminal
        from engine.models import Instance

        mock_user = Mock(id=1)

        mock_queryset = Mock()
        mock_queryset.get = Mock(side_effect=Instance.DoesNotExist)

        with (
            patch.object(Instance.objects, "select_related", return_value=mock_queryset),
            caplog.at_level(logging.ERROR, logger="engine"),
            pytest.raises(ValueError),
        ):
            connect_ngfw_terminal(mock_user, "missing-uuid")

        assert "error" in caplog.text.lower() or "not found" in caplog.text.lower()

    def test_logs_error_when_permission_denied(self, caplog):
        """Service logs error when user doesn't own NGFW."""
        from engine import connect_ngfw_terminal
        from engine.models import Instance, Request

        mock_user = Mock(id=1)
        mock_other_user = Mock(id=2)
        mock_request = Mock(spec=Request, user=mock_other_user)

        mock_ngfw = Mock(
            spec=Instance,
            uuid="ngfw-uuid-123",
            role=Instance.Role.NGFW,
            status=ResourceStatus.READY.value,
            state={
                "management_ip": "10.1.5.10",
                "ssh_key_secret_arn": "arn:aws:secretsmanager:us-east-2:123:secret:key",
            },
        )
        mock_ngfw.request = mock_request

        mock_queryset = Mock()
        mock_queryset.get = Mock(return_value=mock_ngfw)

        with (
            patch.object(Instance.objects, "select_related", return_value=mock_queryset),
            caplog.at_level(logging.ERROR, logger="engine"),
            pytest.raises(PermissionError),
        ):
            connect_ngfw_terminal(mock_user, "ngfw-uuid-123")

        assert "permission" in caplog.text.lower() or "does not own" in caplog.text.lower()

    def test_logs_error_when_ngfw_not_accessible(self, caplog):
        """Service logs error when NGFW is not in accessible state."""
        from engine import connect_ngfw_terminal
        from engine.models import Instance, Request

        mock_user = Mock(id=1)
        mock_request = Mock(spec=Request, user=mock_user)

        mock_ngfw = Mock(
            spec=Instance,
            uuid="ngfw-uuid-123",
            role=Instance.Role.NGFW,
            status=ResourceStatus.PROVISIONING.value,
            state={
                "management_ip": "10.1.5.10",
                "ssh_key_secret_arn": "arn:aws:secretsmanager:us-east-2:123:secret:key",
            },
        )
        mock_ngfw.request = mock_request

        mock_queryset = Mock()
        mock_queryset.get = Mock(return_value=mock_ngfw)

        with (
            patch.object(Instance.objects, "select_related", return_value=mock_queryset),
            caplog.at_level(logging.ERROR, logger="engine"),
            pytest.raises(ValueError),
        ):
            connect_ngfw_terminal(mock_user, "ngfw-uuid-123")

        assert "error" in caplog.text.lower() or "not accessible" in caplog.text.lower()
