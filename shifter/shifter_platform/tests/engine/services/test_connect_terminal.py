"""Tests for connect_terminal() in engine/services.py."""

import logging
from unittest.mock import Mock, patch

import pytest


@pytest.mark.django_db
class TestConnectTerminal:
    """Tests for connect_terminal() in engine/services.py.

    Tests the service contract:
    - Inputs: user (required), range_id (required positive int), instance_uuid (required string)
    - Outputs: SSHConnection for the specified instance
    - Side effects: none (read-only operation)
    - Errors: validates inputs, ownership, range status, instance existence
    - Logging: DEBUG on success, ERROR on failures
    """

    # -------------------------------------------------------------------------
    # Outputs - returns SSHConnection
    # -------------------------------------------------------------------------

    def test_returns_ssh_connection(self):
        """Service returns SSHConnection for valid inputs."""
        from engine import connect_terminal
        from engine.models import Range
        from engine.ssh import SSHConnection

        mock_user = Mock(id=1)
        instance_data = {
            "uuid": "instance-uuid-123",
            "role": "attacker",
            "private_ip": "10.1.1.10",
            "ssh_key_secret_arn": "arn:aws:secretsmanager:us-east-2:123:secret:key",
        }
        mock_range = Mock(spec=Range, id=42, user=mock_user, status=Range.Status.READY)
        mock_range.get_instance_by_uuid = Mock(return_value=instance_data)

        ssh_key = "fake-ssh-key-for-testing"
        with (
            patch.object(Range.objects, "get", return_value=mock_range),
            patch("engine.secrets.get_ssh_key", return_value=ssh_key),
        ):
            result = connect_terminal(mock_user, 42, "instance-uuid-123")
            assert isinstance(result, SSHConnection)

    def test_calls_get_instance_by_uuid_with_uuid(self):
        """Service calls get_instance_by_uuid with the provided UUID."""
        from engine import connect_terminal
        from engine.models import Range
        from engine.ssh import SSHConnection

        mock_user = Mock(id=1)
        instance_data = {
            "uuid": "victim-uuid-456",
            "role": "victim",
            "private_ip": "10.1.1.20",
            "ssh_key_secret_arn": "arn:aws:secretsmanager:us-east-2:123:secret:key",
        }
        mock_range = Mock(spec=Range, id=42, user=mock_user, status=Range.Status.READY)
        mock_range.get_instance_by_uuid = Mock(return_value=instance_data)

        ssh_key = "fake-ssh-key-for-testing"
        with (
            patch.object(Range.objects, "get", return_value=mock_range),
            patch("engine.secrets.get_ssh_key", return_value=ssh_key),
        ):
            result = connect_terminal(mock_user, 42, "victim-uuid-456")
            assert isinstance(result, SSHConnection)
            mock_range.get_instance_by_uuid.assert_called_once_with("victim-uuid-456")

    def test_calls_range_get_with_range_id(self):
        """Service queries Range by id."""
        from engine import connect_terminal
        from engine.models import Range

        mock_user = Mock(id=1)
        instance_data = {
            "uuid": "instance-uuid-123",
            "role": "attacker",
            "private_ip": "10.1.1.10",
            "ssh_key_secret_arn": "arn:aws:secretsmanager:us-east-2:123:secret:key",
        }
        mock_range = Mock(spec=Range, id=42, user=mock_user, status=Range.Status.READY)
        mock_range.get_instance_by_uuid = Mock(return_value=instance_data)

        ssh_key = "fake-ssh-key-for-testing"
        with (
            patch.object(Range.objects, "get", return_value=mock_range) as mock_get,
            patch("engine.secrets.get_ssh_key", return_value=ssh_key),
        ):
            connect_terminal(mock_user, 42, "instance-uuid-123")
            mock_get.assert_called_once_with(id=42)

    # -------------------------------------------------------------------------
    # Side effects - none expected (read-only)
    # -------------------------------------------------------------------------

    def test_does_not_modify_range(self):
        """Service does not modify the Range object."""
        from engine import connect_terminal
        from engine.models import Range

        mock_user = Mock(id=1)
        instance_data = {
            "uuid": "instance-uuid-123",
            "role": "attacker",
            "private_ip": "10.1.1.10",
            "ssh_key_secret_arn": "arn:aws:secretsmanager:us-east-2:123:secret:key",
        }
        mock_range = Mock(spec=Range, id=42, user=mock_user, status=Range.Status.READY)
        mock_range.get_instance_by_uuid = Mock(return_value=instance_data)

        ssh_key = "fake-ssh-key-for-testing"
        with (
            patch.object(Range.objects, "get", return_value=mock_range),
            patch("engine.secrets.get_ssh_key", return_value=ssh_key),
        ):
            connect_terminal(mock_user, 42, "instance-uuid-123")
            mock_range.save.assert_not_called()

    # -------------------------------------------------------------------------
    # Input validation - user parameter
    # -------------------------------------------------------------------------

    def test_requires_user_argument(self):
        """Service raises TypeError if user not provided."""
        from engine import connect_terminal

        with pytest.raises(TypeError):
            connect_terminal(range_id=42, instance_uuid="uuid-123")

    def test_raises_on_none_user(self):
        """Service raises error if user is None."""
        from engine import connect_terminal

        with pytest.raises((TypeError, ValueError)):
            connect_terminal(None, 42, "uuid-123")

    # -------------------------------------------------------------------------
    # Input validation - range_id parameter
    # -------------------------------------------------------------------------

    def test_raises_on_none_range_id(self):
        """Service raises error if range_id is None."""
        from engine import connect_terminal

        mock_user = Mock(id=1)

        with pytest.raises((TypeError, ValueError)):
            connect_terminal(mock_user, None, "uuid-123")

    def test_raises_on_invalid_range_id_type(self):
        """Service raises error if range_id is wrong type."""
        from engine import connect_terminal

        mock_user = Mock(id=1)

        with pytest.raises((TypeError, ValueError)):
            connect_terminal(mock_user, "not-an-id", "uuid-123")

    def test_raises_on_negative_range_id(self):
        """Service raises error if range_id is negative."""
        from engine import connect_terminal

        mock_user = Mock(id=1)

        with pytest.raises((TypeError, ValueError)):
            connect_terminal(mock_user, -1, "uuid-123")

    # -------------------------------------------------------------------------
    # Input validation - instance_uuid parameter
    # -------------------------------------------------------------------------

    def test_raises_on_none_instance_uuid(self):
        """Service raises error if instance_uuid is None."""
        from engine import connect_terminal

        mock_user = Mock(id=1)

        with pytest.raises((TypeError, ValueError)):
            connect_terminal(mock_user, 42, None)

    def test_raises_on_empty_instance_uuid(self):
        """Service raises error if instance_uuid is empty string."""
        from engine import connect_terminal

        mock_user = Mock(id=1)

        with pytest.raises((TypeError, ValueError)):
            connect_terminal(mock_user, 42, "")

    # -------------------------------------------------------------------------
    # Error handling - ownership
    # -------------------------------------------------------------------------

    def test_raises_when_user_does_not_own_range(self):
        """Service raises PermissionError when user doesn't own range."""
        from engine import connect_terminal
        from engine.models import Range

        mock_user = Mock(id=1)
        other_user = Mock(id=999)

        mock_range = Mock(spec=Range, id=42, user=other_user, status=Range.Status.READY)

        with patch.object(Range.objects, "get", return_value=mock_range), pytest.raises(PermissionError):
            connect_terminal(mock_user, 42, "uuid-123")

    # -------------------------------------------------------------------------
    # Error handling - range status
    # -------------------------------------------------------------------------

    def test_raises_when_range_not_ready(self):
        """Service raises ValueError when range is not READY."""
        from engine import connect_terminal
        from engine.models import Range

        mock_user = Mock(id=1)

        mock_range = Mock(spec=Range, id=42, user=mock_user, status=Range.Status.FAILED)

        with patch.object(Range.objects, "get", return_value=mock_range), pytest.raises(ValueError, match="not ready"):
            connect_terminal(mock_user, 42, "uuid-123")

    def test_raises_when_range_provisioning(self):
        """Service raises ValueError when range is PROVISIONING."""
        from engine import connect_terminal
        from engine.models import Range

        mock_user = Mock(id=1)

        mock_range = Mock(spec=Range, id=42, user=mock_user, status=Range.Status.PROVISIONING)

        with patch.object(Range.objects, "get", return_value=mock_range), pytest.raises(ValueError, match="not ready"):
            connect_terminal(mock_user, 42, "uuid-123")

    # -------------------------------------------------------------------------
    # Error handling - instance not found
    # -------------------------------------------------------------------------

    def test_raises_when_instance_uuid_not_found(self):
        """Service raises ValueError when instance UUID doesn't exist in range."""
        from engine import connect_terminal
        from engine.models import Range

        mock_user = Mock(id=1)

        mock_range = Mock(spec=Range, id=42, user=mock_user, status=Range.Status.READY)
        mock_range.get_instance_by_uuid = Mock(return_value=None)

        with (
            patch.object(Range.objects, "get", return_value=mock_range),
            pytest.raises(ValueError, match=r"(?i)instance.*not found"),
        ):
            connect_terminal(mock_user, 42, "non-existent-uuid")

    # -------------------------------------------------------------------------
    # Error propagation
    # -------------------------------------------------------------------------

    def test_propagates_range_does_not_exist(self):
        """Service propagates Range.DoesNotExist."""
        from engine import connect_terminal
        from engine.models import Range

        mock_user = Mock(id=1)

        with patch.object(Range.objects, "get", side_effect=Range.DoesNotExist), pytest.raises(Range.DoesNotExist):
            connect_terminal(mock_user, 42, "uuid-123")

    # -------------------------------------------------------------------------
    # Logging - DEBUG on success
    # -------------------------------------------------------------------------

    def test_logs_debug_on_entry(self, caplog):
        """Service logs debug on entry with range_id and instance_uuid."""
        from engine import connect_terminal
        from engine.models import Range

        mock_user = Mock(id=1)
        instance_data = {
            "uuid": "instance-uuid-123",
            "role": "attacker",
            "private_ip": "10.1.1.10",
            "ssh_key_secret_arn": "arn:aws:secretsmanager:us-east-2:123:secret:key",
        }
        mock_range = Mock(spec=Range, id=42, user=mock_user, status=Range.Status.READY)
        mock_range.get_instance_by_uuid = Mock(return_value=instance_data)

        ssh_key = "fake-ssh-key-for-testing"
        with (
            patch.object(Range.objects, "get", return_value=mock_range),
            patch("engine.secrets.get_ssh_key", return_value=ssh_key),
            caplog.at_level(logging.DEBUG, logger="engine"),
        ):
            connect_terminal(mock_user, 42, "instance-uuid-123")

        assert "42" in caplog.text
        assert "instance-uuid-123" in caplog.text

    # -------------------------------------------------------------------------
    # Logging - ERROR on failures
    # -------------------------------------------------------------------------

    def test_logs_error_when_range_not_found(self, caplog):
        """Service logs error when range not found."""
        from engine import connect_terminal
        from engine.models import Range

        mock_user = Mock(id=1)

        with (
            patch.object(Range.objects, "get", side_effect=Range.DoesNotExist),
            caplog.at_level(logging.ERROR, logger="engine"),
            pytest.raises(Range.DoesNotExist),
        ):
            connect_terminal(mock_user, 999, "uuid-123")

        assert "error" in caplog.text.lower() or "not found" in caplog.text.lower()

    def test_logs_error_when_range_not_ready(self, caplog):
        """Service logs error when range is not READY."""
        from engine import connect_terminal
        from engine.models import Range

        mock_user = Mock(id=1)

        mock_range = Mock(spec=Range, id=42, user=mock_user, status=Range.Status.PROVISIONING)

        with (
            patch.object(Range.objects, "get", return_value=mock_range),
            caplog.at_level(logging.ERROR, logger="engine"),
            pytest.raises(ValueError),
        ):
            connect_terminal(mock_user, 42, "uuid-123")

        assert "error" in caplog.text.lower() or "not ready" in caplog.text.lower()

    def test_logs_error_when_instance_not_found(self, caplog):
        """Service logs error when instance UUID not found."""
        from engine import connect_terminal
        from engine.models import Range

        mock_user = Mock(id=1)

        mock_range = Mock(spec=Range, id=42, user=mock_user, status=Range.Status.READY)
        mock_range.get_instance_by_uuid = Mock(return_value=None)

        with (
            patch.object(Range.objects, "get", return_value=mock_range),
            caplog.at_level(logging.ERROR, logger="engine"),
            pytest.raises(ValueError),
        ):
            connect_terminal(mock_user, 42, "missing-uuid")

        assert "error" in caplog.text.lower() or "not found" in caplog.text.lower()
