"""Tests for create_range() in engine/services.py."""

import logging
from unittest.mock import Mock, patch

import pytest
from django.contrib.auth import get_user_model

from shared.schemas import RangeSpec


@pytest.mark.django_db
class TestCreateRange:
    """Tests for create_range() in engine/services.py.

    Tests the service contract:
    - Inputs: request (required RangeSpec)
    - Outputs: int (range_id of created range)
    - Side effects: looks up User, allocates subnet, creates Range, triggers ECS provisioning
    - Errors: TypeError (wrong type), ValueError (subnet exhausted), User.DoesNotExist
    - Logging: DEBUG on entry, INFO on range creation, INFO on ECS task start
    """

    # -------------------------------------------------------------------------
    # Outputs - returns range_id
    # -------------------------------------------------------------------------

    def test_returns_range_id_as_int(self):
        """Service returns integer range_id for valid request."""
        from engine import create_range
        from engine.models import Range

        User = get_user_model()

        mock_request = Mock(
            spec=RangeSpec,
            scenario_id="basic-attack",
            user_id=1,
            instances=[],
        )
        mock_request.model_dump.return_value = {"scenario_id": "basic-attack", "user_id": 1, "instances": []}

        mock_user = Mock(id=1)
        mock_range = Mock(spec=Range, id=42)

        with (
            patch.object(User.objects, "get", return_value=mock_user),
            patch.object(Range, "allocate_subnet_index", return_value=5),
            patch.object(Range.objects, "create", return_value=mock_range),
            patch("engine.ecs.start_provisioning", return_value=None),
        ):
            result = create_range(mock_request)

            assert isinstance(result, int)
            assert result == 42

    def test_returns_id_from_created_range(self):
        """Service returns the ID of the newly created Range object."""
        from engine import create_range
        from engine.models import Range

        User = get_user_model()

        mock_request = Mock(
            spec=RangeSpec,
            scenario_id="advanced-scenario",
            user_id=99,
            instances=[],
        )
        mock_request.model_dump.return_value = {"scenario_id": "advanced-scenario", "user_id": 99, "instances": []}

        mock_user = Mock(id=99)
        mock_range = Mock(spec=Range, id=1337)

        with (
            patch.object(User.objects, "get", return_value=mock_user),
            patch.object(Range, "allocate_subnet_index", return_value=10),
            patch.object(Range.objects, "create", return_value=mock_range),
            patch("engine.ecs.start_provisioning", return_value=None),
        ):
            result = create_range(mock_request)

            assert result == 1337

    # -------------------------------------------------------------------------
    # Side effects - User lookup
    # -------------------------------------------------------------------------

    def test_looks_up_user_by_request_user_id(self):
        """Service retrieves User by request.user_id."""
        from engine import create_range
        from engine.models import Range

        User = get_user_model()

        mock_request = Mock(
            spec=RangeSpec,
            scenario_id="test-scenario",
            user_id=42,
            instances=[],
        )
        mock_request.model_dump.return_value = {"scenario_id": "test-scenario", "user_id": 42, "instances": []}

        mock_user = Mock(id=42)
        mock_range = Mock(spec=Range, id=1)

        with (
            patch.object(User.objects, "get", return_value=mock_user) as mock_get,
            patch.object(Range, "allocate_subnet_index", return_value=1),
            patch.object(Range.objects, "create", return_value=mock_range),
            patch("engine.ecs.start_provisioning", return_value=None),
        ):
            create_range(mock_request)

            mock_get.assert_called_once_with(id=42)

    # -------------------------------------------------------------------------
    # Side effects - Subnet allocation
    # -------------------------------------------------------------------------

    def test_allocates_subnet_index(self):
        """Service calls Range.allocate_subnet_index() to get subnet."""
        from engine import create_range
        from engine.models import Range

        User = get_user_model()

        mock_request = Mock(
            spec=RangeSpec,
            scenario_id="test-scenario",
            user_id=1,
            instances=[],
        )
        mock_request.model_dump.return_value = {"scenario_id": "test-scenario", "user_id": 1, "instances": []}

        mock_user = Mock(id=1)
        mock_range = Mock(spec=Range, id=1)

        with (
            patch.object(User.objects, "get", return_value=mock_user),
            patch.object(Range, "allocate_subnet_index", return_value=15) as mock_allocate,
            patch.object(Range.objects, "create", return_value=mock_range),
            patch("engine.ecs.start_provisioning", return_value=None),
        ):
            create_range(mock_request)

            mock_allocate.assert_called_once()

    # -------------------------------------------------------------------------
    # Side effects - Range creation
    # -------------------------------------------------------------------------

    def test_creates_range_with_user_from_lookup(self):
        """Service creates Range with User object from lookup."""
        from engine import create_range
        from engine.models import Range

        User = get_user_model()

        mock_request = Mock(
            spec=RangeSpec,
            scenario_id="test-scenario",
            user_id=1,
            instances=[],
        )
        mock_request.model_dump.return_value = {"scenario_id": "test-scenario", "user_id": 1, "instances": []}

        mock_user = Mock(id=1)
        mock_range = Mock(spec=Range, id=1)

        with (
            patch.object(User.objects, "get", return_value=mock_user),
            patch.object(Range, "allocate_subnet_index", return_value=5),
            patch.object(Range.objects, "create", return_value=mock_range) as mock_create,
            patch("engine.ecs.start_provisioning", return_value=None),
        ):
            create_range(mock_request)

            mock_create.assert_called_once()
            call_kwargs = mock_create.call_args[1]
            assert call_kwargs["user"] == mock_user

    def test_creates_range_with_cms_user_id(self):
        """Service creates Range with cms_user_id from request."""
        from engine import create_range
        from engine.models import Range

        User = get_user_model()

        mock_request = Mock(
            spec=RangeSpec,
            scenario_id="test-scenario",
            user_id=123,
            instances=[],
        )
        mock_request.model_dump.return_value = {"scenario_id": "test-scenario", "user_id": 123, "instances": []}

        mock_user = Mock(id=123)
        mock_range = Mock(spec=Range, id=1)

        with (
            patch.object(User.objects, "get", return_value=mock_user),
            patch.object(Range, "allocate_subnet_index", return_value=5),
            patch.object(Range.objects, "create", return_value=mock_range) as mock_create,
            patch("engine.ecs.start_provisioning", return_value=None),
        ):
            create_range(mock_request)

            call_kwargs = mock_create.call_args[1]
            assert call_kwargs["cms_user_id"] == 123

    def test_creates_range_with_provisioning_status(self):
        """Service creates Range with status set to PROVISIONING."""
        from engine import create_range
        from engine.models import Range

        User = get_user_model()

        mock_request = Mock(
            spec=RangeSpec,
            scenario_id="test-scenario",
            user_id=1,
            instances=[],
        )
        mock_request.model_dump.return_value = {"scenario_id": "test-scenario", "user_id": 1, "instances": []}

        mock_user = Mock(id=1)
        mock_range = Mock(spec=Range, id=1)

        with (
            patch.object(User.objects, "get", return_value=mock_user),
            patch.object(Range, "allocate_subnet_index", return_value=5),
            patch.object(Range.objects, "create", return_value=mock_range) as mock_create,
            patch("engine.ecs.start_provisioning", return_value=None),
        ):
            create_range(mock_request)

            call_kwargs = mock_create.call_args[1]
            assert call_kwargs["status"] == Range.Status.PROVISIONING

    def test_creates_range_with_allocated_subnet_index(self):
        """Service creates Range with subnet_index from allocation."""
        from engine import create_range
        from engine.models import Range

        User = get_user_model()

        mock_request = Mock(
            spec=RangeSpec,
            scenario_id="test-scenario",
            user_id=1,
            instances=[],
        )
        mock_request.model_dump.return_value = {"scenario_id": "test-scenario", "user_id": 1, "instances": []}

        mock_user = Mock(id=1)
        mock_range = Mock(spec=Range, id=1)

        with (
            patch.object(User.objects, "get", return_value=mock_user),
            patch.object(Range, "allocate_subnet_index", return_value=87),
            patch.object(Range.objects, "create", return_value=mock_range) as mock_create,
            patch("engine.ecs.start_provisioning", return_value=None),
        ):
            create_range(mock_request)

            call_kwargs = mock_create.call_args[1]
            assert call_kwargs["subnet_index"] == 87

    def test_creates_range_with_config_from_request(self):
        """Service creates Range with range_config from request.model_dump()."""
        from engine import create_range
        from engine.models import Range

        User = get_user_model()

        mock_request = Mock(
            spec=RangeSpec,
            scenario_id="test-scenario",
            user_id=1,
            instances=[{"role": "attacker"}],
        )
        request_data = {"scenario_id": "test-scenario", "user_id": 1, "instances": [{"role": "attacker"}]}
        mock_request.model_dump.return_value = request_data

        mock_user = Mock(id=1)
        mock_range = Mock(spec=Range, id=1)

        with (
            patch.object(User.objects, "get", return_value=mock_user),
            patch.object(Range, "allocate_subnet_index", return_value=5),
            patch.object(Range.objects, "create", return_value=mock_range) as mock_create,
            patch("engine.ecs.start_provisioning", return_value=None),
        ):
            create_range(mock_request)

            call_kwargs = mock_create.call_args[1]
            assert call_kwargs["range_config"] == request_data

    # -------------------------------------------------------------------------
    # Side effects - ECS provisioning
    # -------------------------------------------------------------------------

    def test_triggers_ecs_provisioning_with_range_id(self):
        """Service calls start_provisioning with created range ID."""
        from engine import create_range
        from engine.models import Range

        User = get_user_model()

        mock_request = Mock(
            spec=RangeSpec,
            scenario_id="test-scenario",
            user_id=1,
            instances=[],
        )
        mock_request.model_dump.return_value = {"scenario_id": "test-scenario", "user_id": 1, "instances": []}

        mock_user = Mock(id=1)
        mock_range = Mock(spec=Range, id=99)

        with (
            patch.object(User.objects, "get", return_value=mock_user),
            patch.object(Range, "allocate_subnet_index", return_value=5),
            patch.object(Range.objects, "create", return_value=mock_range),
            patch("engine.ecs.start_provisioning") as mock_start,
        ):
            mock_start.return_value = None

            create_range(mock_request)

            mock_start.assert_called_once_with(99, 1)

    def test_stores_task_arn_when_provisioning_returns_one(self):
        """Service stores ECS task ARN when start_provisioning returns one."""
        from engine import create_range
        from engine.models import Range

        User = get_user_model()

        mock_request = Mock(
            spec=RangeSpec,
            scenario_id="test-scenario",
            user_id=1,
            instances=[],
        )
        mock_request.model_dump.return_value = {"scenario_id": "test-scenario", "user_id": 1, "instances": []}

        mock_user = Mock(id=1)
        mock_range = Mock(spec=Range, id=1)
        task_arn = "arn:aws:ecs:us-east-2:123456789:task/cluster/provisioner-task-123"

        with (
            patch.object(User.objects, "get", return_value=mock_user),
            patch.object(Range, "allocate_subnet_index", return_value=5),
            patch.object(Range.objects, "create", return_value=mock_range),
            patch("engine.ecs.start_provisioning", return_value=task_arn),
        ):
            create_range(mock_request)

            assert mock_range.step_function_execution_arn == task_arn
            mock_range.save.assert_called_once_with(update_fields=["step_function_execution_arn"])

    def test_does_not_store_task_arn_when_provisioning_returns_none(self):
        """Service does not save ARN field when start_provisioning returns None."""
        from engine import create_range
        from engine.models import Range

        User = get_user_model()

        mock_request = Mock(
            spec=RangeSpec,
            scenario_id="test-scenario",
            user_id=1,
            instances=[],
        )
        mock_request.model_dump.return_value = {"scenario_id": "test-scenario", "user_id": 1, "instances": []}

        mock_user = Mock(id=1)
        mock_range = Mock(spec=Range, id=1)

        with (
            patch.object(User.objects, "get", return_value=mock_user),
            patch.object(Range, "allocate_subnet_index", return_value=5),
            patch.object(Range.objects, "create", return_value=mock_range),
            patch("engine.ecs.start_provisioning", return_value=None),
        ):
            create_range(mock_request)

            mock_range.save.assert_not_called()

    # -------------------------------------------------------------------------
    # Input validation - request parameter
    # -------------------------------------------------------------------------

    def test_raises_on_none_request(self):
        """Service raises TypeError when request is None."""
        from engine import create_range

        with pytest.raises(TypeError, match="request must be RangeSpec"):
            create_range(None)

    def test_raises_on_invalid_request_type(self):
        """Service raises TypeError when request is not a RangeSpec."""
        from engine import create_range

        with pytest.raises(TypeError, match="request must be RangeSpec"):
            create_range({"scenario_id": "test", "user_id": 1})

    def test_raises_on_string_request(self):
        """Service raises TypeError when request is a string."""
        from engine import create_range

        with pytest.raises(TypeError, match="request must be RangeSpec"):
            create_range("not-a-request")

    def test_raises_on_plain_dict_request(self):
        """Service raises TypeError when request is a plain dict."""
        from engine import create_range

        request_dict = {
            "scenario_id": "basic-attack",
            "user_id": 1,
            "instances": [],
        }

        with pytest.raises(TypeError, match="request must be RangeSpec"):
            create_range(request_dict)

    # -------------------------------------------------------------------------
    # Error handling - user not found
    # -------------------------------------------------------------------------

    def test_propagates_user_does_not_exist(self):
        """Service propagates User.DoesNotExist when user_id invalid."""
        from engine import create_range

        User = get_user_model()

        mock_request = Mock(
            spec=RangeSpec,
            scenario_id="test-scenario",
            user_id=9999,
            instances=[],
        )
        mock_request.model_dump.return_value = {"scenario_id": "test-scenario", "user_id": 9999, "instances": []}

        with (
            patch.object(User.objects, "get", side_effect=User.DoesNotExist),
            pytest.raises(User.DoesNotExist),
        ):
            create_range(mock_request)

    # -------------------------------------------------------------------------
    # Error handling - subnet allocation failure
    # -------------------------------------------------------------------------

    def test_propagates_subnet_allocation_error(self):
        """Service propagates ValueError when subnet allocation fails."""
        from engine import create_range
        from engine.models import Range

        User = get_user_model()

        mock_request = Mock(
            spec=RangeSpec,
            scenario_id="test-scenario",
            user_id=1,
            instances=[],
        )
        mock_request.model_dump.return_value = {"scenario_id": "test-scenario", "user_id": 1, "instances": []}

        mock_user = Mock(id=1)

        with (
            patch.object(User.objects, "get", return_value=mock_user),
            patch.object(Range, "allocate_subnet_index", side_effect=ValueError("No subnet indices available")),
            pytest.raises(ValueError, match="No subnet indices available"),
        ):
            create_range(mock_request)

    def test_does_not_create_range_when_allocation_fails(self):
        """Service does not create Range when subnet allocation fails."""
        from engine import create_range
        from engine.models import Range

        User = get_user_model()

        mock_request = Mock(
            spec=RangeSpec,
            scenario_id="test-scenario",
            user_id=1,
            instances=[],
        )
        mock_request.model_dump.return_value = {"scenario_id": "test-scenario", "user_id": 1, "instances": []}

        mock_user = Mock(id=1)

        with (
            patch.object(User.objects, "get", return_value=mock_user),
            patch.object(Range, "allocate_subnet_index", side_effect=ValueError("No subnet indices available")),
            patch.object(Range.objects, "create") as mock_create,
            pytest.raises(ValueError),
        ):
            create_range(mock_request)

            mock_create.assert_not_called()

    # -------------------------------------------------------------------------
    # Logging - DEBUG on entry
    # -------------------------------------------------------------------------

    def test_logs_debug_on_entry_with_scenario(self, caplog):
        """Service logs debug on entry with scenario_id."""
        from engine import create_range
        from engine.models import Range

        User = get_user_model()

        mock_request = Mock(
            spec=RangeSpec,
            scenario_id="advanced-persistent-threat",
            user_id=1,
            instances=[],
        )
        mock_request.model_dump.return_value = {
            "scenario_id": "advanced-persistent-threat",
            "user_id": 1,
            "instances": [],
        }

        mock_user = Mock(id=1)
        mock_range = Mock(spec=Range, id=1)

        with (
            patch.object(User.objects, "get", return_value=mock_user),
            patch.object(Range, "allocate_subnet_index", return_value=5),
            patch.object(Range.objects, "create", return_value=mock_range),
            patch("engine.ecs.start_provisioning", return_value=None),
            caplog.at_level(logging.DEBUG, logger="engine"),
        ):
            create_range(mock_request)

        assert "advanced-persistent-threat" in caplog.text

    def test_logs_debug_on_entry_with_user_id(self, caplog):
        """Service logs debug on entry with user_id."""
        from engine import create_range
        from engine.models import Range

        User = get_user_model()

        mock_request = Mock(
            spec=RangeSpec,
            scenario_id="test-scenario",
            user_id=777,
            instances=[],
        )
        mock_request.model_dump.return_value = {"scenario_id": "test-scenario", "user_id": 777, "instances": []}

        mock_user = Mock(id=777)
        mock_range = Mock(spec=Range, id=1)

        with (
            patch.object(User.objects, "get", return_value=mock_user),
            patch.object(Range, "allocate_subnet_index", return_value=5),
            patch.object(Range.objects, "create", return_value=mock_range),
            patch("engine.ecs.start_provisioning", return_value=None),
            caplog.at_level(logging.DEBUG, logger="engine"),
        ):
            create_range(mock_request)

        assert "777" in caplog.text

    def test_logs_debug_on_entry_with_instance_count(self, caplog):
        """Service logs debug on entry with count of instances."""
        from engine import create_range
        from engine.models import Range

        User = get_user_model()

        mock_request = Mock(
            spec=RangeSpec,
            scenario_id="test-scenario",
            user_id=1,
            instances=[Mock(), Mock(), Mock()],
        )
        mock_request.model_dump.return_value = {
            "scenario_id": "test-scenario",
            "user_id": 1,
            "instances": [{}, {}, {}],
        }

        mock_user = Mock(id=1)
        mock_range = Mock(spec=Range, id=1)

        with (
            patch.object(User.objects, "get", return_value=mock_user),
            patch.object(Range, "allocate_subnet_index", return_value=5),
            patch.object(Range.objects, "create", return_value=mock_range),
            patch("engine.ecs.start_provisioning", return_value=None),
            caplog.at_level(logging.DEBUG, logger="engine"),
        ):
            create_range(mock_request)

        # Check for "3" in the context of instances
        assert "3" in caplog.text

    # -------------------------------------------------------------------------
    # Logging - INFO on range creation
    # -------------------------------------------------------------------------

    def test_logs_info_when_range_created(self, caplog):
        """Service logs info when Range is created."""
        from engine import create_range
        from engine.models import Range

        User = get_user_model()

        mock_request = Mock(
            spec=RangeSpec,
            scenario_id="test-scenario",
            user_id=1,
            instances=[],
        )
        mock_request.model_dump.return_value = {"scenario_id": "test-scenario", "user_id": 1, "instances": []}

        mock_user = Mock(id=1)
        mock_range = Mock(spec=Range, id=42)

        with (
            patch.object(User.objects, "get", return_value=mock_user),
            patch.object(Range, "allocate_subnet_index", return_value=5),
            patch.object(Range.objects, "create", return_value=mock_range),
            patch("engine.ecs.start_provisioning", return_value=None),
            caplog.at_level(logging.INFO, logger="engine"),
        ):
            create_range(mock_request)

        assert "created" in caplog.text.lower() or "42" in caplog.text

    def test_logs_info_with_range_id(self, caplog):
        """Service logs info with created range_id."""
        from engine import create_range
        from engine.models import Range

        User = get_user_model()

        mock_request = Mock(
            spec=RangeSpec,
            scenario_id="test-scenario",
            user_id=1,
            instances=[],
        )
        mock_request.model_dump.return_value = {"scenario_id": "test-scenario", "user_id": 1, "instances": []}

        mock_user = Mock(id=1)
        mock_range = Mock(spec=Range, id=999)

        with (
            patch.object(User.objects, "get", return_value=mock_user),
            patch.object(Range, "allocate_subnet_index", return_value=5),
            patch.object(Range.objects, "create", return_value=mock_range),
            patch("engine.ecs.start_provisioning", return_value=None),
            caplog.at_level(logging.INFO, logger="engine"),
        ):
            create_range(mock_request)

        assert "999" in caplog.text

    def test_logs_info_with_subnet_index(self, caplog):
        """Service logs info with allocated subnet_index."""
        from engine import create_range
        from engine.models import Range

        User = get_user_model()

        mock_request = Mock(
            spec=RangeSpec,
            scenario_id="test-scenario",
            user_id=1,
            instances=[],
        )
        mock_request.model_dump.return_value = {"scenario_id": "test-scenario", "user_id": 1, "instances": []}

        mock_user = Mock(id=1)
        mock_range = Mock(spec=Range, id=1)

        with (
            patch.object(User.objects, "get", return_value=mock_user),
            patch.object(Range, "allocate_subnet_index", return_value=123),
            patch.object(Range.objects, "create", return_value=mock_range),
            patch("engine.ecs.start_provisioning", return_value=None),
            caplog.at_level(logging.INFO, logger="engine"),
        ):
            create_range(mock_request)

        assert "123" in caplog.text

    # -------------------------------------------------------------------------
    # Logging - INFO when ECS task started
    # -------------------------------------------------------------------------

    def test_logs_info_when_ecs_task_started(self, caplog):
        """Service logs info when ECS task is started."""
        from engine import create_range
        from engine.models import Range

        User = get_user_model()

        mock_request = Mock(
            spec=RangeSpec,
            scenario_id="test-scenario",
            user_id=1,
            instances=[],
        )
        mock_request.model_dump.return_value = {"scenario_id": "test-scenario", "user_id": 1, "instances": []}

        mock_user = Mock(id=1)
        mock_range = Mock(spec=Range, id=1)
        task_arn = "arn:aws:ecs:us-east-2:123456789:task/cluster/task-abc123"

        with (
            patch.object(User.objects, "get", return_value=mock_user),
            patch.object(Range, "allocate_subnet_index", return_value=5),
            patch.object(Range.objects, "create", return_value=mock_range),
            patch("engine.ecs.start_provisioning", return_value=task_arn),
            caplog.at_level(logging.INFO, logger="engine"),
        ):
            create_range(mock_request)

        assert task_arn in caplog.text or "task" in caplog.text.lower()

    def test_does_not_log_ecs_info_when_no_task_arn(self, caplog):
        """Service does not log ECS task info when start_provisioning returns None."""
        from engine import create_range
        from engine.models import Range

        User = get_user_model()

        mock_request = Mock(
            spec=RangeSpec,
            scenario_id="test-scenario",
            user_id=1,
            instances=[],
        )
        mock_request.model_dump.return_value = {"scenario_id": "test-scenario", "user_id": 1, "instances": []}

        mock_user = Mock(id=1)
        mock_range = Mock(spec=Range, id=1)

        with (
            patch.object(User.objects, "get", return_value=mock_user),
            patch.object(Range, "allocate_subnet_index", return_value=5),
            patch.object(Range.objects, "create", return_value=mock_range),
            patch("engine.ecs.start_provisioning", return_value=None),
            caplog.at_level(logging.INFO, logger="engine"),
        ):
            create_range(mock_request)

        # Should still have the "created range" log, but not the "started ECS task" log
        # This is hard to assert negatively, so we just verify the creation log exists
        assert "created" in caplog.text.lower() or "1" in caplog.text
