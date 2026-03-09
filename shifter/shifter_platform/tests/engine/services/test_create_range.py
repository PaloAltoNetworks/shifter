"""Tests for create_range() in engine/services.py."""

import logging
from unittest.mock import Mock, patch
from uuid import UUID, uuid4

import pytest
from django.contrib.auth import get_user_model

from shared.schemas import InstanceSpec, RangeSpec, RequestSpec, SubnetSpec


def make_request_spec(
    scenario_id: str = "basic-attack",
    user_id: int = 1,
    subnets: list | None = None,
) -> RequestSpec:
    """Create a RequestSpec containing a RangeSpec for testing."""
    default_subnets = [
        SubnetSpec(
            name="default",
            uuid=str(uuid4()),
            instances=[InstanceSpec(role="attacker", os_type="kali", uuid=str(uuid4()))],
            connected_to=[],
        )
    ]
    range_spec = RangeSpec(
        uuid=str(uuid4()),
        scenario_id=scenario_id,
        user_id=user_id,
        subnets=subnets or default_subnets,
    )
    return RequestSpec(
        request_id=uuid4(),
        user_id=user_id,
        items=[range_spec],
    )


@pytest.mark.django_db
class TestCreateRange:
    """Tests for create_range() in engine/services.py.

    Tests the service contract:
    - Inputs: request_spec (required RequestSpec containing RangeSpec)
    - Outputs: UUID (request_id for correlation with CMS)
    - Side effects: interprets spec, looks up User, allocates subnet, creates Range, dispatches Celery task
    - Errors: TypeError (wrong type), ValueError (missing RangeSpec/subnet exhausted), User.DoesNotExist
    - Logging: DEBUG on entry, INFO on range creation, INFO on Celery task dispatch
    """

    # -------------------------------------------------------------------------
    # Outputs - returns request_id UUID
    # -------------------------------------------------------------------------

    def test_returns_request_id_as_uuid(self):
        """Service returns UUID request_id from the RequestSpec."""
        from engine import create_range
        from engine.models import Range

        User = get_user_model()

        request_spec = make_request_spec(user_id=1)
        mock_user = Mock(id=1)
        mock_range = Mock(spec=Range, id=42)
        mock_request = Mock(request_id=request_spec.request_id)

        with (
            patch("engine.interpreter.interpret", return_value=mock_request),
            patch.object(User.objects, "get", return_value=mock_user),
            patch.object(Range, "allocate_subnet_index", return_value=5),
            patch.object(Range.objects, "create", return_value=mock_range),
            patch("engine.tasks.provision_range"),
            patch("engine.models.Subnet"),
        ):
            result = create_range(request_spec)

            assert isinstance(result, UUID)
            assert result == request_spec.request_id

    # -------------------------------------------------------------------------
    # Side effects - User lookup
    # -------------------------------------------------------------------------

    def test_looks_up_user_by_range_spec_user_id(self):
        """Service retrieves User by RangeSpec.user_id."""
        from engine import create_range
        from engine.models import Range

        User = get_user_model()

        request_spec = make_request_spec(user_id=42)
        mock_user = Mock(id=42)
        mock_range = Mock(spec=Range, id=1)
        mock_request = Mock(request_id=request_spec.request_id)

        with (
            patch("engine.interpreter.interpret", return_value=mock_request),
            patch.object(User.objects, "get", return_value=mock_user) as mock_get,
            patch.object(Range, "allocate_subnet_index", return_value=1),
            patch.object(Range.objects, "create", return_value=mock_range),
            patch("engine.tasks.provision_range"),
            patch("engine.models.Subnet"),  # Mock Subnet.objects.filter().update()
        ):
            create_range(request_spec)

            mock_get.assert_called_once_with(id=42)

    # -------------------------------------------------------------------------
    # Side effects - Subnet allocation
    # -------------------------------------------------------------------------

    def test_allocates_subnet_index(self):
        """Service calls Range.allocate_subnet_index() to get subnet."""
        from engine import create_range
        from engine.models import Range

        User = get_user_model()

        request_spec = make_request_spec(user_id=1)
        mock_user = Mock(id=1)
        mock_range = Mock(spec=Range, id=1)
        mock_request = Mock(request_id=request_spec.request_id)

        with (
            patch("engine.interpreter.interpret", return_value=mock_request),
            patch.object(User.objects, "get", return_value=mock_user),
            patch.object(Range, "allocate_subnet_index", return_value=15) as mock_allocate,
            patch.object(Range.objects, "create", return_value=mock_range),
            patch("engine.tasks.provision_range"),
            patch("engine.models.Subnet"),  # Mock Subnet.objects.filter().update()
        ):
            create_range(request_spec)

            mock_allocate.assert_called_once()

    # -------------------------------------------------------------------------
    # Side effects - Range creation
    # -------------------------------------------------------------------------

    def test_creates_range_with_correct_kwargs(self):
        """Service creates Range with correct user, cms_user_id, status, subnet_index, and request."""
        from engine import create_range
        from engine.models import Range

        User = get_user_model()

        request_spec = make_request_spec(user_id=123)
        mock_user = Mock(id=123)
        mock_range = Mock(spec=Range, id=1)
        mock_request = Mock(request_id=request_spec.request_id)

        with (
            patch("engine.interpreter.interpret", return_value=mock_request),
            patch.object(User.objects, "get", return_value=mock_user),
            patch.object(Range, "allocate_subnet_index", return_value=87),
            patch.object(Range.objects, "create", return_value=mock_range) as mock_create,
            patch("engine.tasks.provision_range"),
            patch("engine.models.Subnet"),
        ):
            create_range(request_spec)

            mock_create.assert_called_once()
            call_kwargs = mock_create.call_args[1]
            assert call_kwargs["user"] == mock_user
            assert call_kwargs["cms_user_id"] == 123
            assert call_kwargs["status"] == Range.Status.PROVISIONING
            assert call_kwargs["subnet_index"] == 87
            assert call_kwargs["request"] == mock_request

    # -------------------------------------------------------------------------
    # Side effects - Celery task dispatch
    # -------------------------------------------------------------------------

    def test_dispatches_celery_provision_task_with_request_id(self):
        """Service dispatches provision_range Celery task with request_id."""
        from engine import create_range
        from engine.models import Range

        User = get_user_model()

        request_spec = make_request_spec(user_id=1)
        mock_user = Mock(id=1)
        mock_range = Mock(spec=Range, id=99)
        mock_request = Mock(request_id=request_spec.request_id)

        with (
            patch("engine.interpreter.interpret", return_value=mock_request),
            patch.object(User.objects, "get", return_value=mock_user),
            patch.object(Range, "allocate_subnet_index", return_value=5),
            patch.object(Range.objects, "create", return_value=mock_range),
            patch("engine.tasks.provision_range") as mock_provision_task,
            patch("engine.models.Subnet"),  # Mock Subnet.objects.filter().update()
        ):
            create_range(request_spec)

            mock_provision_task.delay.assert_called_once_with(str(request_spec.request_id))

    # -------------------------------------------------------------------------
    # Input validation - request_spec parameter
    # -------------------------------------------------------------------------

    def test_validates_request_spec_type(self):
        """Service raises TypeError for invalid request_spec types."""
        from engine import create_range

        # None, dict, string
        for invalid in [None, {"scenario_id": "test", "user_id": 1}, "not-a-request"]:
            with pytest.raises(TypeError, match="request_spec must be RequestSpec"):
                create_range(invalid)

        # RangeSpec directly (old API)
        range_spec = RangeSpec(
            scenario_id="basic-attack",
            user_id=1,
            subnets=[
                SubnetSpec(
                    name="default",
                    uuid=str(uuid4()),
                    instances=[InstanceSpec(role="attacker", os_type="kali", uuid=str(uuid4()))],
                )
            ],
        )
        with pytest.raises(TypeError, match="request_spec must be RequestSpec"):
            create_range(range_spec)

    def test_raises_on_request_spec_without_range_spec(self):
        """Service raises ValueError when RequestSpec has no RangeSpec item."""
        from engine import create_range

        request_spec = RequestSpec(
            request_id=uuid4(),
            user_id=1,
            items=[],  # No RangeSpec
        )

        with pytest.raises(ValueError, match="must contain a RangeSpec"):
            create_range(request_spec)

    # -------------------------------------------------------------------------
    # Error handling - user not found
    # -------------------------------------------------------------------------

    def test_propagates_user_does_not_exist(self):
        """Service propagates User.DoesNotExist when user_id invalid."""
        from engine import create_range

        User = get_user_model()

        request_spec = make_request_spec(user_id=9999)
        mock_request = Mock(request_id=request_spec.request_id)

        with (
            patch("engine.interpreter.interpret", return_value=mock_request),
            patch.object(User.objects, "get", side_effect=User.DoesNotExist),
            pytest.raises(User.DoesNotExist),
        ):
            create_range(request_spec)

    # -------------------------------------------------------------------------
    # Error handling - subnet allocation failure
    # -------------------------------------------------------------------------

    def test_propagates_subnet_allocation_error(self):
        """Service propagates ValueError when subnet allocation fails."""
        from engine import create_range
        from engine.models import Range

        User = get_user_model()

        request_spec = make_request_spec(user_id=1)
        mock_user = Mock(id=1)
        mock_request = Mock(request_id=request_spec.request_id)

        with (
            patch("engine.interpreter.interpret", return_value=mock_request),
            patch.object(User.objects, "get", return_value=mock_user),
            patch.object(Range, "allocate_subnet_index", side_effect=ValueError("No subnet indices available")),
            pytest.raises(ValueError, match="No subnet indices available"),
        ):
            create_range(request_spec)

    def test_does_not_create_range_when_allocation_fails(self):
        """Service does not create Range when subnet allocation fails."""
        from engine import create_range
        from engine.models import Range

        User = get_user_model()

        request_spec = make_request_spec(user_id=1)
        mock_user = Mock(id=1)
        mock_request = Mock(request_id=request_spec.request_id)

        with (
            patch("engine.interpreter.interpret", return_value=mock_request),
            patch.object(User.objects, "get", return_value=mock_user),
            patch.object(Range, "allocate_subnet_index", side_effect=ValueError("No subnet indices available")),
            patch.object(Range.objects, "create") as mock_create,
            pytest.raises(ValueError),
        ):
            create_range(request_spec)

            mock_create.assert_not_called()

    # -------------------------------------------------------------------------
    # Logging - DEBUG on entry
    # -------------------------------------------------------------------------

    def test_logs_debug_on_entry(self, caplog):
        """Service logs debug on entry with scenario_id and user_id."""
        from engine import create_range
        from engine.models import Range

        User = get_user_model()

        request_spec = make_request_spec(scenario_id="advanced-persistent-threat", user_id=777)
        mock_user = Mock(id=777)
        mock_range = Mock(spec=Range, id=1)
        mock_request = Mock(request_id=request_spec.request_id)

        with (
            patch("engine.interpreter.interpret", return_value=mock_request),
            patch.object(User.objects, "get", return_value=mock_user),
            patch.object(Range, "allocate_subnet_index", return_value=5),
            patch.object(Range.objects, "create", return_value=mock_range),
            patch("engine.tasks.provision_range"),
            patch("engine.models.Subnet"),
            caplog.at_level(logging.DEBUG, logger="engine"),
        ):
            create_range(request_spec)

        assert "advanced-persistent-threat" in caplog.text
        assert "777" in caplog.text

    # -------------------------------------------------------------------------
    # Logging - INFO on range creation
    # -------------------------------------------------------------------------

    def test_logs_info_when_range_created(self, caplog):
        """Service logs info with range_id and subnet_index when Range is created."""
        from engine import create_range
        from engine.models import Range

        User = get_user_model()

        request_spec = make_request_spec(user_id=1)
        mock_user = Mock(id=1)
        mock_range = Mock(spec=Range, id=999)
        mock_request = Mock(request_id=request_spec.request_id)

        with (
            patch("engine.interpreter.interpret", return_value=mock_request),
            patch.object(User.objects, "get", return_value=mock_user),
            patch.object(Range, "allocate_subnet_index", return_value=123),
            patch.object(Range.objects, "create", return_value=mock_range),
            patch("engine.tasks.provision_range"),
            patch("engine.models.Subnet"),
            caplog.at_level(logging.INFO, logger="engine"),
        ):
            create_range(request_spec)

        assert "999" in caplog.text
        assert "123" in caplog.text

    # -------------------------------------------------------------------------
    # Logging - INFO when Celery task dispatched
    # -------------------------------------------------------------------------

    def test_logs_info_when_celery_task_dispatched(self, caplog):
        """Service logs info when Celery task is dispatched."""
        from engine import create_range
        from engine.models import Range

        User = get_user_model()

        request_spec = make_request_spec(user_id=1)
        mock_user = Mock(id=1)
        mock_range = Mock(spec=Range, id=1)
        mock_request = Mock(request_id=request_spec.request_id)

        with (
            patch("engine.interpreter.interpret", return_value=mock_request),
            patch.object(User.objects, "get", return_value=mock_user),
            patch.object(Range, "allocate_subnet_index", return_value=5),
            patch.object(Range.objects, "create", return_value=mock_range),
            patch("engine.tasks.provision_range"),
            patch("engine.models.Subnet"),
            caplog.at_level(logging.INFO, logger="engine"),
        ):
            create_range(request_spec)

        assert "celery" in caplog.text.lower() or "task" in caplog.text.lower()
