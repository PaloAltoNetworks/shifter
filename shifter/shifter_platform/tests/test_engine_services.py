"""Tests for engine service imports.

These tests verify that services are importable from the engine package
after migration from mission_control.
"""

import logging
from unittest.mock import Mock, patch

import pytest


class TestECSService:
    """Tests for ECS service import from engine.services.ecs."""

    def test_start_provisioning_importable(self):
        """start_provisioning is importable from engine.services.ecs."""
        from engine.services.ecs import start_provisioning

        assert callable(start_provisioning)

    def test_start_teardown_importable(self):
        """start_teardown is importable from engine.services.ecs."""
        from engine.services.ecs import start_teardown

        assert callable(start_teardown)

    def test_get_task_status_importable(self):
        """get_task_status is importable from engine.services.ecs."""
        from engine.services.ecs import get_task_status

        assert callable(get_task_status)


class TestSSHService:
    """Tests for SSH service import from engine.services.ssh."""

    def test_ssh_connection_importable(self):
        """SSHConnection is importable from engine.services.ssh."""
        from engine.services.ssh import SSHConnection

        assert SSHConnection is not None

    def test_ssh_connection_error_importable(self):
        """SSHConnectionError is importable from engine.services.ssh."""
        from engine.services.ssh import SSHConnectionError

        assert issubclass(SSHConnectionError, Exception)


class TestSecretsService:
    """Tests for Secrets service import from engine.services.secrets."""

    def test_get_ssh_key_importable(self):
        """get_ssh_key is importable from engine.services.secrets."""
        from engine.services.secrets import get_ssh_key

        assert callable(get_ssh_key)

    def test_secrets_error_importable(self):
        """SecretsError is importable from engine.services.secrets."""
        from engine.services.secrets import SecretsError

        assert issubclass(SecretsError, Exception)


# =============================================================================
# Phase 3: Engine Service Interface Tests
# =============================================================================


@pytest.mark.django_db
class TestGetRangeStatus:
    """Tests for get_range_status() in engine/services.py.

    Tests SERVICE behavior with mocked model layer:
    - Calls Range.objects.get correctly
    - Returns dict with range_id and status
    - Logs all errors from downstream
    - Validates input
    - Propagates errors
    """

    # -------------------------------------------------------------------------
    # Service calls model correctly
    # -------------------------------------------------------------------------

    def test_calls_range_get_with_range_id(self):
        """Service queries Range by id."""
        from engine.models import Range
        from engine.services import get_range_status

        mock_range = Mock(spec=Range, id=42, status=Range.Status.READY)
        with patch.object(Range.objects, "get", return_value=mock_range) as mock_get:
            get_range_status(42)
            mock_get.assert_called_once_with(id=42)

    # -------------------------------------------------------------------------
    # Service returns correct structure
    # -------------------------------------------------------------------------

    def test_returns_dict_with_range_id(self):
        """Service returns dict containing range_id."""
        from engine.models import Range
        from engine.services import get_range_status

        mock_range = Mock(spec=Range, id=42, status=Range.Status.READY)
        with patch.object(Range.objects, "get", return_value=mock_range):
            result = get_range_status(42)
            assert isinstance(result, dict)
            assert result["range_id"] == 42

    def test_returns_dict_with_status(self):
        """Service returns dict containing status string."""
        from engine.models import Range
        from engine.services import get_range_status

        mock_range = Mock(spec=Range, id=42, status=Range.Status.PROVISIONING)
        with patch.object(Range.objects, "get", return_value=mock_range):
            result = get_range_status(42)
            assert result["status"] == Range.Status.PROVISIONING

    def test_returns_ready_status_correctly(self):
        """Service returns READY status when range is ready."""
        from engine.models import Range
        from engine.services import get_range_status

        mock_range = Mock(spec=Range, id=1, status=Range.Status.READY)
        with patch.object(Range.objects, "get", return_value=mock_range):
            result = get_range_status(1)
            assert result["status"] == Range.Status.READY

    def test_returns_failed_status_correctly(self):
        """Service returns FAILED status when range failed."""
        from engine.models import Range
        from engine.services import get_range_status

        mock_range = Mock(spec=Range, id=1, status=Range.Status.FAILED)
        with patch.object(Range.objects, "get", return_value=mock_range):
            result = get_range_status(1)
            assert result["status"] == Range.Status.FAILED

    def test_returns_destroyed_status_correctly(self):
        """Service returns DESTROYED status for destroyed range."""
        from engine.models import Range
        from engine.services import get_range_status

        mock_range = Mock(spec=Range, id=1, status=Range.Status.DESTROYED)
        with patch.object(Range.objects, "get", return_value=mock_range):
            result = get_range_status(1)
            assert result["status"] == Range.Status.DESTROYED

    # -------------------------------------------------------------------------
    # Logging - DEBUG on success
    # -------------------------------------------------------------------------

    def test_logs_debug_on_entry(self, caplog):
        """Service logs debug on entry with range_id."""
        from engine.models import Range
        from engine.services import get_range_status

        mock_range = Mock(spec=Range, id=42, status=Range.Status.READY)
        with (
            patch.object(Range.objects, "get", return_value=mock_range),
            caplog.at_level(logging.DEBUG, logger="engine.services"),
        ):
            get_range_status(42)
        assert "42" in caplog.text

    def test_logs_debug_on_success(self, caplog):
        """Service logs debug on successful status retrieval."""
        from engine.models import Range
        from engine.services import get_range_status

        mock_range = Mock(spec=Range, id=42, status=Range.Status.READY)
        with (
            patch.object(Range.objects, "get", return_value=mock_range),
            caplog.at_level(logging.DEBUG, logger="engine.services"),
        ):
            get_range_status(42)
        # Should log success with range_id
        assert "42" in caplog.text

    # -------------------------------------------------------------------------
    # Logging - ERROR on failures
    # -------------------------------------------------------------------------

    def test_logs_error_when_range_not_found(self, caplog):
        """Service logs error when Range.DoesNotExist raised."""
        from engine.models import Range
        from engine.services import get_range_status

        with (
            patch.object(Range.objects, "get", side_effect=Range.DoesNotExist),
            caplog.at_level(logging.ERROR, logger="engine.services"),
            pytest.raises(Range.DoesNotExist),
        ):
            get_range_status(999)
        assert "error" in caplog.text.lower() or "not found" in caplog.text.lower()

    def test_logs_error_on_database_failure(self, caplog):
        """Service logs error when database raises exception."""
        from engine.models import Range
        from engine.services import get_range_status

        with (
            patch.object(Range.objects, "get", side_effect=RuntimeError("DB connection failed")),
            caplog.at_level(logging.ERROR, logger="engine.services"),
            pytest.raises(RuntimeError),
        ):
            get_range_status(42)
        assert "error" in caplog.text.lower() or "exception" in caplog.text.lower()

    # -------------------------------------------------------------------------
    # Error handling - Range.DoesNotExist
    # -------------------------------------------------------------------------

    def test_raises_does_not_exist_when_range_not_found(self):
        """Service raises Range.DoesNotExist when range doesn't exist."""
        from engine.models import Range
        from engine.services import get_range_status

        with (
            patch.object(Range.objects, "get", side_effect=Range.DoesNotExist),
            pytest.raises(Range.DoesNotExist),
        ):
            get_range_status(999)

    # -------------------------------------------------------------------------
    # Error propagation
    # -------------------------------------------------------------------------

    def test_propagates_database_exception(self):
        """Service propagates exceptions from model."""
        from engine.models import Range
        from engine.services import get_range_status

        with (
            patch.object(Range.objects, "get", side_effect=RuntimeError("Model error")),
            pytest.raises(RuntimeError, match="Model error"),
        ):
            get_range_status(42)

    # -------------------------------------------------------------------------
    # Input validation - range_id parameter
    # -------------------------------------------------------------------------

    def test_requires_range_id_argument(self):
        """Service raises TypeError if range_id not provided."""
        from engine.services import get_range_status

        with pytest.raises(TypeError):
            get_range_status()

    def test_raises_on_none_range_id(self):
        """Service raises error if range_id is None."""
        from engine.services import get_range_status

        with pytest.raises((TypeError, ValueError)):
            get_range_status(None)

    def test_raises_on_invalid_range_id_type(self):
        """Service raises error if range_id is wrong type."""
        from engine.services import get_range_status

        with pytest.raises((TypeError, ValueError)):
            get_range_status("not-an-id")

    def test_raises_on_negative_range_id(self):
        """Service raises error if range_id is negative."""
        from engine.services import get_range_status

        with pytest.raises((TypeError, ValueError)):
            get_range_status(-1)

    def test_logs_error_on_invalid_range_id(self, caplog):
        """Service logs error when given invalid range_id."""
        from engine.services import get_range_status

        with (
            caplog.at_level(logging.ERROR, logger="engine.services"),
            pytest.raises((TypeError, ValueError)),
        ):
            get_range_status(None)
        assert "error" in caplog.text.lower() or "invalid" in caplog.text.lower() or "none" in caplog.text.lower()


@pytest.mark.django_db
class TestConnectTerminal:
    """Tests for connect_terminal() in engine/services.py.

    Tests SERVICE behavior:
    - Validates user, range_id, and instance_type parameters
    - Fetches Range and verifies user ownership
    - Verifies range is READY
    - Returns SSHConnection for specified instance
    - Logs all errors from downstream
    """

    # -------------------------------------------------------------------------
    # Service calls model correctly
    # -------------------------------------------------------------------------

    def test_calls_range_get_with_range_id(self):
        """Service queries Range by id and user."""
        from engine.models import Range
        from engine.services import connect_terminal

        mock_user = Mock(id=1)

        mock_range = Mock(spec=Range, id=42, user=mock_user, status=Range.Status.READY)
        instance_data = {
            "role": "attacker",
            "private_ip": "10.1.1.10",
            "ssh_key_secret_arn": "arn:aws:secretsmanager:us-east-2:123:secret:key",
        }
        mock_range.provisioned_instances = [instance_data]
        mock_range.get_instance_by_role = Mock(return_value=instance_data)

        ssh_key = "fake-ssh-key-for-testing"
        with (
            patch.object(Range.objects, "get", return_value=mock_range) as mock_get,
            patch("engine.services.secrets.get_ssh_key", return_value=ssh_key),
        ):
            connect_terminal(mock_user, 42, "attacker")
            mock_get.assert_called_once_with(id=42)

    # -------------------------------------------------------------------------
    # Service returns SSHConnection
    # -------------------------------------------------------------------------

    def test_returns_ssh_connection(self):
        """Service returns SSHConnection for valid inputs."""
        from engine.models import Range
        from engine.services import connect_terminal
        from engine.services.ssh import SSHConnection

        mock_user = Mock(id=1)
        instance_data = {
            "role": "attacker",
            "private_ip": "10.1.1.10",
            "ssh_key_secret_arn": "arn:aws:secretsmanager:us-east-2:123:secret:key",
        }
        mock_range = Mock(spec=Range, id=42, user=mock_user, status=Range.Status.READY)
        mock_range.get_instance_by_role = Mock(return_value=instance_data)

        ssh_key = "fake-ssh-key-for-testing"
        with (
            patch.object(Range.objects, "get", return_value=mock_range),
            patch("engine.services.secrets.get_ssh_key", return_value=ssh_key),
        ):
            result = connect_terminal(mock_user, 42, "attacker")
            assert isinstance(result, SSHConnection)

    def test_returns_ssh_connection_for_victim(self):
        """Service returns SSHConnection for victim instance."""
        from engine.models import Range
        from engine.services import connect_terminal
        from engine.services.ssh import SSHConnection

        mock_user = Mock(id=1)
        instance_data = {
            "role": "victim",
            "private_ip": "10.1.1.20",
            "ssh_key_secret_arn": "arn:aws:secretsmanager:us-east-2:123:secret:key",
        }
        mock_range = Mock(spec=Range, id=42, user=mock_user, status=Range.Status.READY)
        mock_range.get_instance_by_role = Mock(return_value=instance_data)

        ssh_key = "fake-ssh-key-for-testing"
        with (
            patch.object(Range.objects, "get", return_value=mock_range),
            patch("engine.services.secrets.get_ssh_key", return_value=ssh_key),
        ):
            result = connect_terminal(mock_user, 42, "victim")
            assert isinstance(result, SSHConnection)
            mock_range.get_instance_by_role.assert_called_once_with("victim")

    # -------------------------------------------------------------------------
    # Logging - DEBUG on success
    # -------------------------------------------------------------------------

    def test_logs_debug_on_entry(self, caplog):
        """Service logs debug on entry with user_id, range_id, instance_type."""
        from engine.models import Range
        from engine.services import connect_terminal

        mock_user = Mock(id=1)
        instance_data = {
            "role": "attacker",
            "private_ip": "10.1.1.10",
            "ssh_key_secret_arn": "arn:aws:secretsmanager:us-east-2:123:secret:key",
        }
        mock_range = Mock(spec=Range, id=42, user=mock_user, status=Range.Status.READY)
        mock_range.get_instance_by_role = Mock(return_value=instance_data)

        ssh_key = "fake-ssh-key-for-testing"
        with (
            patch.object(Range.objects, "get", return_value=mock_range),
            patch("engine.services.secrets.get_ssh_key", return_value=ssh_key),
            caplog.at_level(logging.DEBUG, logger="engine.services"),
        ):
            connect_terminal(mock_user, 42, "attacker")

        assert "42" in caplog.text
        assert "attacker" in caplog.text

    # -------------------------------------------------------------------------
    # Logging - ERROR on failures
    # -------------------------------------------------------------------------

    def test_logs_error_when_range_not_found(self, caplog):
        """Service logs error when range not found."""
        from engine.models import Range
        from engine.services import connect_terminal

        mock_user = Mock(id=1)

        with (
            patch.object(Range.objects, "get", side_effect=Range.DoesNotExist),
            caplog.at_level(logging.ERROR, logger="engine.services"),
            pytest.raises(Range.DoesNotExist),
        ):
            connect_terminal(mock_user, 999, "attacker")

        assert "error" in caplog.text.lower() or "not found" in caplog.text.lower()

    def test_logs_error_when_range_not_ready(self, caplog):
        """Service logs error when range is not READY."""
        from engine.models import Range
        from engine.services import connect_terminal

        mock_user = Mock(id=1)

        mock_range = Mock(spec=Range, id=42, user=mock_user, status=Range.Status.PROVISIONING)

        with (
            patch.object(Range.objects, "get", return_value=mock_range),
            caplog.at_level(logging.ERROR, logger="engine.services"),
            pytest.raises(ValueError),
        ):
            connect_terminal(mock_user, 42, "attacker")

        assert "error" in caplog.text.lower() or "not ready" in caplog.text.lower()

    # -------------------------------------------------------------------------
    # Error handling - ownership
    # -------------------------------------------------------------------------

    def test_raises_when_user_does_not_own_range(self):
        """Service raises PermissionError when user doesn't own range."""
        from engine.models import Range
        from engine.services import connect_terminal

        mock_user = Mock(id=1)
        other_user = Mock(id=999)

        mock_range = Mock(spec=Range, id=42, user=other_user, status=Range.Status.READY)

        with patch.object(Range.objects, "get", return_value=mock_range), pytest.raises(PermissionError):
            connect_terminal(mock_user, 42, "attacker")

    # -------------------------------------------------------------------------
    # Error handling - range not ready
    # -------------------------------------------------------------------------

    def test_raises_when_range_not_ready(self):
        """Service raises ValueError when range is not READY."""
        from engine.models import Range
        from engine.services import connect_terminal

        mock_user = Mock(id=1)

        mock_range = Mock(spec=Range, id=42, user=mock_user, status=Range.Status.FAILED)

        with patch.object(Range.objects, "get", return_value=mock_range), pytest.raises(ValueError, match="not ready"):
            connect_terminal(mock_user, 42, "attacker")

    # -------------------------------------------------------------------------
    # Error handling - invalid instance type
    # -------------------------------------------------------------------------

    def test_raises_when_instance_type_not_found(self):
        """Service raises ValueError when instance type doesn't exist."""
        from engine.models import Range
        from engine.services import connect_terminal

        mock_user = Mock(id=1)

        mock_range = Mock(spec=Range, id=42, user=mock_user, status=Range.Status.READY)
        mock_range.get_instance_by_role = Mock(return_value=None)

        with (
            patch.object(Range.objects, "get", return_value=mock_range),
            pytest.raises(ValueError, match=r"instance.*not found"),
        ):
            connect_terminal(mock_user, 42, "invalid_type")

    # -------------------------------------------------------------------------
    # Error propagation
    # -------------------------------------------------------------------------

    def test_propagates_range_does_not_exist(self):
        """Service propagates Range.DoesNotExist."""
        from engine.models import Range
        from engine.services import connect_terminal

        mock_user = Mock(id=1)

        with patch.object(Range.objects, "get", side_effect=Range.DoesNotExist), pytest.raises(Range.DoesNotExist):
            connect_terminal(mock_user, 42, "attacker")

    # -------------------------------------------------------------------------
    # Input validation - user parameter
    # -------------------------------------------------------------------------

    def test_requires_user_argument(self):
        """Service raises TypeError if user not provided."""
        from engine.services import connect_terminal

        with pytest.raises(TypeError):
            connect_terminal(range_id=42, instance_type="attacker")

    def test_raises_on_none_user(self):
        """Service raises error if user is None."""
        from engine.services import connect_terminal

        with pytest.raises((TypeError, ValueError)):
            connect_terminal(None, 42, "attacker")

    # -------------------------------------------------------------------------
    # Input validation - range_id parameter
    # -------------------------------------------------------------------------

    def test_raises_on_none_range_id(self):
        """Service raises error if range_id is None."""
        from engine.services import connect_terminal

        mock_user = Mock(id=1)

        with pytest.raises((TypeError, ValueError)):
            connect_terminal(mock_user, None, "attacker")

    def test_raises_on_invalid_range_id_type(self):
        """Service raises error if range_id is wrong type."""
        from engine.services import connect_terminal

        mock_user = Mock(id=1)

        with pytest.raises((TypeError, ValueError)):
            connect_terminal(mock_user, "not-an-id", "attacker")

    def test_raises_on_negative_range_id(self):
        """Service raises error if range_id is negative."""
        from engine.services import connect_terminal

        mock_user = Mock(id=1)

        with pytest.raises((TypeError, ValueError)):
            connect_terminal(mock_user, -1, "attacker")

    # -------------------------------------------------------------------------
    # Input validation - instance_type parameter
    # -------------------------------------------------------------------------

    def test_raises_on_none_instance_type(self):
        """Service raises error if instance_type is None."""
        from engine.services import connect_terminal

        mock_user = Mock(id=1)

        with pytest.raises((TypeError, ValueError)):
            connect_terminal(mock_user, 42, None)

    def test_raises_on_empty_instance_type(self):
        """Service raises error if instance_type is empty string."""
        from engine.services import connect_terminal

        mock_user = Mock(id=1)

        with pytest.raises((TypeError, ValueError)):
            connect_terminal(mock_user, 42, "")


@pytest.mark.django_db
class TestCreateRange:
    """Tests for create_range() in engine/services.py.

    Tests SERVICE behavior:
    - Validates range_config parameter (dict with required fields)
    - Creates Range record with PENDING status
    - Allocates subnet index
    - Starts ECS provisioning task
    - Returns the created range_id
    - Logs all errors from downstream
    """

    # -------------------------------------------------------------------------
    # Valid range_config fixture
    # -------------------------------------------------------------------------

    @pytest.fixture
    def valid_range_config(self):
        """Return a valid range_config dict for testing."""
        return {
            "user_id": 1,
            "scenario_id": 10,
            "instance_config": [
                {"role": "attacker", "ami_id": "ami-123", "instance_type": "t3.micro"},
                {"role": "victim", "ami_id": "ami-456", "instance_type": "t3.small"},
            ],
            "agent_id": 5,
        }

    # -------------------------------------------------------------------------
    # Service creates Range correctly
    # -------------------------------------------------------------------------

    def test_creates_range_with_pending_status(self, valid_range_config):
        """Service creates Range record with PENDING status."""
        from django.contrib.auth import get_user_model

        from engine.models import Range
        from engine.services import create_range

        User = get_user_model()
        mock_user = Mock(id=1)
        mock_range = Mock(spec=Range, id=42)

        with (
            patch.object(User.objects, "get", return_value=mock_user),
            patch.object(Range.objects, "create", return_value=mock_range) as mock_create,
            patch.object(Range, "allocate_subnet_index", return_value=5),
            patch("engine.services.ecs.start_provisioning", return_value="arn:aws:ecs:test"),
        ):
            create_range(valid_range_config)
            mock_create.assert_called_once()
            call_kwargs = mock_create.call_args.kwargs
            assert call_kwargs["status"] == Range.Status.PENDING

    def test_allocates_subnet_index(self, valid_range_config):
        """Service calls Range.allocate_subnet_index."""
        from django.contrib.auth import get_user_model

        from engine.models import Range
        from engine.services import create_range

        User = get_user_model()
        mock_user = Mock(id=1)
        mock_range = Mock(spec=Range, id=42)

        with (
            patch.object(User.objects, "get", return_value=mock_user),
            patch.object(Range.objects, "create", return_value=mock_range),
            patch.object(Range, "allocate_subnet_index", return_value=5) as mock_allocate,
            patch("engine.services.ecs.start_provisioning", return_value="arn:aws:ecs:test"),
        ):
            create_range(valid_range_config)
            mock_allocate.assert_called_once()

    def test_starts_ecs_provisioning(self, valid_range_config):
        """Service calls start_provisioning with range_id."""
        from django.contrib.auth import get_user_model

        from engine.models import Range
        from engine.services import create_range

        User = get_user_model()
        mock_user = Mock(id=1)
        mock_range = Mock(spec=Range, id=42)

        with (
            patch.object(User.objects, "get", return_value=mock_user),
            patch.object(Range.objects, "create", return_value=mock_range),
            patch.object(Range, "allocate_subnet_index", return_value=5),
            patch("engine.services.ecs.start_provisioning", return_value="arn:aws:ecs:test") as mock_start,
        ):
            create_range(valid_range_config)
            mock_start.assert_called_once_with(42)

    # -------------------------------------------------------------------------
    # Service returns range_id
    # -------------------------------------------------------------------------

    def test_returns_range_id(self, valid_range_config):
        """Service returns created range_id."""
        from django.contrib.auth import get_user_model

        from engine.models import Range
        from engine.services import create_range

        User = get_user_model()
        mock_user = Mock(id=1)
        mock_range = Mock(spec=Range, id=42)

        with (
            patch.object(User.objects, "get", return_value=mock_user),
            patch.object(Range.objects, "create", return_value=mock_range),
            patch.object(Range, "allocate_subnet_index", return_value=5),
            patch("engine.services.ecs.start_provisioning", return_value="arn:aws:ecs:test"),
        ):
            result = create_range(valid_range_config)
            assert result == 42

    # -------------------------------------------------------------------------
    # Logging - DEBUG on success
    # -------------------------------------------------------------------------

    def test_logs_debug_on_entry(self, valid_range_config, caplog):
        """Service logs debug on entry with range_config info."""
        from django.contrib.auth import get_user_model

        from engine.models import Range
        from engine.services import create_range

        User = get_user_model()
        mock_user = Mock(id=1)
        mock_range = Mock(spec=Range, id=42)

        with (
            patch.object(User.objects, "get", return_value=mock_user),
            patch.object(Range.objects, "create", return_value=mock_range),
            patch.object(Range, "allocate_subnet_index", return_value=5),
            patch("engine.services.ecs.start_provisioning", return_value="arn:aws:ecs:test"),
            caplog.at_level(logging.DEBUG, logger="engine.services"),
        ):
            create_range(valid_range_config)

        assert "create_range" in caplog.text

    def test_logs_debug_on_range_created(self, valid_range_config, caplog):
        """Service logs debug when range is created."""
        from django.contrib.auth import get_user_model

        from engine.models import Range
        from engine.services import create_range

        User = get_user_model()
        mock_user = Mock(id=1)
        mock_range = Mock(spec=Range, id=42)

        with (
            patch.object(User.objects, "get", return_value=mock_user),
            patch.object(Range.objects, "create", return_value=mock_range),
            patch.object(Range, "allocate_subnet_index", return_value=5),
            patch("engine.services.ecs.start_provisioning", return_value="arn:aws:ecs:test"),
            caplog.at_level(logging.DEBUG, logger="engine.services"),
        ):
            create_range(valid_range_config)

        assert "42" in caplog.text

    # -------------------------------------------------------------------------
    # Logging - ERROR on failures
    # -------------------------------------------------------------------------

    def test_logs_error_when_subnet_allocation_fails(self, valid_range_config, caplog):
        """Service logs error when subnet allocation fails."""
        from engine.models import Range
        from engine.services import create_range

        with (
            caplog.at_level(logging.ERROR, logger="engine.services"),
            patch.object(Range, "allocate_subnet_index", side_effect=ValueError("No subnets available")),
            pytest.raises(ValueError),
        ):
            create_range(valid_range_config)

        assert "subnet" in caplog.text.lower() or "allocation" in caplog.text.lower() or "error" in caplog.text.lower()

    def test_logs_error_when_range_creation_fails(self, valid_range_config, caplog):
        """Service logs error when Range.objects.create fails."""
        from django.contrib.auth import get_user_model
        from django.db import DatabaseError

        from engine.models import Range
        from engine.services import create_range

        User = get_user_model()
        mock_user = Mock(id=1)

        with (
            caplog.at_level(logging.ERROR, logger="engine.services"),
            patch.object(User.objects, "get", return_value=mock_user),
            patch.object(Range, "allocate_subnet_index", return_value=5),
            patch.object(Range.objects, "create", side_effect=DatabaseError("DB error")),
            pytest.raises(DatabaseError),
        ):
            create_range(valid_range_config)

        assert "error" in caplog.text.lower() or "create" in caplog.text.lower()

    # -------------------------------------------------------------------------
    # Error handling - validation
    # -------------------------------------------------------------------------

    def test_raises_when_user_id_missing(self):
        """Service raises ValueError when user_id missing from config."""
        from engine.services import create_range

        invalid_config = {
            "scenario_id": 10,
            "instance_config": [],
        }

        with pytest.raises((ValueError, KeyError, TypeError)):
            create_range(invalid_config)

    def test_raises_when_instance_config_missing(self):
        """Service raises ValueError when instance_config missing."""
        from engine.services import create_range

        invalid_config = {
            "user_id": 1,
            "scenario_id": 10,
        }

        with pytest.raises((ValueError, KeyError, TypeError)):
            create_range(invalid_config)

    # -------------------------------------------------------------------------
    # Error propagation
    # -------------------------------------------------------------------------

    def test_propagates_subnet_allocation_error(self, valid_range_config):
        """Service propagates ValueError from subnet allocation."""
        from engine.models import Range
        from engine.services import create_range

        with (
            patch.object(Range, "allocate_subnet_index", side_effect=ValueError("No subnets available")),
            pytest.raises(ValueError, match="No subnets available"),
        ):
            create_range(valid_range_config)

    def test_propagates_database_error(self, valid_range_config):
        """Service propagates DatabaseError from Range.create."""
        from django.contrib.auth import get_user_model
        from django.db import DatabaseError

        from engine.models import Range
        from engine.services import create_range

        User = get_user_model()
        mock_user = Mock(id=1)

        with (
            patch.object(User.objects, "get", return_value=mock_user),
            patch.object(Range, "allocate_subnet_index", return_value=5),
            patch.object(Range.objects, "create", side_effect=DatabaseError("DB error")),
            pytest.raises(DatabaseError),
        ):
            create_range(valid_range_config)

    def test_propagates_ecs_client_error(self, valid_range_config):
        """Service propagates ClientError from ECS."""
        from botocore.exceptions import ClientError
        from django.contrib.auth import get_user_model

        from engine.models import Range
        from engine.services import create_range

        User = get_user_model()
        mock_user = Mock(id=1)
        mock_range = Mock(spec=Range, id=42)

        with (
            patch.object(User.objects, "get", return_value=mock_user),
            patch.object(Range.objects, "create", return_value=mock_range),
            patch.object(Range, "allocate_subnet_index", return_value=5),
            patch(
                "engine.services.ecs.start_provisioning",
                side_effect=ClientError({"Error": {"Code": "AccessDenied", "Message": "Access Denied"}}, "RunTask"),
            ),
            pytest.raises(ClientError),
        ):
            create_range(valid_range_config)

    # -------------------------------------------------------------------------
    # Input validation
    # -------------------------------------------------------------------------

    def test_raises_on_none_config(self):
        """Service raises error if range_config is None."""
        from engine.services import create_range

        with pytest.raises((TypeError, ValueError)):
            create_range(None)

    def test_raises_on_non_dict_config(self):
        """Service raises error if range_config is not a dict."""
        from engine.services import create_range

        with pytest.raises((TypeError, ValueError)):
            create_range("not a dict")

    def test_raises_on_empty_dict_config(self):
        """Service raises error if range_config is empty dict."""
        from engine.services import create_range

        with pytest.raises((ValueError, KeyError, TypeError)):
            create_range({})


@pytest.mark.django_db
class TestDestroyRange:
    """Tests for destroy_range() in engine/services.py.

    Tests SERVICE behavior:
    - Validates range_id parameter
    - Fetches Range and verifies it's in destroyable state
    - Updates Range status to DESTROYING
    - Starts ECS teardown task
    - Logs all errors from downstream
    """

    # -------------------------------------------------------------------------
    # Service updates Range correctly
    # -------------------------------------------------------------------------

    def test_sets_status_to_destroying(self):
        """Service sets Range status to DESTROYING."""
        from engine.models import Range
        from engine.services import destroy_range

        mock_range = Mock(spec=Range, id=42, status=Range.Status.READY)

        with (
            patch.object(Range.objects, "get", return_value=mock_range),
            patch("engine.services.ecs.start_teardown", return_value="arn:aws:ecs:test"),
        ):
            destroy_range(42)
            assert mock_range.status == Range.Status.DESTROYING
            mock_range.save.assert_called()

    def test_calls_range_get_with_range_id(self):
        """Service queries Range by id."""
        from engine.models import Range
        from engine.services import destroy_range

        mock_range = Mock(spec=Range, id=42, status=Range.Status.READY)

        with (
            patch.object(Range.objects, "get", return_value=mock_range) as mock_get,
            patch("engine.services.ecs.start_teardown", return_value="arn:aws:ecs:test"),
        ):
            destroy_range(42)
            mock_get.assert_called_once_with(id=42)

    def test_starts_ecs_teardown(self):
        """Service calls start_teardown with range_id."""
        from engine.models import Range
        from engine.services import destroy_range

        mock_range = Mock(spec=Range, id=42, status=Range.Status.READY)

        with (
            patch.object(Range.objects, "get", return_value=mock_range),
            patch("engine.services.ecs.start_teardown", return_value="arn:aws:ecs:test") as mock_teardown,
        ):
            destroy_range(42)
            mock_teardown.assert_called_once_with(42)

    def test_returns_none(self):
        """Service returns None on success."""
        from engine.models import Range
        from engine.services import destroy_range

        mock_range = Mock(spec=Range, id=42, status=Range.Status.READY)

        with (
            patch.object(Range.objects, "get", return_value=mock_range),
            patch("engine.services.ecs.start_teardown", return_value="arn:aws:ecs:test"),
        ):
            result = destroy_range(42)
            assert result is None

    # -------------------------------------------------------------------------
    # Logging - DEBUG on success
    # -------------------------------------------------------------------------

    def test_logs_debug_on_entry(self, caplog):
        """Service logs debug on entry with range_id."""
        from engine.models import Range
        from engine.services import destroy_range

        mock_range = Mock(spec=Range, id=42, status=Range.Status.READY)

        with (
            patch.object(Range.objects, "get", return_value=mock_range),
            patch("engine.services.ecs.start_teardown", return_value="arn:aws:ecs:test"),
            caplog.at_level(logging.DEBUG, logger="engine.services"),
        ):
            destroy_range(42)

        assert "42" in caplog.text

    # -------------------------------------------------------------------------
    # Logging - ERROR on failures
    # -------------------------------------------------------------------------

    def test_logs_error_when_range_not_found(self, caplog):
        """Service logs error when range not found."""
        from engine.models import Range
        from engine.services import destroy_range

        with (
            caplog.at_level(logging.ERROR, logger="engine.services"),
            patch.object(Range.objects, "get", side_effect=Range.DoesNotExist),
            pytest.raises(Range.DoesNotExist),
        ):
            destroy_range(42)

        assert "42" in caplog.text

    def test_logs_error_when_range_already_destroyed(self, caplog):
        """Service logs error when range already destroyed."""
        from engine.models import Range
        from engine.services import destroy_range

        mock_range = Mock(spec=Range, id=42, status=Range.Status.DESTROYED)

        with (
            caplog.at_level(logging.ERROR, logger="engine.services"),
            patch.object(Range.objects, "get", return_value=mock_range),
            pytest.raises(ValueError),
        ):
            destroy_range(42)

        assert "42" in caplog.text or "destroy" in caplog.text.lower()

    # -------------------------------------------------------------------------
    # Error handling - state validation
    # -------------------------------------------------------------------------

    def test_raises_when_range_already_destroyed(self):
        """Service raises ValueError when range already destroyed."""
        from engine.models import Range
        from engine.services import destroy_range

        mock_range = Mock(spec=Range, id=42, status=Range.Status.DESTROYED)

        with (
            patch.object(Range.objects, "get", return_value=mock_range),
            pytest.raises(ValueError, match="already"),
        ):
            destroy_range(42)

    def test_raises_when_range_already_destroying(self):
        """Service raises ValueError when range already being destroyed."""
        from engine.models import Range
        from engine.services import destroy_range

        mock_range = Mock(spec=Range, id=42, status=Range.Status.DESTROYING)

        with (
            patch.object(Range.objects, "get", return_value=mock_range),
            pytest.raises(ValueError, match="already"),
        ):
            destroy_range(42)

    # -------------------------------------------------------------------------
    # Error propagation
    # -------------------------------------------------------------------------

    def test_propagates_range_does_not_exist(self):
        """Service propagates Range.DoesNotExist."""
        from engine.models import Range
        from engine.services import destroy_range

        with patch.object(Range.objects, "get", side_effect=Range.DoesNotExist), pytest.raises(Range.DoesNotExist):
            destroy_range(42)

    def test_propagates_ecs_client_error(self):
        """Service propagates ClientError from ECS."""
        from botocore.exceptions import ClientError

        from engine.models import Range
        from engine.services import destroy_range

        mock_range = Mock(spec=Range, id=42, status=Range.Status.READY)

        with (
            patch.object(Range.objects, "get", return_value=mock_range),
            patch(
                "engine.services.ecs.start_teardown",
                side_effect=ClientError({"Error": {"Code": "AccessDenied", "Message": "Access Denied"}}, "RunTask"),
            ),
            pytest.raises(ClientError),
        ):
            destroy_range(42)

    # -------------------------------------------------------------------------
    # Input validation
    # -------------------------------------------------------------------------

    def test_raises_on_none_range_id(self):
        """Service raises error if range_id is None."""
        from engine.services import destroy_range

        with pytest.raises((TypeError, ValueError)):
            destroy_range(None)

    def test_raises_on_invalid_range_id_type(self):
        """Service raises error if range_id is not an int."""
        from engine.services import destroy_range

        with pytest.raises((TypeError, ValueError)):
            destroy_range("not an int")

    def test_raises_on_negative_range_id(self):
        """Service raises error if range_id is negative."""
        from engine.services import destroy_range

        with pytest.raises((TypeError, ValueError)):
            destroy_range(-1)


@pytest.mark.django_db
class TestCancelRange:
    """Tests for cancel_range() in engine/services.py.

    Tests SERVICE behavior:
    - Validates range_id parameter
    - Fetches Range and verifies it's in cancellable state (PENDING or PROVISIONING)
    - Updates Range status to FAILED
    - Logs all errors from downstream
    """

    # -------------------------------------------------------------------------
    # Service updates Range correctly
    # -------------------------------------------------------------------------

    def test_sets_status_to_failed(self):
        """Service sets Range status to FAILED when cancelling."""
        from engine.models import Range
        from engine.services import cancel_range

        mock_range = Mock(spec=Range, id=42, status=Range.Status.PROVISIONING)

        with patch.object(Range.objects, "get", return_value=mock_range):
            cancel_range(42)
            assert mock_range.status == Range.Status.FAILED
            mock_range.save.assert_called()

    def test_calls_range_get_with_range_id(self):
        """Service queries Range by id."""
        from engine.models import Range
        from engine.services import cancel_range

        mock_range = Mock(spec=Range, id=42, status=Range.Status.PENDING)

        with patch.object(Range.objects, "get", return_value=mock_range) as mock_get:
            cancel_range(42)
            mock_get.assert_called_once_with(id=42)

    def test_cancels_pending_range(self):
        """Service can cancel a PENDING range."""
        from engine.models import Range
        from engine.services import cancel_range

        mock_range = Mock(spec=Range, id=42, status=Range.Status.PENDING)

        with patch.object(Range.objects, "get", return_value=mock_range):
            cancel_range(42)
            assert mock_range.status == Range.Status.FAILED

    def test_cancels_provisioning_range(self):
        """Service can cancel a PROVISIONING range."""
        from engine.models import Range
        from engine.services import cancel_range

        mock_range = Mock(spec=Range, id=42, status=Range.Status.PROVISIONING)

        with patch.object(Range.objects, "get", return_value=mock_range):
            cancel_range(42)
            assert mock_range.status == Range.Status.FAILED

    def test_returns_none(self):
        """Service returns None on success."""
        from engine.models import Range
        from engine.services import cancel_range

        mock_range = Mock(spec=Range, id=42, status=Range.Status.PENDING)

        with patch.object(Range.objects, "get", return_value=mock_range):
            result = cancel_range(42)
            assert result is None

    # -------------------------------------------------------------------------
    # Logging - DEBUG on success
    # -------------------------------------------------------------------------

    def test_logs_debug_on_entry(self, caplog):
        """Service logs debug on entry with range_id."""
        from engine.models import Range
        from engine.services import cancel_range

        mock_range = Mock(spec=Range, id=42, status=Range.Status.PENDING)

        with (
            patch.object(Range.objects, "get", return_value=mock_range),
            caplog.at_level(logging.DEBUG, logger="engine.services"),
        ):
            cancel_range(42)

        assert "42" in caplog.text

    # -------------------------------------------------------------------------
    # Logging - ERROR on failures
    # -------------------------------------------------------------------------

    def test_logs_error_when_range_not_found(self, caplog):
        """Service logs error when range not found."""
        from engine.models import Range
        from engine.services import cancel_range

        with (
            caplog.at_level(logging.ERROR, logger="engine.services"),
            patch.object(Range.objects, "get", side_effect=Range.DoesNotExist),
            pytest.raises(Range.DoesNotExist),
        ):
            cancel_range(42)

        assert "42" in caplog.text

    def test_logs_error_when_range_not_cancellable(self, caplog):
        """Service logs error when range is in non-cancellable state."""
        from engine.models import Range
        from engine.services import cancel_range

        mock_range = Mock(spec=Range, id=42, status=Range.Status.READY)

        with (
            caplog.at_level(logging.ERROR, logger="engine.services"),
            patch.object(Range.objects, "get", return_value=mock_range),
            pytest.raises(ValueError),
        ):
            cancel_range(42)

        assert "42" in caplog.text or "cancel" in caplog.text.lower()

    # -------------------------------------------------------------------------
    # Error handling - state validation
    # -------------------------------------------------------------------------

    def test_raises_when_range_is_ready(self):
        """Service raises ValueError when range is already READY."""
        from engine.models import Range
        from engine.services import cancel_range

        mock_range = Mock(spec=Range, id=42, status=Range.Status.READY)

        with (
            patch.object(Range.objects, "get", return_value=mock_range),
            pytest.raises(ValueError, match="cannot be cancelled"),
        ):
            cancel_range(42)

    def test_raises_when_range_is_destroyed(self):
        """Service raises ValueError when range is DESTROYED."""
        from engine.models import Range
        from engine.services import cancel_range

        mock_range = Mock(spec=Range, id=42, status=Range.Status.DESTROYED)

        with (
            patch.object(Range.objects, "get", return_value=mock_range),
            pytest.raises(ValueError, match="cannot be cancelled"),
        ):
            cancel_range(42)

    def test_raises_when_range_is_destroying(self):
        """Service raises ValueError when range is DESTROYING."""
        from engine.models import Range
        from engine.services import cancel_range

        mock_range = Mock(spec=Range, id=42, status=Range.Status.DESTROYING)

        with (
            patch.object(Range.objects, "get", return_value=mock_range),
            pytest.raises(ValueError, match="cannot be cancelled"),
        ):
            cancel_range(42)

    # -------------------------------------------------------------------------
    # Error propagation
    # -------------------------------------------------------------------------

    def test_propagates_range_does_not_exist(self):
        """Service propagates Range.DoesNotExist."""
        from engine.models import Range
        from engine.services import cancel_range

        with patch.object(Range.objects, "get", side_effect=Range.DoesNotExist), pytest.raises(Range.DoesNotExist):
            cancel_range(42)

    # -------------------------------------------------------------------------
    # Input validation
    # -------------------------------------------------------------------------

    def test_raises_on_none_range_id(self):
        """Service raises error if range_id is None."""
        from engine.services import cancel_range

        with pytest.raises((TypeError, ValueError)):
            cancel_range(None)

    def test_raises_on_invalid_range_id_type(self):
        """Service raises error if range_id is not an int."""
        from engine.services import cancel_range

        with pytest.raises((TypeError, ValueError)):
            cancel_range("not an int")

    def test_raises_on_negative_range_id(self):
        """Service raises error if range_id is negative."""
        from engine.services import cancel_range

        with pytest.raises((TypeError, ValueError)):
            cancel_range(-1)
