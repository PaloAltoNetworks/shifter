"""Tests for connect_terminal() in engine/services.py."""

import logging
from unittest.mock import Mock, patch

import pytest


class TestConnectTerminal:
    """Tests for connect_terminal() in engine/services.py.

    Tests the service contract:
    - Inputs: user (required), instance_uuid (required string)
    - Outputs: SSHConnection for the specified instance
    - Side effects: none (read-only operation)
    - Errors: validates inputs, ownership, range status, instance existence
    - Logging: DEBUG on success, ERROR on failures

    The function looks up Range by instance_uuid in provisioned_instances JSONB.
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

        mock_queryset = Mock()
        mock_queryset.first = Mock(return_value=mock_range)

        ssh_key = "fake-ssh-key-for-testing"
        with (
            patch.object(Range.objects, "filter", return_value=mock_queryset),
            patch("engine.secrets.get_ssh_key", return_value=ssh_key),
        ):
            result = connect_terminal(mock_user, "instance-uuid-123")
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

        mock_queryset = Mock()
        mock_queryset.first = Mock(return_value=mock_range)

        ssh_key = "fake-ssh-key-for-testing"
        with (
            patch.object(Range.objects, "filter", return_value=mock_queryset),
            patch("engine.secrets.get_ssh_key", return_value=ssh_key),
        ):
            result = connect_terminal(mock_user, "victim-uuid-456")
            assert isinstance(result, SSHConnection)
            mock_range.get_instance_by_uuid.assert_called_once_with("victim-uuid-456")

    def test_filters_range_by_instance_uuid_and_user(self):
        """Service queries Range by instance_uuid in provisioned_instances."""
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

        mock_queryset = Mock()
        mock_queryset.first = Mock(return_value=mock_range)

        ssh_key = "fake-ssh-key-for-testing"
        with (
            patch.object(Range.objects, "filter", return_value=mock_queryset) as mock_filter,
            patch("engine.secrets.get_ssh_key", return_value=ssh_key),
        ):
            connect_terminal(mock_user, "instance-uuid-123")
            mock_filter.assert_called_once_with(
                provisioned_instances__contains=[{"uuid": "instance-uuid-123"}],
                user=mock_user,
            )

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

        mock_queryset = Mock()
        mock_queryset.first = Mock(return_value=mock_range)

        ssh_key = "fake-ssh-key-for-testing"
        with (
            patch.object(Range.objects, "filter", return_value=mock_queryset),
            patch("engine.secrets.get_ssh_key", return_value=ssh_key),
        ):
            connect_terminal(mock_user, "instance-uuid-123")
            mock_range.save.assert_not_called()

    # -------------------------------------------------------------------------
    # Input validation - user parameter
    # -------------------------------------------------------------------------

    def test_requires_user_argument(self):
        """Service raises TypeError if user not provided."""
        from engine import connect_terminal

        with pytest.raises(TypeError):
            connect_terminal(instance_uuid="uuid-123")

    def test_raises_on_none_user(self):
        """Service raises error if user is None."""
        from engine import connect_terminal

        with pytest.raises((TypeError, ValueError)):
            connect_terminal(None, "uuid-123")

    # -------------------------------------------------------------------------
    # Input validation - instance_uuid parameter
    # -------------------------------------------------------------------------

    def test_raises_on_none_instance_uuid(self):
        """Service raises error if instance_uuid is None."""
        from engine import connect_terminal

        mock_user = Mock(id=1)

        with pytest.raises((TypeError, ValueError)):
            connect_terminal(mock_user, None)

    def test_raises_on_empty_instance_uuid(self):
        """Service raises error if instance_uuid is empty string."""
        from engine import connect_terminal

        mock_user = Mock(id=1)

        with pytest.raises((TypeError, ValueError)):
            connect_terminal(mock_user, "")

    # -------------------------------------------------------------------------
    # Error handling - range not found
    # -------------------------------------------------------------------------

    def test_raises_when_no_range_found_for_instance(self):
        """Service raises ValueError when no range contains the instance."""
        from engine import connect_terminal
        from engine.models import Range

        mock_user = Mock(id=1)

        mock_queryset = Mock()
        mock_queryset.first = Mock(return_value=None)

        with (
            patch.object(Range.objects, "filter", return_value=mock_queryset),
            pytest.raises(ValueError, match=r"No range found"),
        ):
            connect_terminal(mock_user, "non-existent-uuid")

    # -------------------------------------------------------------------------
    # Error handling - range status
    # -------------------------------------------------------------------------

    def test_raises_when_range_not_ready(self):
        """Service raises ValueError when range is not READY."""
        from engine import connect_terminal
        from engine.models import Range

        mock_user = Mock(id=1)

        mock_range = Mock(spec=Range, id=42, user=mock_user, status=Range.Status.FAILED)

        mock_queryset = Mock()
        mock_queryset.first = Mock(return_value=mock_range)

        with (
            patch.object(Range.objects, "filter", return_value=mock_queryset),
            pytest.raises(ValueError, match="not ready"),
        ):
            connect_terminal(mock_user, "uuid-123")

    def test_raises_when_range_provisioning(self):
        """Service raises ValueError when range is PROVISIONING."""
        from engine import connect_terminal
        from engine.models import Range

        mock_user = Mock(id=1)

        mock_range = Mock(spec=Range, id=42, user=mock_user, status=Range.Status.PROVISIONING)

        mock_queryset = Mock()
        mock_queryset.first = Mock(return_value=mock_range)

        with (
            patch.object(Range.objects, "filter", return_value=mock_queryset),
            pytest.raises(ValueError, match="not ready"),
        ):
            connect_terminal(mock_user, "uuid-123")

    # -------------------------------------------------------------------------
    # Error handling - instance not found in range
    # -------------------------------------------------------------------------

    def test_raises_when_instance_uuid_not_found_in_range(self):
        """Service raises ValueError when instance UUID doesn't exist in range."""
        from engine import connect_terminal
        from engine.models import Range

        mock_user = Mock(id=1)

        mock_range = Mock(spec=Range, id=42, user=mock_user, status=Range.Status.READY)
        mock_range.get_instance_by_uuid = Mock(return_value=None)

        mock_queryset = Mock()
        mock_queryset.first = Mock(return_value=mock_range)

        with (
            patch.object(Range.objects, "filter", return_value=mock_queryset),
            pytest.raises(ValueError, match=r"(?i)instance.*not found"),
        ):
            connect_terminal(mock_user, "non-existent-uuid")

    # -------------------------------------------------------------------------
    # Logging - DEBUG on success
    # -------------------------------------------------------------------------

    def test_logs_debug_on_entry(self, caplog):
        """Service logs debug on entry with user_id and instance_uuid."""
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

        mock_queryset = Mock()
        mock_queryset.first = Mock(return_value=mock_range)

        ssh_key = "fake-ssh-key-for-testing"
        with (
            patch.object(Range.objects, "filter", return_value=mock_queryset),
            patch("engine.secrets.get_ssh_key", return_value=ssh_key),
            caplog.at_level(logging.DEBUG, logger="engine"),
        ):
            connect_terminal(mock_user, "instance-uuid-123")

        assert "instance-uuid-123" in caplog.text

    # -------------------------------------------------------------------------
    # Logging - ERROR on failures
    # -------------------------------------------------------------------------

    def test_logs_error_when_range_not_found(self, caplog):
        """Service logs error when no range found for instance."""
        from engine import connect_terminal
        from engine.models import Range

        mock_user = Mock(id=1)

        mock_queryset = Mock()
        mock_queryset.first = Mock(return_value=None)

        with (
            patch.object(Range.objects, "filter", return_value=mock_queryset),
            caplog.at_level(logging.ERROR, logger="engine"),
            pytest.raises(ValueError),
        ):
            connect_terminal(mock_user, "missing-uuid")

        assert "error" in caplog.text.lower() or "not found" in caplog.text.lower()

    def test_logs_error_when_range_not_ready(self, caplog):
        """Service logs error when range is not READY."""
        from engine import connect_terminal
        from engine.models import Range

        mock_user = Mock(id=1)

        mock_range = Mock(spec=Range, id=42, user=mock_user, status=Range.Status.PROVISIONING)

        mock_queryset = Mock()
        mock_queryset.first = Mock(return_value=mock_range)

        with (
            patch.object(Range.objects, "filter", return_value=mock_queryset),
            caplog.at_level(logging.ERROR, logger="engine"),
            pytest.raises(ValueError),
        ):
            connect_terminal(mock_user, "uuid-123")

        assert "error" in caplog.text.lower() or "not ready" in caplog.text.lower()

    def test_logs_error_when_instance_not_found(self, caplog):
        """Service logs error when instance UUID not found."""
        from engine import connect_terminal
        from engine.models import Range

        mock_user = Mock(id=1)

        mock_range = Mock(spec=Range, id=42, user=mock_user, status=Range.Status.READY)
        mock_range.get_instance_by_uuid = Mock(return_value=None)

        mock_queryset = Mock()
        mock_queryset.first = Mock(return_value=mock_range)

        with (
            patch.object(Range.objects, "filter", return_value=mock_queryset),
            caplog.at_level(logging.ERROR, logger="engine"),
            pytest.raises(ValueError),
        ):
            connect_terminal(mock_user, "missing-uuid")

        assert "error" in caplog.text.lower() or "not found" in caplog.text.lower()

    # -------------------------------------------------------------------------
    # SSH username based on os_type
    # -------------------------------------------------------------------------

    def test_uses_kali_username_for_kali_os_type(self):
        """Service uses 'kali' username when os_type is 'kali'."""
        from engine import connect_terminal
        from engine.models import Range

        mock_user = Mock(id=1)
        instance_data = {
            "uuid": "kali-uuid-123",
            "role": "attacker",
            "os_type": "kali",
            "private_ip": "10.1.1.10",
            "ssh_key_secret_arn": "arn:aws:secretsmanager:us-east-2:123:secret:key",
        }
        mock_range = Mock(spec=Range, id=42, user=mock_user, status=Range.Status.READY)
        mock_range.get_instance_by_uuid = Mock(return_value=instance_data)

        mock_queryset = Mock()
        mock_queryset.first = Mock(return_value=mock_range)

        ssh_key = "fake-ssh-key-for-testing"
        with (
            patch.object(Range.objects, "filter", return_value=mock_queryset),
            patch("engine.secrets.get_ssh_key", return_value=ssh_key),
        ):
            result = connect_terminal(mock_user, "kali-uuid-123")
            assert result.username == "kali"

    def test_uses_ubuntu_username_for_ubuntu_os_type(self):
        """Service uses 'ubuntu' username when os_type is 'ubuntu'."""
        from engine import connect_terminal
        from engine.models import Range

        mock_user = Mock(id=1)
        instance_data = {
            "uuid": "ubuntu-uuid-456",
            "role": "victim",
            "os_type": "ubuntu",
            "private_ip": "10.1.1.20",
            "ssh_key_secret_arn": "arn:aws:secretsmanager:us-east-2:123:secret:key",
        }
        mock_range = Mock(spec=Range, id=42, user=mock_user, status=Range.Status.READY)
        mock_range.get_instance_by_uuid = Mock(return_value=instance_data)

        mock_queryset = Mock()
        mock_queryset.first = Mock(return_value=mock_range)

        ssh_key = "fake-ssh-key-for-testing"
        with (
            patch.object(Range.objects, "filter", return_value=mock_queryset),
            patch("engine.secrets.get_ssh_key", return_value=ssh_key),
        ):
            result = connect_terminal(mock_user, "ubuntu-uuid-456")
            assert result.username == "ubuntu"

    def test_uses_ec2_user_username_for_amazon_linux_os_type(self):
        """Service uses 'ec2-user' username when os_type is 'amazon-linux'."""
        from engine import connect_terminal
        from engine.models import Range

        mock_user = Mock(id=1)
        instance_data = {
            "uuid": "al-uuid-789",
            "role": "victim",
            "os_type": "amazon-linux",
            "private_ip": "10.1.1.30",
            "ssh_key_secret_arn": "arn:aws:secretsmanager:us-east-2:123:secret:key",
        }
        mock_range = Mock(spec=Range, id=42, user=mock_user, status=Range.Status.READY)
        mock_range.get_instance_by_uuid = Mock(return_value=instance_data)

        mock_queryset = Mock()
        mock_queryset.first = Mock(return_value=mock_range)

        ssh_key = "fake-ssh-key-for-testing"
        with (
            patch.object(Range.objects, "filter", return_value=mock_queryset),
            patch("engine.secrets.get_ssh_key", return_value=ssh_key),
        ):
            result = connect_terminal(mock_user, "al-uuid-789")
            assert result.username == "ec2-user"

    def test_defaults_to_ubuntu_when_os_type_missing(self):
        """Service defaults to 'ubuntu' username when os_type is not set."""
        from engine import connect_terminal
        from engine.models import Range

        mock_user = Mock(id=1)
        instance_data = {
            "uuid": "no-os-uuid",
            "role": "victim",
            "private_ip": "10.1.1.40",
            "ssh_key_secret_arn": "arn:aws:secretsmanager:us-east-2:123:secret:key",
            # os_type intentionally omitted
        }
        mock_range = Mock(spec=Range, id=42, user=mock_user, status=Range.Status.READY)
        mock_range.get_instance_by_uuid = Mock(return_value=instance_data)

        mock_queryset = Mock()
        mock_queryset.first = Mock(return_value=mock_range)

        ssh_key = "fake-ssh-key-for-testing"
        with (
            patch.object(Range.objects, "filter", return_value=mock_queryset),
            patch("engine.secrets.get_ssh_key", return_value=ssh_key),
        ):
            result = connect_terminal(mock_user, "no-os-uuid")
            assert result.username == "ubuntu"

    def test_handles_uppercase_os_type(self):
        """Service handles uppercase os_type values (case-insensitive)."""
        from engine import connect_terminal
        from engine.models import Range

        mock_user = Mock(id=1)
        instance_data = {
            "uuid": "upper-uuid",
            "role": "attacker",
            "os_type": "KALI",
            "private_ip": "10.1.1.50",
            "ssh_key_secret_arn": "arn:aws:secretsmanager:us-east-2:123:secret:key",
        }
        mock_range = Mock(spec=Range, id=42, user=mock_user, status=Range.Status.READY)
        mock_range.get_instance_by_uuid = Mock(return_value=instance_data)

        mock_queryset = Mock()
        mock_queryset.first = Mock(return_value=mock_range)

        ssh_key = "fake-ssh-key-for-testing"
        with (
            patch.object(Range.objects, "filter", return_value=mock_queryset),
            patch("engine.secrets.get_ssh_key", return_value=ssh_key),
        ):
            result = connect_terminal(mock_user, "upper-uuid")
            assert result.username == "kali"

    def test_uses_administrator_username_for_windows_os_type(self):
        """Service uses 'Administrator' username when os_type is 'windows'."""
        from engine import connect_terminal
        from engine.models import Range

        mock_user = Mock(id=1)
        instance_data = {
            "uuid": "win-uuid-123",
            "role": "victim",
            "os_type": "windows",
            "private_ip": "10.1.1.60",
            "ssh_key_secret_arn": "arn:aws:secretsmanager:us-east-2:123:secret:key",
        }
        mock_range = Mock(spec=Range, id=42, user=mock_user, status=Range.Status.READY)
        mock_range.get_instance_by_uuid = Mock(return_value=instance_data)

        mock_queryset = Mock()
        mock_queryset.first = Mock(return_value=mock_range)

        ssh_key = "fake-ssh-key-for-testing"
        with (
            patch.object(Range.objects, "filter", return_value=mock_queryset),
            patch("engine.secrets.get_ssh_key", return_value=ssh_key),
        ):
            result = connect_terminal(mock_user, "win-uuid-123")
            assert result.username == "Administrator"

    # -------------------------------------------------------------------------
    # Persistent tmux sessions (session_id)
    # -------------------------------------------------------------------------

    def test_sets_session_id_for_kali_instances(self):
        """Service sets session_id for Kali instances (tmux persistent session)."""
        from engine import connect_terminal
        from engine.models import Range

        mock_user = Mock(id=1)
        instance_data = {
            "uuid": "kali-uuid-789",
            "role": "attacker",
            "os_type": "kali",
            "private_ip": "10.1.1.10",
            "ssh_key_secret_arn": "arn:aws:secretsmanager:us-east-2:123:secret:key",
        }
        mock_range = Mock(spec=Range, id=42, user=mock_user, status=Range.Status.READY)
        mock_range.get_instance_by_uuid = Mock(return_value=instance_data)

        mock_queryset = Mock()
        mock_queryset.first = Mock(return_value=mock_range)

        ssh_key = "fake-ssh-key-for-testing"
        with (
            patch.object(Range.objects, "filter", return_value=mock_queryset),
            patch("engine.secrets.get_ssh_key", return_value=ssh_key),
        ):
            result = connect_terminal(mock_user, "kali-uuid-789")
            assert result.session_id == "kali-uuid-789"

    def test_sets_session_id_for_ubuntu_instances(self):
        """Service sets session_id for Ubuntu instances (tmux persistent session)."""
        from engine import connect_terminal
        from engine.models import Range

        mock_user = Mock(id=1)
        instance_data = {
            "uuid": "ubuntu-uuid-789",
            "role": "victim",
            "os_type": "ubuntu",
            "private_ip": "10.1.1.20",
            "ssh_key_secret_arn": "arn:aws:secretsmanager:us-east-2:123:secret:key",
        }
        mock_range = Mock(spec=Range, id=42, user=mock_user, status=Range.Status.READY)
        mock_range.get_instance_by_uuid = Mock(return_value=instance_data)

        mock_queryset = Mock()
        mock_queryset.first = Mock(return_value=mock_range)

        ssh_key = "fake-ssh-key-for-testing"
        with (
            patch.object(Range.objects, "filter", return_value=mock_queryset),
            patch("engine.secrets.get_ssh_key", return_value=ssh_key),
        ):
            result = connect_terminal(mock_user, "ubuntu-uuid-789")
            assert result.session_id == "ubuntu-uuid-789"

    def test_no_session_id_for_windows_instances(self):
        """Service does NOT set session_id for Windows instances (no tmux)."""
        from engine import connect_terminal
        from engine.models import Range

        mock_user = Mock(id=1)
        instance_data = {
            "uuid": "windows-uuid-789",
            "role": "victim",
            "os_type": "windows",
            "private_ip": "10.1.1.60",
            "ssh_key_secret_arn": "arn:aws:secretsmanager:us-east-2:123:secret:key",
        }
        mock_range = Mock(spec=Range, id=42, user=mock_user, status=Range.Status.READY)
        mock_range.get_instance_by_uuid = Mock(return_value=instance_data)

        mock_queryset = Mock()
        mock_queryset.first = Mock(return_value=mock_range)

        ssh_key = "fake-ssh-key-for-testing"
        with (
            patch.object(Range.objects, "filter", return_value=mock_queryset),
            patch("engine.secrets.get_ssh_key", return_value=ssh_key),
        ):
            result = connect_terminal(mock_user, "windows-uuid-789")
            assert result.session_id is None
