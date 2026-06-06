"""Tests for engine service functions.

Tests verify service layer behavior with mocked model layer.
"""

import logging
from contextlib import nullcontext
from unittest.mock import Mock, patch

import pytest


class _TestCreateRangeHelpers:
    """Shared helpers for split TestCreateRange scenarios."""

    @pytest.fixture
    def valid_request_spec(self):
        """Return a valid RequestSpec containing a RangeSpec for testing."""
        from uuid import uuid4

        from shared.schemas import InstanceSpec, RangeSpec, RequestSpec, SubnetSpec

        request_id = uuid4()
        return RequestSpec(
            request_id=request_id,
            user_id=1,
            items=[
                RangeSpec(
                    user_id=1,
                    scenario_id="test-scenario",
                    subnets=[
                        SubnetSpec(
                            name="test_network",
                            uuid=str(uuid4()),
                            instances=[
                                InstanceSpec(
                                    name="attacker-kali",
                                    uuid="uuid-1",
                                    role="attacker",
                                    os_type="kali",
                                ),
                                InstanceSpec(
                                    name="victim-ubuntu",
                                    uuid="uuid-2",
                                    role="victim",
                                    os_type="ubuntu",
                                ),
                            ],
                            connected_to=[],
                        )
                    ],
                )
            ],
        )

    @pytest.fixture(autouse=True)
    def mock_transaction_atomic(self):
        """Keep these tests unit-level by skipping real DB transaction setup."""
        with patch("engine.services.transaction.atomic", return_value=nullcontext()):
            yield


class TestGetResourceStatus:
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


class TestCreateRangePersistence(_TestCreateRangeHelpers):
    """Persistence and provisioning tests for create_range()."""

    def test_creates_range_with_provisioning_status(self, valid_request_spec):
        """Service creates Range record with PROVISIONING status."""
        from django.contrib.auth import get_user_model

        from engine import create_range
        from engine.models import Range, Request

        User = get_user_model()
        mock_user = Mock(id=1)
        mock_range = Mock(spec=Range, id=42)
        mock_request = Mock(spec=Request)

        with (
            patch.object(User.objects, "get", return_value=mock_user),
            patch("engine.interpreter.interpret", return_value=mock_request),
            patch.object(Range.objects, "create", return_value=mock_range) as mock_create,
            patch.object(Range, "allocate_subnet_index", return_value=5),
            patch("engine.ecs.start_range_provisioning", return_value="arn:aws:ecs:test"),
            patch("engine.models.Subnet"),  # Mock Subnet.objects.filter().update()
        ):
            create_range(valid_request_spec)
            mock_create.assert_called_once()
            call_kwargs = mock_create.call_args.kwargs
            assert call_kwargs["status"] == Range.Status.PROVISIONING

    def test_allocates_subnet_index(self, valid_request_spec):
        """Service calls Range.allocate_subnet_index."""
        from django.contrib.auth import get_user_model

        from engine import create_range
        from engine.models import Range, Request

        User = get_user_model()
        mock_user = Mock(id=1)
        mock_range = Mock(spec=Range, id=42)
        mock_request = Mock(spec=Request)

        with (
            patch.object(User.objects, "get", return_value=mock_user),
            patch("engine.interpreter.interpret", return_value=mock_request),
            patch.object(Range.objects, "create", return_value=mock_range),
            patch.object(Range, "allocate_subnet_index", return_value=5) as mock_allocate,
            patch("engine.ecs.start_range_provisioning", return_value="arn:aws:ecs:test"),
            patch("engine.models.Subnet"),  # Mock Subnet.objects.filter().update()
        ):
            create_range(valid_request_spec)
            mock_allocate.assert_called_once()

    def test_starts_ecs_provisioning(self, valid_request_spec):
        """Service calls start_range_provisioning with request_id."""
        from django.contrib.auth import get_user_model

        from engine import create_range
        from engine.models import Range, Request

        User = get_user_model()
        mock_user = Mock(id=1)
        mock_range = Mock(spec=Range, id=42)
        mock_request = Mock(spec=Request)

        with (
            patch.object(User.objects, "get", return_value=mock_user),
            patch("engine.interpreter.interpret", return_value=mock_request),
            patch.object(Range.objects, "create", return_value=mock_range),
            patch.object(Range, "allocate_subnet_index", return_value=5),
            patch("engine.ecs.start_range_provisioning", return_value="arn:aws:ecs:test") as mock_start,
            patch("engine.models.Subnet"),  # Mock Subnet.objects.filter().update()
        ):
            create_range(valid_request_spec)
            mock_start.assert_called_once_with(valid_request_spec.request_id)


class TestCreateRangeReturnsAndLogging(_TestCreateRangeHelpers):
    """Return payload and logging tests for create_range()."""

    def test_returns_request_id(self, valid_request_spec):
        """Service returns request_id UUID."""
        from django.contrib.auth import get_user_model

        from engine import create_range
        from engine.models import Range, Request

        User = get_user_model()
        mock_user = Mock(id=1)
        mock_range = Mock(spec=Range, id=42)
        mock_request = Mock(spec=Request)

        with (
            patch.object(User.objects, "get", return_value=mock_user),
            patch("engine.interpreter.interpret", return_value=mock_request),
            patch.object(Range.objects, "create", return_value=mock_range),
            patch.object(Range, "allocate_subnet_index", return_value=5),
            patch("engine.ecs.start_range_provisioning", return_value="arn:aws:ecs:test"),
            patch("engine.models.Subnet"),  # Mock Subnet.objects.filter().update()
        ):
            result = create_range(valid_request_spec)
            assert result == valid_request_spec.request_id

    def test_logs_debug_on_entry(self, valid_request_spec, caplog):
        """Service logs debug on entry with range_config info."""
        from django.contrib.auth import get_user_model

        from engine import create_range
        from engine.models import Range, Request

        User = get_user_model()
        mock_user = Mock(id=1)
        mock_range = Mock(spec=Range, id=42)
        mock_request = Mock(spec=Request)

        with (
            patch.object(User.objects, "get", return_value=mock_user),
            patch("engine.interpreter.interpret", return_value=mock_request),
            patch.object(Range.objects, "create", return_value=mock_range),
            patch.object(Range, "allocate_subnet_index", return_value=5),
            patch("engine.ecs.start_range_provisioning", return_value="arn:aws:ecs:test"),
            patch("engine.models.Subnet"),  # Mock Subnet.objects.filter().update()
            caplog.at_level(logging.DEBUG, logger="engine"),
        ):
            create_range(valid_request_spec)

        assert "create_range" in caplog.text

    def test_logs_info_on_range_created(self, valid_request_spec, caplog):
        """Service logs info when range is created."""
        from django.contrib.auth import get_user_model

        from engine import create_range
        from engine.models import Range, Request

        User = get_user_model()
        mock_user = Mock(id=1)
        mock_range = Mock(spec=Range, id=42)
        mock_request = Mock(spec=Request)

        with (
            patch.object(User.objects, "get", return_value=mock_user),
            patch("engine.interpreter.interpret", return_value=mock_request),
            patch.object(Range.objects, "create", return_value=mock_range),
            patch.object(Range, "allocate_subnet_index", return_value=5),
            patch("engine.ecs.start_range_provisioning", return_value="arn:aws:ecs:test"),
            patch("engine.models.Subnet"),  # Mock Subnet.objects.filter().update()
            caplog.at_level(logging.INFO, logger="engine"),
        ):
            create_range(valid_request_spec)

        assert "42" in caplog.text


class TestCreateRangeErrorValidation(_TestCreateRangeHelpers):
    """Error and input validation tests for create_range()."""

    def test_propagates_subnet_allocation_error(self, valid_request_spec):
        """Service propagates ValueError from subnet allocation."""
        from django.contrib.auth import get_user_model

        from engine import create_range
        from engine.models import Range, Request

        User = get_user_model()
        mock_user = Mock(id=1)
        mock_request = Mock(spec=Request)

        with (
            patch.object(User.objects, "get", return_value=mock_user),
            patch("engine.interpreter.interpret", return_value=mock_request),
            patch.object(
                Range,
                "allocate_subnet_index",
                side_effect=ValueError("No subnets available"),
            ),
            pytest.raises(ValueError, match="No subnets available"),
        ):
            create_range(valid_request_spec)

    def test_propagates_database_error(self, valid_request_spec):
        """Service propagates DatabaseError from Range.create."""
        from django.contrib.auth import get_user_model
        from django.db import DatabaseError

        from engine import create_range
        from engine.models import Range, Request

        User = get_user_model()
        mock_user = Mock(id=1)
        mock_request = Mock(spec=Request)

        with (
            patch.object(User.objects, "get", return_value=mock_user),
            patch("engine.interpreter.interpret", return_value=mock_request),
            patch.object(Range, "allocate_subnet_index", return_value=5),
            patch.object(Range.objects, "create", side_effect=DatabaseError("DB error")),
            pytest.raises(DatabaseError),
        ):
            create_range(valid_request_spec)

    def test_propagates_ecs_client_error(self, valid_request_spec):
        """Service propagates ClientError from ECS."""
        from botocore.exceptions import ClientError
        from django.contrib.auth import get_user_model

        from engine import create_range
        from engine.models import Range, Request

        User = get_user_model()
        mock_user = Mock(id=1)
        mock_range = Mock(spec=Range, id=42)
        mock_request = Mock(spec=Request)

        with (
            patch.object(User.objects, "get", return_value=mock_user),
            patch("engine.interpreter.interpret", return_value=mock_request),
            patch.object(Range.objects, "create", return_value=mock_range),
            patch.object(Range, "allocate_subnet_index", return_value=5),
            patch(
                "engine.ecs.start_range_provisioning",
                side_effect=ClientError(
                    {"Error": {"Code": "AccessDenied", "Message": "Access Denied"}},
                    "RunTask",
                ),
            ),
            patch("engine.models.Subnet"),  # Mock Subnet.objects.filter().update()
            pytest.raises(ClientError),
        ):
            create_range(valid_request_spec)

    def test_raises_on_none_request(self):
        """Service raises error if request is None."""
        from engine import create_range

        with pytest.raises(TypeError):
            create_range(None)

    def test_raises_on_non_requestspec_request(self):
        """Service raises TypeError if request is not a RequestSpec."""
        from engine import create_range

        with pytest.raises(TypeError, match="must be RequestSpec"):
            create_range("not a RequestSpec")

    def test_raises_on_dict_instead_of_requestspec(self):
        """Service raises TypeError if dict passed instead of RequestSpec."""
        from engine import create_range

        with pytest.raises(TypeError, match="must be RequestSpec"):
            create_range({"user_id": 1, "scenario_id": "test"})
