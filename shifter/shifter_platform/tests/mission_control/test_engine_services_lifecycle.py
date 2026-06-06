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
        from uuid import uuid4

        from shared.enums import ResourceStatus
        from shared.schemas import RangeContext

        return RangeContext(
            request_id=uuid4(),
            range_id=42,
            user_id=1,
            scenario_id="test-scenario",
            status=ResourceStatus.READY,
            instances=[],
        )

    # -------------------------------------------------------------------------
    # Service updates Range correctly
    # -------------------------------------------------------------------------

    def test_sets_status_to_destroying(self, range_context):
        """Service sets Range status to DESTROYING."""
        from engine import destroy_range
        from engine.models import Range
        from shared.enums import ResourceStatus

        mock_range = Mock(spec=Range, id=42, status=Range.Status.READY)

        with (
            patch.object(Range.objects, "get", return_value=mock_range),
            patch("engine.ecs.start_teardown", return_value="arn:aws:ecs:test"),
        ):
            destroy_range(range_context)
            assert mock_range.status == ResourceStatus.DESTROYING.value
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
        from shared.enums import ResourceStatus

        mock_range = Mock(spec=Range, id=42, status=ResourceStatus.DESTROYED)

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
        from shared.enums import ResourceStatus

        mock_range = Mock(spec=Range, id=42, status=ResourceStatus.DESTROYING)

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
                side_effect=ClientError(
                    {"Error": {"Code": "AccessDenied", "Message": "Access Denied"}},
                    "RunTask",
                ),
            ),
            pytest.raises(ClientError),
        ):
            destroy_range(range_context)


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
        from uuid import uuid4

        from shared.enums import ResourceStatus
        from shared.schemas import RangeContext

        return RangeContext(
            request_id=uuid4(),
            range_id=42,
            user_id=1,
            scenario_id="test-scenario",
            status=ResourceStatus.PENDING,
            instances=[],
        )

    @pytest.fixture
    def provisioning_range_context(self):
        """Return a RangeContext for a provisioning range."""
        from uuid import uuid4

        from shared.enums import ResourceStatus
        from shared.schemas import RangeContext

        return RangeContext(
            request_id=uuid4(),
            range_id=42,
            user_id=1,
            scenario_id="test-scenario",
            status=ResourceStatus.PROVISIONING,
            instances=[],
        )

    @pytest.fixture
    def ready_range_context(self):
        """Return a RangeContext for a ready range (not cancellable)."""
        from uuid import uuid4

        from shared.enums import ResourceStatus
        from shared.schemas import RangeContext

        return RangeContext(
            request_id=uuid4(),
            range_id=42,
            user_id=1,
            scenario_id="test-scenario",
            status=ResourceStatus.READY,
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
