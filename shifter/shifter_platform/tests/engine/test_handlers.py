"""Tests for Engine handlers."""

import json
import logging
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model

from shared.enums import ResourceStatus

User = get_user_model()


@pytest.mark.django_db
class TestProcessEvent:
    """Tests for process_event dispatcher."""

    def test_routes_range_events_to_range_handler(self):
        """Dispatcher routes range.* events to process_range_event."""
        from engine.handlers import process_event

        message = {
            "Message": json.dumps(
                {
                    "event_type": "range.status.updated",
                    "range_id": 1,
                    "user_id": 42,
                }
            )
        }

        with patch("engine.handlers.process_range_event") as mock_range_handler:
            process_event(message)
            mock_range_handler.assert_called_once_with(message)

    def test_routes_ngfw_events_to_ngfw_handler(self):
        """Dispatcher routes ngfw.* events to process_ngfw_event."""
        from engine.handlers import process_event

        message = {
            "Message": json.dumps(
                {
                    "event_type": "ngfw.status.updated",
                    "ngfw_id": 1,
                    "user_id": 42,
                }
            )
        }

        with patch("engine.handlers.process_ngfw_event") as mock_ngfw_handler:
            process_event(message)
            mock_ngfw_handler.assert_called_once_with(message)

    def test_ignores_unknown_event_types(self, caplog):
        """Dispatcher ignores events with unknown event_type prefix."""
        from engine.handlers import process_event

        message = {
            "Message": json.dumps(
                {
                    "event_type": "unknown.event",
                    "some_id": 1,
                }
            )
        }

        with (
            caplog.at_level(logging.DEBUG, logger="engine.handlers"),
            patch("engine.handlers.process_range_event") as mock_range_handler,
            patch("engine.handlers.process_ngfw_event") as mock_ngfw_handler,
        ):
            process_event(message)
            mock_range_handler.assert_not_called()
            mock_ngfw_handler.assert_not_called()
            assert "Ignoring unknown event_type" in caplog.text

    def test_handles_missing_event_type(self, caplog):
        """Dispatcher handles messages without event_type gracefully."""
        from engine.handlers import process_event

        message = {"Message": json.dumps({"range_id": 1})}

        with (
            caplog.at_level(logging.DEBUG, logger="engine.handlers"),
            patch("engine.handlers.process_range_event") as mock_range_handler,
            patch("engine.handlers.process_ngfw_event") as mock_ngfw_handler,
        ):
            process_event(message)
            mock_range_handler.assert_not_called()
            mock_ngfw_handler.assert_not_called()

    def test_dispatcher_is_callable(self):
        """Dispatcher is a callable function."""
        from engine.handlers import process_event

        assert callable(process_event)


@pytest.mark.django_db
class TestParseSnsMessage:
    """Tests for parse_sns_message helper."""

    def test_parses_sns_wrapped_message(self):
        """Function unwraps SNS envelope to get event payload."""
        from engine.handlers import parse_sns_message

        sns_message = {
            "Message": json.dumps(
                {
                    "event_type": "range.status.updated",
                    "range_id": 1,
                    "user_id": 42,
                }
            )
        }

        result = parse_sns_message(sns_message)

        assert result["event_type"] == "range.status.updated"
        assert result["range_id"] == 1
        assert result["user_id"] == 42

    def test_parses_string_input(self):
        """Function parses string JSON input."""
        from engine.handlers import parse_sns_message

        sns_message = json.dumps(
            {
                "Message": json.dumps(
                    {
                        "event_type": "range.status.updated",
                        "range_id": 1,
                    }
                )
            }
        )

        result = parse_sns_message(sns_message)

        assert result["event_type"] == "range.status.updated"
        assert result["range_id"] == 1

    def test_handles_non_wrapped_message(self):
        """Function handles direct event payload (no SNS wrapper)."""
        from engine.handlers import parse_sns_message

        direct_message = {
            "event_type": "range.status.updated",
            "range_id": 1,
            "user_id": 42,
        }

        result = parse_sns_message(direct_message)

        assert result["event_type"] == "range.status.updated"
        assert result["range_id"] == 1


@pytest.fixture
def user():
    """Create a test user."""
    return User.objects.create_user(username="testuser", password="testpass")


@pytest.mark.django_db
class TestProcessRangeEvent:
    """Tests for process_range_event handler."""

    # ---------------------------------------------------------------------
    # Happy path - status update
    # ---------------------------------------------------------------------

    def test_updates_range_status(self, user):
        """Handler updates Range.status from event."""
        from engine.handlers import process_range_event
        from engine.models import Range

        range_obj = Range.objects.create(
            user=user,
            status=ResourceStatus.PENDING.value,
        )

        message = {
            "Message": json.dumps(
                {
                    "event_type": "range.status.updated",
                    "range_id": range_obj.id,
                    "new_status": ResourceStatus.PROVISIONING.value,
                    "user_id": user.id,
                }
            )
        }

        process_range_event(message)

        range_obj.refresh_from_db()
        assert range_obj.status == ResourceStatus.PROVISIONING.value

    def test_sets_ready_at_on_ready_status(self, user):
        """Handler sets ready_at when transitioning to READY."""
        from engine.handlers import process_range_event
        from engine.models import Range

        range_obj = Range.objects.create(
            user=user,
            status=ResourceStatus.PROVISIONING.value,
        )
        assert range_obj.ready_at is None

        message = {
            "Message": json.dumps(
                {
                    "event_type": "range.status.updated",
                    "range_id": range_obj.id,
                    "new_status": ResourceStatus.READY.value,
                    "user_id": user.id,
                }
            )
        }

        process_range_event(message)

        range_obj.refresh_from_db()
        assert range_obj.status == ResourceStatus.READY.value
        assert range_obj.ready_at is not None

    def test_sets_destroyed_at_on_destroyed_status(self, user):
        """Handler sets destroyed_at when transitioning to DESTROYED."""
        from engine.handlers import process_range_event
        from engine.models import Range

        range_obj = Range.objects.create(
            user=user,
            status=ResourceStatus.DESTROYING.value,
        )
        assert range_obj.destroyed_at is None

        message = {
            "Message": json.dumps(
                {
                    "event_type": "range.status.updated",
                    "range_id": range_obj.id,
                    "new_status": ResourceStatus.DESTROYED.value,
                    "user_id": user.id,
                }
            )
        }

        process_range_event(message)

        range_obj.refresh_from_db()
        assert range_obj.status == ResourceStatus.DESTROYED.value
        assert range_obj.destroyed_at is not None

    def test_stores_error_message_on_failed_status(self, user):
        """Handler stores error_message when transitioning to FAILED."""
        from engine.handlers import process_range_event
        from engine.models import Range

        range_obj = Range.objects.create(
            user=user,
            status=ResourceStatus.PROVISIONING.value,
        )

        message = {
            "Message": json.dumps(
                {
                    "event_type": "range.status.updated",
                    "range_id": range_obj.id,
                    "new_status": ResourceStatus.FAILED.value,
                    "user_id": user.id,
                    "error_message": "Subnet exhausted",
                }
            )
        }

        process_range_event(message)

        range_obj.refresh_from_db()
        assert range_obj.status == ResourceStatus.FAILED.value
        assert range_obj.error_message == "Subnet exhausted"

    # ---------------------------------------------------------------------
    # Event filtering
    # ---------------------------------------------------------------------

    def test_ignores_unknown_event_types(self, user, caplog):
        """Handler ignores events that are not recognized."""
        from engine.handlers import process_range_event
        from engine.models import Range

        range_obj = Range.objects.create(
            user=user,
            status=ResourceStatus.PENDING.value,
        )

        message = {
            "Message": json.dumps(
                {
                    "event_type": "range.unknown_event",
                    "range_id": range_obj.id,
                    "user_id": user.id,
                }
            )
        }

        with caplog.at_level(logging.DEBUG, logger="engine.handlers"):
            process_range_event(message)

        assert "Ignoring event_type" in caplog.text

        # Status should be unchanged
        range_obj.refresh_from_db()
        assert range_obj.status == ResourceStatus.PENDING.value

    # ---------------------------------------------------------------------
    # Error handling - missing data
    # ---------------------------------------------------------------------

    def test_handles_missing_range(self, caplog):
        """Handler logs warning when Range not found."""
        from engine.handlers import process_range_event

        message = {
            "Message": json.dumps(
                {
                    "event_type": "range.status.updated",
                    "range_id": 999999,
                    "new_status": ResourceStatus.READY.value,
                    "user_id": 42,
                }
            )
        }

        with caplog.at_level(logging.WARNING, logger="engine.handlers"):
            process_range_event(message)

        assert "Range not found" in caplog.text
        assert "999999" in caplog.text

    def test_handles_user_id_mismatch(self, user, caplog):
        """Handler logs error when user_id doesn't match Range."""
        from engine.handlers import process_range_event
        from engine.models import Range

        range_obj = Range.objects.create(
            user=user,
            status=ResourceStatus.PENDING.value,
        )

        message = {
            "Message": json.dumps(
                {
                    "event_type": "range.status.updated",
                    "range_id": range_obj.id,
                    "new_status": ResourceStatus.READY.value,
                    "user_id": 999999,  # Wrong user
                }
            )
        }

        with caplog.at_level(logging.ERROR, logger="engine.handlers"):
            process_range_event(message)

        assert "user_id mismatch" in caplog.text
        assert "999999" in caplog.text

        # Status should be unchanged
        range_obj.refresh_from_db()
        assert range_obj.status == ResourceStatus.PENDING.value

    # ---------------------------------------------------------------------
    # Error handling - database failures
    # ---------------------------------------------------------------------

    def test_logs_exception_on_database_error(self, user, caplog):
        """Handler logs exception when database save fails."""
        from engine.handlers import process_range_event
        from engine.models import Range

        range_obj = Range.objects.create(
            user=user,
            status=ResourceStatus.PENDING.value,
        )

        message = {
            "Message": json.dumps(
                {
                    "event_type": "range.status.updated",
                    "range_id": range_obj.id,
                    "new_status": ResourceStatus.PROVISIONING.value,
                    "user_id": user.id,
                }
            )
        }

        with (
            caplog.at_level(logging.ERROR, logger="engine.handlers"),
            patch.object(Range, "save", side_effect=Exception("DB down")),
        ):
            process_range_event(message)

        assert "DB error saving Range" in caplog.text
        assert f"range_id={range_obj.id}" in caplog.text

    # ---------------------------------------------------------------------
    # Logging - success
    # ---------------------------------------------------------------------

    def test_logs_info_on_successful_update(self, user, caplog):
        """Handler logs INFO when status successfully updated."""
        from engine.handlers import process_range_event
        from engine.models import Range

        range_obj = Range.objects.create(
            user=user,
            status=ResourceStatus.PENDING.value,
        )

        message = {
            "Message": json.dumps(
                {
                    "event_type": "range.status.updated",
                    "range_id": range_obj.id,
                    "new_status": ResourceStatus.PROVISIONING.value,
                    "user_id": user.id,
                }
            )
        }

        with caplog.at_level(logging.INFO, logger="engine.handlers"):
            process_range_event(message)

        assert "Engine updated Range" in caplog.text
        assert f"range_id={range_obj.id}" in caplog.text
        assert "pending" in caplog.text
        assert "provisioning" in caplog.text

    def test_logs_debug_on_event_ignore(self, caplog):
        """Handler logs DEBUG when ignoring non-status events."""
        from engine.handlers import process_range_event

        message = {
            "Message": json.dumps(
                {
                    "event_type": "range.destroyed",
                    "range_id": 1,
                    "user_id": 42,
                }
            )
        }

        with caplog.at_level(logging.DEBUG, logger="engine.handlers"):
            process_range_event(message)

        assert "Ignoring event_type" in caplog.text
        assert "range.destroyed" in caplog.text

    # ---------------------------------------------------------------------
    # Handler is callable
    # ---------------------------------------------------------------------

    def test_handler_is_callable(self):
        """Handler is a callable function."""
        from engine.handlers import process_range_event

        assert callable(process_range_event)

    # ---------------------------------------------------------------------
    # Minimum required input
    # ---------------------------------------------------------------------

    def test_succeeds_with_minimum_required_input(self, user):
        """Handler works with minimal event fields."""
        from engine.handlers import process_range_event
        from engine.models import Range

        range_obj = Range.objects.create(
            user=user,
            status=ResourceStatus.PENDING.value,
        )

        # Minimal SNS message - no error_message
        message = {
            "Message": json.dumps(
                {
                    "event_type": "range.status.updated",
                    "range_id": range_obj.id,
                    "new_status": ResourceStatus.PROVISIONING.value,
                    "user_id": user.id,
                }
            )
        }

        process_range_event(message)

        range_obj.refresh_from_db()
        assert range_obj.status == ResourceStatus.PROVISIONING.value

    def test_failed_without_error_message(self, user):
        """Handler handles FAILED status even without error_message."""
        from engine.handlers import process_range_event
        from engine.models import Range

        range_obj = Range.objects.create(
            user=user,
            status=ResourceStatus.PROVISIONING.value,
        )

        message = {
            "Message": json.dumps(
                {
                    "event_type": "range.status.updated",
                    "range_id": range_obj.id,
                    "new_status": ResourceStatus.FAILED.value,
                    "user_id": user.id,
                    # No error_message
                }
            )
        }

        process_range_event(message)

        range_obj.refresh_from_db()
        assert range_obj.status == ResourceStatus.FAILED.value
        assert range_obj.error_message == ""  # Default empty string


@pytest.mark.django_db
class TestHandleProvisioned:
    """Tests for _handle_provisioned handler."""

    # ---------------------------------------------------------------------
    # Happy path - provisioned event processing
    # ---------------------------------------------------------------------

    def test_updates_provisioned_instances(self, user):
        """Handler updates provisioned_instances from event."""
        from engine.handlers import process_range_event
        from engine.models import Range

        range_obj = Range.objects.create(
            user=user,
            status=ResourceStatus.PROVISIONING.value,
            range_config={
                "scenario_id": "basic",
                "user_id": user.id,
                "instances": [
                    {
                        "uuid": "uuid-attacker-123",
                        "role": "attacker",
                        "os_type": "kali",
                    },
                    {"uuid": "uuid-victim-456", "role": "victim", "os_type": "ubuntu"},
                ],
            },
        )

        message = {
            "Message": json.dumps(
                {
                    "event_type": "range.provisioned",
                    "range_id": range_obj.id,
                    "user_id": user.id,
                    "instances": [
                        {
                            "role": "attacker",
                            "os": "kali",
                            "instance_id": "i-attacker123",
                            "private_ip": "10.1.2.10",
                            "ssh_key_secret_arn": "arn:aws:secretsmanager:us-east-2:123:secret:ssh-key-attacker",
                        },
                        {
                            "role": "victim",
                            "os": "ubuntu",
                            "instance_id": "i-victim456",
                            "private_ip": "10.1.2.20",
                            "ssh_key_secret_arn": "arn:aws:secretsmanager:us-east-2:123:secret:ssh-key-victim",
                        },
                    ],
                    "subnet_id": "subnet-123",
                    "subnet_cidr": "10.1.2.0/24",
                    "pulumi_stack": "range-42",
                }
            )
        }

        process_range_event(message)

        range_obj.refresh_from_db()
        assert range_obj.provisioned_instances is not None
        assert len(range_obj.provisioned_instances) == 2

        # Check that UUIDs from range_config are merged with provisioner data
        attacker = next(i for i in range_obj.provisioned_instances if i["role"] == "attacker")
        assert attacker["uuid"] == "uuid-attacker-123"
        assert attacker["instance_id"] == "i-attacker123"
        assert attacker["private_ip"] == "10.1.2.10"
        assert attacker["ssh_key_secret_arn"] == "arn:aws:secretsmanager:us-east-2:123:secret:ssh-key-attacker"

        victim = next(i for i in range_obj.provisioned_instances if i["role"] == "victim")
        assert victim["uuid"] == "uuid-victim-456"
        assert victim["instance_id"] == "i-victim456"
        assert victim["private_ip"] == "10.1.2.20"

        # Check other fields
        assert range_obj.subnet_id == "subnet-123"
        assert range_obj.subnet_cidr == "10.1.2.0/24"
        assert range_obj.pulumi_stack == "range-42"

    def test_handles_missing_range_config(self, user):
        """Handler works even if range_config is empty (UUIDs will be None)."""
        from engine.handlers import process_range_event
        from engine.models import Range

        range_obj = Range.objects.create(
            user=user,
            status=ResourceStatus.PROVISIONING.value,
            range_config=None,  # No range_config
        )

        message = {
            "Message": json.dumps(
                {
                    "event_type": "range.provisioned",
                    "range_id": range_obj.id,
                    "user_id": user.id,
                    "instances": [
                        {
                            "role": "attacker",
                            "os": "kali",
                            "instance_id": "i-attacker123",
                            "private_ip": "10.1.2.10",
                            "ssh_key_secret_arn": "arn:aws:secretsmanager:us-east-2:123:secret:ssh-key",
                        },
                    ],
                }
            )
        }

        process_range_event(message)

        range_obj.refresh_from_db()
        assert range_obj.provisioned_instances is not None
        assert len(range_obj.provisioned_instances) == 1
        # UUID will be None since no range_config
        assert range_obj.provisioned_instances[0]["uuid"] is None
        assert range_obj.provisioned_instances[0]["instance_id"] == "i-attacker123"

    def test_get_instance_by_uuid_works_after_provisioned(self, user):
        """After processing provisioned event, get_instance_by_uuid returns correct data."""
        from engine.handlers import process_range_event
        from engine.models import Range

        range_obj = Range.objects.create(
            user=user,
            status=ResourceStatus.PROVISIONING.value,
            range_config={
                "scenario_id": "basic",
                "user_id": user.id,
                "instances": [
                    {
                        "uuid": "uuid-attacker-123",
                        "role": "attacker",
                        "os_type": "kali",
                    },
                ],
            },
        )

        message = {
            "Message": json.dumps(
                {
                    "event_type": "range.provisioned",
                    "range_id": range_obj.id,
                    "user_id": user.id,
                    "instances": [
                        {
                            "role": "attacker",
                            "os": "kali",
                            "instance_id": "i-attacker123",
                            "private_ip": "10.1.2.10",
                            "ssh_key_secret_arn": "arn:aws:secretsmanager:us-east-2:123:secret:ssh-key",
                        },
                    ],
                }
            )
        }

        process_range_event(message)

        range_obj.refresh_from_db()
        # This is the actual lookup used by connect_terminal
        instance = range_obj.get_instance_by_uuid("uuid-attacker-123")
        assert instance is not None
        assert instance["private_ip"] == "10.1.2.10"
        assert instance["ssh_key_secret_arn"] == "arn:aws:secretsmanager:us-east-2:123:secret:ssh-key"

    # ---------------------------------------------------------------------
    # Error handling
    # ---------------------------------------------------------------------

    def test_handles_missing_range(self, caplog):
        """Handler logs warning when Range not found for provisioned event."""
        from engine.handlers import process_range_event

        message = {
            "Message": json.dumps(
                {
                    "event_type": "range.provisioned",
                    "range_id": 999999,
                    "user_id": 42,
                    "instances": [],
                }
            )
        }

        with caplog.at_level(logging.WARNING, logger="engine.handlers"):
            process_range_event(message)

        assert "Range not found for provisioned event" in caplog.text
        assert "999999" in caplog.text

    def test_handles_user_id_mismatch(self, user, caplog):
        """Handler logs error when user_id doesn't match Range."""
        from engine.handlers import process_range_event
        from engine.models import Range

        range_obj = Range.objects.create(
            user=user,
            status=ResourceStatus.PROVISIONING.value,
        )

        message = {
            "Message": json.dumps(
                {
                    "event_type": "range.provisioned",
                    "range_id": range_obj.id,
                    "user_id": 999999,  # Wrong user
                    "instances": [],
                }
            )
        }

        with caplog.at_level(logging.ERROR, logger="engine.handlers"):
            process_range_event(message)

        assert "user_id mismatch in provisioned event" in caplog.text

        # provisioned_instances should be unchanged
        range_obj.refresh_from_db()
        assert range_obj.provisioned_instances is None

    def test_logs_info_on_successful_update(self, user, caplog):
        """Handler logs INFO when provisioned_instances successfully updated."""
        from engine.handlers import process_range_event
        from engine.models import Range

        range_obj = Range.objects.create(
            user=user,
            status=ResourceStatus.PROVISIONING.value,
            range_config={"instances": [{"uuid": "uuid-123", "role": "attacker", "os_type": "kali"}]},
        )

        message = {
            "Message": json.dumps(
                {
                    "event_type": "range.provisioned",
                    "range_id": range_obj.id,
                    "user_id": user.id,
                    "instances": [
                        {
                            "role": "attacker",
                            "os": "kali",
                            "instance_id": "i-123",
                            "private_ip": "10.1.2.10",
                        },
                    ],
                }
            )
        }

        with caplog.at_level(logging.INFO, logger="engine.handlers"):
            process_range_event(message)

        assert "Engine updated provisioned_instances" in caplog.text
        assert f"range_id={range_obj.id}" in caplog.text
        assert "instances=1" in caplog.text
