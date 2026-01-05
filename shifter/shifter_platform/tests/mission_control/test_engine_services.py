"""Tests for engine service imports.

These tests verify that services are importable from the engine package
after migration from mission_control.
"""

import logging
from unittest.mock import Mock, patch

import pytest


class TestECSService:
    """Tests for ECS service import from engine.ecs."""

    def test_start_provisioning_importable(self):
        """start_provisioning is importable from engine.ecs."""
        from engine.ecs import start_provisioning

        assert callable(start_provisioning)

    def test_start_teardown_importable(self):
        """start_teardown is importable from engine.ecs."""
        from engine.ecs import start_teardown

        assert callable(start_teardown)

    def test_get_task_status_importable(self):
        """get_task_status is importable from engine.ecs."""
        from engine.ecs import get_task_status

        assert callable(get_task_status)


class TestSSHService:
    """Tests for SSH service import from engine.ssh."""

    def test_ssh_connection_importable(self):
        """SSHConnection is importable from engine.ssh."""
        from engine.ssh import SSHConnection

        assert SSHConnection is not None

    def test_ssh_connection_error_importable(self):
        """SSHConnectionError is importable from engine.ssh."""
        from engine.ssh import SSHConnectionError

        assert issubclass(SSHConnectionError, Exception)


class TestSecretsService:
    """Tests for Secrets service import from engine.secrets."""

    def test_get_ssh_key_importable(self):
        """get_ssh_key is importable from engine.secrets."""
        from engine.secrets import get_ssh_key

        assert callable(get_ssh_key)

    def test_secrets_error_importable(self):
        """SecretsError is importable from engine.secrets."""
        from engine.secrets import SecretsError

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
        from engine import get_range_status
        from engine.models import Range

        mock_range = Mock(spec=Range, id=42, status=Range.Status.READY)
        with patch.object(Range.objects, "get", return_value=mock_range) as mock_get:
            get_range_status(42)
            mock_get.assert_called_once_with(id=42)

    # -------------------------------------------------------------------------
    # Service returns correct structure
    # -------------------------------------------------------------------------

    def test_returns_dict_with_expected_keys(self):
        """Service returns dict with status, error_message, instances, created_at, ready_at."""
        from engine import get_range_status
        from engine.models import Range

        mock_range = Mock(
            spec=Range,
            id=42,
            status=Range.Status.READY,
            error_message="",
            provisioned_instances=None,
            created_at=None,
            ready_at=None,
        )
        with patch.object(Range.objects, "get", return_value=mock_range):
            result = get_range_status(42)
            assert isinstance(result, dict)
            assert "status" in result
            assert "error_message" in result
            assert "instances" in result
            assert "created_at" in result
            assert "ready_at" in result

    def test_returns_status_value(self):
        """Service returns status string in dict."""
        from engine import get_range_status
        from engine.models import Range

        mock_range = Mock(
            spec=Range,
            id=42,
            status=Range.Status.PROVISIONING,
            error_message="",
            provisioned_instances=None,
            created_at=None,
            ready_at=None,
        )
        with patch.object(Range.objects, "get", return_value=mock_range):
            result = get_range_status(42)
            assert result["status"] == Range.Status.PROVISIONING

    def test_returns_ready_status_correctly(self):
        """Service returns READY status when range is ready."""
        from engine import get_range_status
        from engine.models import Range

        mock_range = Mock(
            spec=Range,
            id=1,
            status=Range.Status.READY,
            error_message="",
            provisioned_instances=None,
            created_at=None,
            ready_at=None,
        )
        with patch.object(Range.objects, "get", return_value=mock_range):
            result = get_range_status(1)
            assert result["status"] == Range.Status.READY

    def test_returns_failed_status_correctly(self):
        """Service returns FAILED status when range failed."""
        from engine import get_range_status
        from engine.models import Range

        mock_range = Mock(
            spec=Range,
            id=1,
            status=Range.Status.FAILED,
            error_message="",
            provisioned_instances=None,
            created_at=None,
            ready_at=None,
        )
        with patch.object(Range.objects, "get", return_value=mock_range):
            result = get_range_status(1)
            assert result["status"] == Range.Status.FAILED

    def test_returns_destroyed_status_correctly(self):
        """Service returns DESTROYED status for destroyed range."""
        from engine import get_range_status
        from engine.models import Range

        mock_range = Mock(
            spec=Range,
            id=1,
            status=Range.Status.DESTROYED,
            error_message="",
            provisioned_instances=None,
            created_at=None,
            ready_at=None,
        )
        with patch.object(Range.objects, "get", return_value=mock_range):
            result = get_range_status(1)
            assert result["status"] == Range.Status.DESTROYED

    # -------------------------------------------------------------------------
    # Logging - DEBUG on success
    # -------------------------------------------------------------------------

    def test_logs_debug_on_entry(self, caplog):
        """Service logs debug on entry with range_id."""
        from engine import get_range_status
        from engine.models import Range

        mock_range = Mock(spec=Range, id=42, status=Range.Status.READY)
        with (
            patch.object(Range.objects, "get", return_value=mock_range),
            caplog.at_level(logging.DEBUG, logger="engine"),
        ):
            get_range_status(42)
        assert "42" in caplog.text

    def test_logs_debug_on_success(self, caplog):
        """Service logs debug on successful status retrieval."""
        from engine import get_range_status
        from engine.models import Range

        mock_range = Mock(spec=Range, id=42, status=Range.Status.READY)
        with (
            patch.object(Range.objects, "get", return_value=mock_range),
            caplog.at_level(logging.DEBUG, logger="engine"),
        ):
            get_range_status(42)
        # Should log success with range_id
        assert "42" in caplog.text

    # -------------------------------------------------------------------------
    # Logging - ERROR on failures
    # -------------------------------------------------------------------------

    def test_logs_warning_when_range_not_found(self, caplog):
        """Service logs warning when range not found and returns None."""
        from engine import get_range_status
        from engine.models import Range

        with (
            patch.object(Range.objects, "get", side_effect=Range.DoesNotExist),
            caplog.at_level(logging.WARNING, logger="engine"),
        ):
            result = get_range_status(999)
            assert result is None
        assert "not found" in caplog.text.lower()

    def test_propagates_database_exception(self, caplog):
        """Service propagates database exceptions."""
        from engine import get_range_status
        from engine.models import Range

        with (
            patch.object(Range.objects, "get", side_effect=RuntimeError("DB connection failed")),
            pytest.raises(RuntimeError),
        ):
            get_range_status(42)

    # -------------------------------------------------------------------------
    # Error handling - returns None when not found
    # -------------------------------------------------------------------------

    def test_returns_none_when_range_not_found(self):
        """Service returns None when range doesn't exist."""
        from engine import get_range_status
        from engine.models import Range

        with patch.object(Range.objects, "get", side_effect=Range.DoesNotExist):
            result = get_range_status(999)
            assert result is None

    # -------------------------------------------------------------------------
    # Error propagation
    # -------------------------------------------------------------------------

    def test_propagates_model_exception(self):
        """Service propagates exceptions from model."""
        from engine import get_range_status
        from engine.models import Range

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
        from engine import get_range_status

        with pytest.raises(TypeError):
            get_range_status()

    def test_returns_none_for_nonexistent_range_id(self):
        """Service returns None if range_id doesn't exist (ORM returns DoesNotExist)."""
        from engine import get_range_status
        from engine.models import Range

        with patch.object(Range.objects, "get", side_effect=Range.DoesNotExist):
            result = get_range_status(99999)
            assert result is None

    def test_orm_handles_invalid_range_id_type(self):
        """ORM raises ValueError for invalid range_id type."""
        from engine import get_range_status
        from engine.models import Range

        with (
            patch.object(Range.objects, "get", side_effect=ValueError("invalid literal")),
            pytest.raises(ValueError),
        ):
            get_range_status("not-an-id")

    def test_returns_none_for_negative_range_id(self):
        """Service returns None for negative range_id (no match)."""
        from engine import get_range_status
        from engine.models import Range

        with patch.object(Range.objects, "get", side_effect=Range.DoesNotExist):
            result = get_range_status(-1)
            assert result is None


@pytest.mark.django_db
class TestCreateRange:
    """Tests for create_range() in engine/services.py.

    Tests SERVICE behavior:
    - Validates request parameter (RangeSpec)
    - Creates Range record with PROVISIONING status
    - Allocates subnet index
    - Starts ECS provisioning task
    - Returns the created range_id
    - Logs all errors from downstream
    """

    # -------------------------------------------------------------------------
    # Valid RangeSpec fixture
    # -------------------------------------------------------------------------

    @pytest.fixture
    def valid_range_spec(self):
        """Return a valid RangeSpec for testing."""
        from shared.schemas import InstanceSpec, RangeSpec

        return RangeSpec(
            user_id=1,
            scenario_id="test-scenario",
            instances=[
                InstanceSpec(uuid="uuid-1", role="attacker", os_type="kali"),
                InstanceSpec(uuid="uuid-2", role="victim", os_type="ubuntu"),
            ],
        )

    # -------------------------------------------------------------------------
    # Service creates Range correctly
    # -------------------------------------------------------------------------

    def test_creates_range_with_provisioning_status(self, valid_range_spec):
        """Service creates Range record with PROVISIONING status."""
        from django.contrib.auth import get_user_model

        from engine import create_range
        from engine.models import Range

        User = get_user_model()
        mock_user = Mock(id=1)
        mock_range = Mock(spec=Range, id=42)

        with (
            patch.object(User.objects, "get", return_value=mock_user),
            patch.object(Range.objects, "create", return_value=mock_range) as mock_create,
            patch.object(Range, "allocate_subnet_index", return_value=5),
            patch("engine.ecs.start_provisioning", return_value="arn:aws:ecs:test"),
        ):
            create_range(valid_range_spec)
            mock_create.assert_called_once()
            call_kwargs = mock_create.call_args.kwargs
            assert call_kwargs["status"] == Range.Status.PROVISIONING

    def test_allocates_subnet_index(self, valid_range_spec):
        """Service calls Range.allocate_subnet_index."""
        from django.contrib.auth import get_user_model

        from engine import create_range
        from engine.models import Range

        User = get_user_model()
        mock_user = Mock(id=1)
        mock_range = Mock(spec=Range, id=42)

        with (
            patch.object(User.objects, "get", return_value=mock_user),
            patch.object(Range.objects, "create", return_value=mock_range),
            patch.object(Range, "allocate_subnet_index", return_value=5) as mock_allocate,
            patch("engine.ecs.start_provisioning", return_value="arn:aws:ecs:test"),
        ):
            create_range(valid_range_spec)
            mock_allocate.assert_called_once()

    def test_starts_ecs_provisioning(self, valid_range_spec):
        """Service calls start_provisioning with range_id and user_id."""
        from django.contrib.auth import get_user_model

        from engine import create_range
        from engine.models import Range

        User = get_user_model()
        mock_user = Mock(id=1)
        mock_range = Mock(spec=Range, id=42)

        with (
            patch.object(User.objects, "get", return_value=mock_user),
            patch.object(Range.objects, "create", return_value=mock_range),
            patch.object(Range, "allocate_subnet_index", return_value=5),
            patch("engine.ecs.start_provisioning", return_value="arn:aws:ecs:test") as mock_start,
        ):
            create_range(valid_range_spec)
            mock_start.assert_called_once_with(42, 1)

    # -------------------------------------------------------------------------
    # Service returns range_id
    # -------------------------------------------------------------------------

    def test_returns_range_id(self, valid_range_spec):
        """Service returns created range_id."""
        from django.contrib.auth import get_user_model

        from engine import create_range
        from engine.models import Range

        User = get_user_model()
        mock_user = Mock(id=1)
        mock_range = Mock(spec=Range, id=42)

        with (
            patch.object(User.objects, "get", return_value=mock_user),
            patch.object(Range.objects, "create", return_value=mock_range),
            patch.object(Range, "allocate_subnet_index", return_value=5),
            patch("engine.ecs.start_provisioning", return_value="arn:aws:ecs:test"),
        ):
            result = create_range(valid_range_spec)
            assert result == 42

    # -------------------------------------------------------------------------
    # Logging - DEBUG on success
    # -------------------------------------------------------------------------

    def test_logs_debug_on_entry(self, valid_range_spec, caplog):
        """Service logs debug on entry with range_config info."""
        from django.contrib.auth import get_user_model

        from engine import create_range
        from engine.models import Range

        User = get_user_model()
        mock_user = Mock(id=1)
        mock_range = Mock(spec=Range, id=42)

        with (
            patch.object(User.objects, "get", return_value=mock_user),
            patch.object(Range.objects, "create", return_value=mock_range),
            patch.object(Range, "allocate_subnet_index", return_value=5),
            patch("engine.ecs.start_provisioning", return_value="arn:aws:ecs:test"),
            caplog.at_level(logging.DEBUG, logger="engine"),
        ):
            create_range(valid_range_spec)

        assert "create_range" in caplog.text

    def test_logs_info_on_range_created(self, valid_range_spec, caplog):
        """Service logs info when range is created."""
        from django.contrib.auth import get_user_model

        from engine import create_range
        from engine.models import Range

        User = get_user_model()
        mock_user = Mock(id=1)
        mock_range = Mock(spec=Range, id=42)

        with (
            patch.object(User.objects, "get", return_value=mock_user),
            patch.object(Range.objects, "create", return_value=mock_range),
            patch.object(Range, "allocate_subnet_index", return_value=5),
            patch("engine.ecs.start_provisioning", return_value="arn:aws:ecs:test"),
            caplog.at_level(logging.INFO, logger="engine"),
        ):
            create_range(valid_range_spec)

        assert "42" in caplog.text

    # -------------------------------------------------------------------------
    # Error propagation
    # -------------------------------------------------------------------------

    def test_propagates_subnet_allocation_error(self, valid_range_spec):
        """Service propagates ValueError from subnet allocation."""
        from django.contrib.auth import get_user_model

        from engine import create_range
        from engine.models import Range

        User = get_user_model()
        mock_user = Mock(id=1)

        with (
            patch.object(User.objects, "get", return_value=mock_user),
            patch.object(Range, "allocate_subnet_index", side_effect=ValueError("No subnets available")),
            pytest.raises(ValueError, match="No subnets available"),
        ):
            create_range(valid_range_spec)

    def test_propagates_database_error(self, valid_range_spec):
        """Service propagates DatabaseError from Range.create."""
        from django.contrib.auth import get_user_model
        from django.db import DatabaseError

        from engine import create_range
        from engine.models import Range

        User = get_user_model()
        mock_user = Mock(id=1)

        with (
            patch.object(User.objects, "get", return_value=mock_user),
            patch.object(Range, "allocate_subnet_index", return_value=5),
            patch.object(Range.objects, "create", side_effect=DatabaseError("DB error")),
            pytest.raises(DatabaseError),
        ):
            create_range(valid_range_spec)

    def test_propagates_ecs_client_error(self, valid_range_spec):
        """Service propagates ClientError from ECS."""
        from botocore.exceptions import ClientError
        from django.contrib.auth import get_user_model

        from engine import create_range
        from engine.models import Range

        User = get_user_model()
        mock_user = Mock(id=1)
        mock_range = Mock(spec=Range, id=42)

        with (
            patch.object(User.objects, "get", return_value=mock_user),
            patch.object(Range.objects, "create", return_value=mock_range),
            patch.object(Range, "allocate_subnet_index", return_value=5),
            patch(
                "engine.ecs.start_provisioning",
                side_effect=ClientError({"Error": {"Code": "AccessDenied", "Message": "Access Denied"}}, "RunTask"),
            ),
            pytest.raises(ClientError),
        ):
            create_range(valid_range_spec)

    # -------------------------------------------------------------------------
    # Input validation
    # -------------------------------------------------------------------------

    def test_raises_on_none_request(self):
        """Service raises error if request is None."""
        from engine import create_range

        with pytest.raises(TypeError):
            create_range(None)

    def test_raises_on_non_rangespec_request(self):
        """Service raises TypeError if request is not a RangeSpec."""
        from engine import create_range

        with pytest.raises(TypeError, match="must be RangeSpec"):
            create_range("not a RangeSpec")

    def test_raises_on_dict_instead_of_rangespec(self):
        """Service raises TypeError if dict passed instead of RangeSpec."""
        from engine import create_range

        with pytest.raises(TypeError, match="must be RangeSpec"):
            create_range({"user_id": 1, "scenario_id": "test"})


@pytest.mark.django_db
class TestDestroyRange:
    """Tests for destroy_range() in engine/services.py.

    Tests SERVICE behavior:
    - Takes RangeContext parameter
    - Fetches Range and verifies it's in destroyable state
    - Updates Range status to DESTROYING
    - Starts ECS teardown task
    - Returns bool indicating success
    """

    # -------------------------------------------------------------------------
    # Valid RangeContext fixture
    # -------------------------------------------------------------------------

    @pytest.fixture
    def range_context(self):
        """Return a valid RangeContext for testing."""
        from shared.enums import RangeStatus
        from shared.schemas import RangeContext

        return RangeContext(
            range_id=42,
            user_id=1,
            scenario_id="test-scenario",
            status=RangeStatus.READY,
            instances=[],
        )

    # -------------------------------------------------------------------------
    # Service updates Range correctly
    # -------------------------------------------------------------------------

    def test_sets_status_to_destroying(self, range_context):
        """Service sets Range status to DESTROYING."""
        from engine import destroy_range
        from engine.models import Range
        from shared.enums import RangeStatus

        mock_range = Mock(spec=Range, id=42, status=Range.Status.READY)

        with (
            patch.object(Range.objects, "get", return_value=mock_range),
            patch("engine.ecs.start_teardown", return_value="arn:aws:ecs:test"),
        ):
            destroy_range(range_context)
            assert mock_range.status == RangeStatus.DESTROYING.value
            mock_range.save.assert_called()

    def test_calls_range_get_with_range_id(self, range_context):
        """Service queries Range by id."""
        from engine import destroy_range
        from engine.models import Range

        mock_range = Mock(spec=Range, id=42, status=Range.Status.READY)

        with (
            patch.object(Range.objects, "get", return_value=mock_range) as mock_get,
            patch("engine.ecs.start_teardown", return_value="arn:aws:ecs:test"),
        ):
            destroy_range(range_context)
            mock_get.assert_called_once_with(id=42)

    def test_starts_ecs_teardown(self, range_context):
        """Service calls start_teardown with range_id and user_id."""
        from engine import destroy_range
        from engine.models import Range

        mock_range = Mock(spec=Range, id=42, status=Range.Status.READY)

        with (
            patch.object(Range.objects, "get", return_value=mock_range),
            patch("engine.ecs.start_teardown", return_value="arn:aws:ecs:test") as mock_teardown,
        ):
            destroy_range(range_context)
            mock_teardown.assert_called_once_with(42, 1)

    def test_returns_true_on_success(self, range_context):
        """Service returns True on success."""
        from engine import destroy_range
        from engine.models import Range

        mock_range = Mock(spec=Range, id=42, status=Range.Status.READY)

        with (
            patch.object(Range.objects, "get", return_value=mock_range),
            patch("engine.ecs.start_teardown", return_value="arn:aws:ecs:test"),
        ):
            result = destroy_range(range_context)
            assert result is True

    # -------------------------------------------------------------------------
    # Logging - DEBUG on success
    # -------------------------------------------------------------------------

    def test_logs_debug_on_entry(self, range_context, caplog):
        """Service logs debug on entry with range_id."""
        from engine import destroy_range
        from engine.models import Range

        mock_range = Mock(spec=Range, id=42, status=Range.Status.READY)

        with (
            patch.object(Range.objects, "get", return_value=mock_range),
            patch("engine.ecs.start_teardown", return_value="arn:aws:ecs:test"),
            caplog.at_level(logging.DEBUG, logger="engine"),
        ):
            destroy_range(range_context)

        assert "42" in caplog.text

    # -------------------------------------------------------------------------
    # Returns False for non-destroyable states (doesn't raise)
    # -------------------------------------------------------------------------

    def test_returns_false_when_range_not_found(self, range_context, caplog):
        """Service returns False and logs warning when range not found."""
        from engine import destroy_range
        from engine.models import Range

        with (
            caplog.at_level(logging.WARNING, logger="engine"),
            patch.object(Range.objects, "get", side_effect=Range.DoesNotExist),
        ):
            result = destroy_range(range_context)
            assert result is False
        assert "not found" in caplog.text.lower()

    def test_returns_false_when_range_already_destroyed(self, range_context, caplog):
        """Service returns False when range already destroyed."""
        from engine import destroy_range
        from engine.models import Range
        from shared.enums import RangeStatus

        mock_range = Mock(spec=Range, id=42, status=RangeStatus.DESTROYED)

        with (
            caplog.at_level(logging.WARNING, logger="engine"),
            patch.object(Range.objects, "get", return_value=mock_range),
        ):
            result = destroy_range(range_context)
            assert result is False
        assert "already destroyed" in caplog.text.lower()

    def test_returns_true_when_range_already_destroying(self, range_context, caplog):
        """Service returns True (idempotent) when range already being destroyed."""
        from engine import destroy_range
        from engine.models import Range
        from shared.enums import RangeStatus

        mock_range = Mock(spec=Range, id=42, status=RangeStatus.DESTROYING)

        with (
            caplog.at_level(logging.INFO, logger="engine"),
            patch.object(Range.objects, "get", return_value=mock_range),
        ):
            result = destroy_range(range_context)
            assert result is True
        assert "already destroying" in caplog.text.lower()

    # -------------------------------------------------------------------------
    # Error propagation
    # -------------------------------------------------------------------------

    def test_propagates_ecs_client_error(self, range_context):
        """Service propagates ClientError from ECS."""
        from botocore.exceptions import ClientError

        from engine import destroy_range
        from engine.models import Range

        mock_range = Mock(spec=Range, id=42, status=Range.Status.READY)

        with (
            patch.object(Range.objects, "get", return_value=mock_range),
            patch(
                "engine.ecs.start_teardown",
                side_effect=ClientError({"Error": {"Code": "AccessDenied", "Message": "Access Denied"}}, "RunTask"),
            ),
            pytest.raises(ClientError),
        ):
            destroy_range(range_context)


@pytest.mark.django_db
class TestCancelRange:
    """Tests for cancel_range() in engine/services.py.

    Tests SERVICE behavior:
    - Takes RangeContext parameter with input validation
    - Fetches Range and verifies it's in cancellable state
    - Updates Range status to DESTROYING
    - Returns silently for non-cancellable states (doesn't raise)
    """

    # -------------------------------------------------------------------------
    # Valid RangeContext fixtures
    # -------------------------------------------------------------------------

    @pytest.fixture
    def pending_range_context(self):
        """Return a RangeContext for a pending range."""
        from shared.enums import RangeStatus
        from shared.schemas import RangeContext

        return RangeContext(
            range_id=42,
            user_id=1,
            scenario_id="test-scenario",
            status=RangeStatus.PENDING,
            instances=[],
        )

    @pytest.fixture
    def provisioning_range_context(self):
        """Return a RangeContext for a provisioning range."""
        from shared.enums import RangeStatus
        from shared.schemas import RangeContext

        return RangeContext(
            range_id=42,
            user_id=1,
            scenario_id="test-scenario",
            status=RangeStatus.PROVISIONING,
            instances=[],
        )

    @pytest.fixture
    def ready_range_context(self):
        """Return a RangeContext for a ready range (not cancellable)."""
        from shared.enums import RangeStatus
        from shared.schemas import RangeContext

        return RangeContext(
            range_id=42,
            user_id=1,
            scenario_id="test-scenario",
            status=RangeStatus.READY,
            instances=[],
        )

    # -------------------------------------------------------------------------
    # Service updates Range correctly
    # -------------------------------------------------------------------------

    def test_sets_status_to_destroying(self, provisioning_range_context):
        """Service sets Range status to DESTROYING when cancelling."""
        from engine import cancel_range
        from engine.models import Range

        mock_range = Mock(spec=Range, id=42, status=Range.Status.PROVISIONING)

        with patch.object(Range.objects, "get", return_value=mock_range):
            cancel_range(provisioning_range_context)
            assert mock_range.status == Range.Status.DESTROYING
            mock_range.save.assert_called()

    def test_calls_range_get_with_range_id(self, pending_range_context):
        """Service queries Range by id."""
        from engine import cancel_range
        from engine.models import Range

        mock_range = Mock(spec=Range, id=42, status=Range.Status.PENDING)

        with patch.object(Range.objects, "get", return_value=mock_range) as mock_get:
            cancel_range(pending_range_context)
            mock_get.assert_called_once_with(id=42)

    def test_cancels_pending_range(self, pending_range_context):
        """Service can cancel a PENDING range."""
        from engine import cancel_range
        from engine.models import Range

        mock_range = Mock(spec=Range, id=42, status=Range.Status.PENDING)

        with patch.object(Range.objects, "get", return_value=mock_range):
            cancel_range(pending_range_context)
            assert mock_range.status == Range.Status.DESTROYING

    def test_cancels_provisioning_range(self, provisioning_range_context):
        """Service can cancel a PROVISIONING range."""
        from engine import cancel_range
        from engine.models import Range

        mock_range = Mock(spec=Range, id=42, status=Range.Status.PROVISIONING)

        with patch.object(Range.objects, "get", return_value=mock_range):
            cancel_range(provisioning_range_context)
            assert mock_range.status == Range.Status.DESTROYING

    def test_returns_none(self, pending_range_context):
        """Service returns None on success."""
        from engine import cancel_range
        from engine.models import Range

        mock_range = Mock(spec=Range, id=42, status=Range.Status.PENDING)

        with patch.object(Range.objects, "get", return_value=mock_range):
            result = cancel_range(pending_range_context)
            assert result is None

    # -------------------------------------------------------------------------
    # Logging - DEBUG on success
    # -------------------------------------------------------------------------

    def test_logs_debug_on_entry(self, pending_range_context, caplog):
        """Service logs debug on entry with range_id."""
        from engine import cancel_range
        from engine.models import Range

        mock_range = Mock(spec=Range, id=42, status=Range.Status.PENDING)

        with (
            patch.object(Range.objects, "get", return_value=mock_range),
            caplog.at_level(logging.DEBUG, logger="engine"),
        ):
            cancel_range(pending_range_context)

        assert "42" in caplog.text

    # -------------------------------------------------------------------------
    # Returns silently for non-cancellable states (doesn't raise)
    # -------------------------------------------------------------------------

    def test_returns_silently_when_range_not_found(self, pending_range_context, caplog):
        """Service returns silently and logs warning when range not found."""
        from engine import cancel_range
        from engine.models import Range

        with (
            caplog.at_level(logging.WARNING, logger="engine"),
            patch.object(Range.objects, "get", side_effect=Range.DoesNotExist),
        ):
            result = cancel_range(pending_range_context)
            assert result is None
        assert "not found" in caplog.text.lower()

    def test_returns_silently_when_range_not_cancellable(self, ready_range_context, caplog):
        """Service returns silently and logs warning when range is not cancellable."""
        from engine import cancel_range
        from engine.models import Range

        mock_range = Mock(spec=Range, id=42, status=Range.Status.READY)

        with (
            caplog.at_level(logging.WARNING, logger="engine"),
            patch.object(Range.objects, "get", return_value=mock_range),
        ):
            result = cancel_range(ready_range_context)
            assert result is None
        assert "not cancellable" in caplog.text.lower()

    # -------------------------------------------------------------------------
    # Input validation
    # -------------------------------------------------------------------------

    def test_raises_on_none_range_context(self):
        """Service raises TypeError if range_ctx is None."""
        from engine import cancel_range

        with pytest.raises(TypeError, match="cannot be None"):
            cancel_range(None)

    def test_raises_on_invalid_range_context_type(self):
        """Service raises TypeError if range_ctx is not a RangeContext."""
        from engine import cancel_range

        with pytest.raises(TypeError, match="must be RangeContext"):
            cancel_range("not a RangeContext")

    def test_raises_on_int_instead_of_range_context(self):
        """Service raises TypeError if int passed instead of RangeContext."""
        from engine import cancel_range

        with pytest.raises(TypeError, match="must be RangeContext"):
            cancel_range(42)
