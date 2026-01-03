"""Tests for Engine consumers."""

import logging
from unittest.mock import patch

import pytest

from shared.enums import RangeStatus


@pytest.mark.django_db
class TestEngineRangeStatusConsumer:
    """Tests for EngineRangeStatusConsumer."""

    # ---------------------------------------------------------------------
    # Happy path - status update
    # ---------------------------------------------------------------------

    def test_updates_range_status(self):
        """Consumer updates Range.status from event."""
        from engine.consumers import EngineRangeStatusConsumer
        from engine.models import Range

        user = self._create_user()

        # Create a range
        range_obj = Range.objects.create(
            user=user,
            cms_user_id=user.id,
            status=Range.Status.PENDING,
            subnet_index=1,
            range_config={},
        )

        consumer = EngineRangeStatusConsumer()
        consumer.range_status(
            {
                "type": "range.status",
                "range_id": range_obj.id,
                "new_status": RangeStatus.PROVISIONING.value,
                "old_status": RangeStatus.PENDING.value,
                "user_id": user.id,
            }
        )

        # Verify status updated
        range_obj.refresh_from_db()
        assert range_obj.status == Range.Status.PROVISIONING

    def test_handles_ready_status_with_ready_at(self):
        """Consumer sets ready_at when status changes to READY."""
        from engine.consumers import EngineRangeStatusConsumer
        from engine.models import Range

        user = self._create_user()

        range_obj = Range.objects.create(
            user=user,
            cms_user_id=user.id,
            status=Range.Status.PROVISIONING,
            subnet_index=2,
            range_config={},
        )

        assert range_obj.ready_at is None

        consumer = EngineRangeStatusConsumer()
        consumer.range_status(
            {
                "type": "range.status",
                "range_id": range_obj.id,
                "new_status": RangeStatus.READY.value,
                "old_status": RangeStatus.PROVISIONING.value,
                "user_id": user.id,
            }
        )

        range_obj.refresh_from_db()
        assert range_obj.status == Range.Status.READY
        assert range_obj.ready_at is not None

    def test_handles_failed_status_with_error_message(self):
        """Consumer stores error_message when status is FAILED."""
        from engine.consumers import EngineRangeStatusConsumer
        from engine.models import Range

        user = self._create_user()

        range_obj = Range.objects.create(
            user=user,
            cms_user_id=user.id,
            status=Range.Status.PROVISIONING,
            subnet_index=3,
            range_config={},
        )

        consumer = EngineRangeStatusConsumer()
        consumer.range_status(
            {
                "type": "range.status",
                "range_id": range_obj.id,
                "new_status": RangeStatus.FAILED.value,
                "old_status": RangeStatus.PROVISIONING.value,
                "user_id": user.id,
                "error_message": "Subnet exhausted",
            }
        )

        range_obj.refresh_from_db()
        assert range_obj.status == Range.Status.FAILED
        assert range_obj.error_message == "Subnet exhausted"

    # ---------------------------------------------------------------------
    # Error handling
    # ---------------------------------------------------------------------

    def test_handles_missing_range(self, caplog):
        """Consumer logs warning when Range not found."""
        from engine.consumers import EngineRangeStatusConsumer

        consumer = EngineRangeStatusConsumer()

        with caplog.at_level(logging.WARNING, logger="engine.consumers"):
            consumer.range_status(
                {
                    "type": "range.status",
                    "range_id": 999,
                    "new_status": RangeStatus.READY.value,
                    "old_status": RangeStatus.PROVISIONING.value,
                    "user_id": 42,
                }
            )

        assert "Range not found" in caplog.text
        assert "999" in caplog.text

    # ---------------------------------------------------------------------
    # Logging
    # ---------------------------------------------------------------------

    def test_logs_debug_on_status_update(self, caplog):
        """Consumer logs DEBUG when status updated."""
        from engine.consumers import EngineRangeStatusConsumer
        from engine.models import Range

        user = self._create_user()

        range_obj = Range.objects.create(
            user=user,
            cms_user_id=user.id,
            status=Range.Status.PENDING,
            subnet_index=4,
            range_config={},
        )

        consumer = EngineRangeStatusConsumer()

        with caplog.at_level(logging.DEBUG, logger="engine.consumers"):
            consumer.range_status(
                {
                    "type": "range.status",
                    "range_id": range_obj.id,
                    "new_status": RangeStatus.PROVISIONING.value,
                    "old_status": RangeStatus.PENDING.value,
                    "user_id": user.id,
                }
            )

        assert f"range_id={range_obj.id}" in caplog.text
        assert "provisioning" in caplog.text

    def test_handles_destroyed_status_with_destroyed_at(self):
        """Consumer sets destroyed_at when status changes to DESTROYED."""
        from engine.consumers import EngineRangeStatusConsumer
        from engine.models import Range

        user = self._create_user()

        range_obj = Range.objects.create(
            user=user,
            cms_user_id=user.id,
            status=Range.Status.DESTROYING,
            subnet_index=5,
            range_config={},
        )

        assert range_obj.destroyed_at is None

        consumer = EngineRangeStatusConsumer()
        consumer.range_status(
            {
                "type": "range.status",
                "range_id": range_obj.id,
                "new_status": RangeStatus.DESTROYED.value,
                "old_status": RangeStatus.DESTROYING.value,
                "user_id": user.id,
            }
        )

        range_obj.refresh_from_db()
        assert range_obj.status == Range.Status.DESTROYED
        assert range_obj.destroyed_at is not None

    # ---------------------------------------------------------------------
    # Input validation via Pydantic
    # ---------------------------------------------------------------------

    def test_rejects_invalid_new_status_value(self, caplog):
        """Consumer rejects invalid new_status values via Pydantic."""
        from engine.consumers import EngineRangeStatusConsumer
        from engine.models import Range

        user = self._create_user()

        range_obj = Range.objects.create(
            user=user,
            cms_user_id=user.id,
            status=Range.Status.PENDING,
            subnet_index=6,
            range_config={},
        )

        consumer = EngineRangeStatusConsumer()

        with caplog.at_level(logging.ERROR, logger="engine.consumers"):
            consumer.range_status(
                {
                    "type": "range.status",
                    "range_id": range_obj.id,
                    "new_status": "invalid_status",
                    "old_status": RangeStatus.PENDING.value,
                    "user_id": user.id,
                }
            )

        assert "Invalid message format" in caplog.text
        assert "new_status" in caplog.text

        # Status should be unchanged
        range_obj.refresh_from_db()
        assert range_obj.status == Range.Status.PENDING

    def test_rejects_non_dict_message(self, caplog):
        """Consumer rejects non-dict messages via Pydantic."""
        from engine.consumers import EngineRangeStatusConsumer

        consumer = EngineRangeStatusConsumer()

        with caplog.at_level(logging.ERROR, logger="engine.consumers"):
            consumer.range_status("not a dict")

        assert "Invalid message format" in caplog.text

    def test_rejects_missing_range_id(self, caplog):
        """Consumer rejects messages missing range_id via Pydantic."""
        from engine.consumers import EngineRangeStatusConsumer

        consumer = EngineRangeStatusConsumer()

        with caplog.at_level(logging.ERROR, logger="engine.consumers"):
            consumer.range_status(
                {
                    "type": "range.status",
                    "new_status": RangeStatus.READY.value,
                    "old_status": RangeStatus.PENDING.value,
                    "user_id": 42,
                }
            )

        assert "Invalid message format" in caplog.text
        assert "range_id" in caplog.text

    def test_reports_all_missing_fields(self, caplog):
        """Consumer reports all missing fields via Pydantic."""
        from engine.consumers import EngineRangeStatusConsumer

        consumer = EngineRangeStatusConsumer()

        with caplog.at_level(logging.ERROR, logger="engine.consumers"):
            consumer.range_status({"type": "range.status"})

        assert "Invalid message format" in caplog.text
        assert "range_id" in caplog.text
        assert "new_status" in caplog.text
        assert "old_status" in caplog.text
        assert "user_id" in caplog.text

    # ---------------------------------------------------------------------
    # Instance validation
    # ---------------------------------------------------------------------

    def test_rejects_user_id_mismatch(self, caplog):
        """Consumer rejects messages where user_id doesn't match range."""
        from engine.consumers import EngineRangeStatusConsumer
        from engine.models import Range

        user = self._create_user()

        range_obj = Range.objects.create(
            user=user,
            cms_user_id=user.id,
            status=Range.Status.PENDING,
            subnet_index=7,
            range_config={},
        )

        consumer = EngineRangeStatusConsumer()

        with caplog.at_level(logging.ERROR, logger="engine.consumers"):
            consumer.range_status(
                {
                    "type": "range.status",
                    "range_id": range_obj.id,
                    "new_status": RangeStatus.READY.value,
                    "old_status": RangeStatus.PENDING.value,
                    "user_id": 999,  # Wrong user
                }
            )

        assert "user_id mismatch" in caplog.text
        assert "999" in caplog.text
        assert str(user.id) in caplog.text

        # Status should be unchanged
        range_obj.refresh_from_db()
        assert range_obj.status == Range.Status.PENDING

    def test_warns_on_old_status_mismatch(self, caplog):
        """Consumer warns but proceeds when old_status doesn't match."""
        from engine.consumers import EngineRangeStatusConsumer
        from engine.models import Range

        user = self._create_user()

        # Current status is PROVISIONING
        range_obj = Range.objects.create(
            user=user,
            cms_user_id=user.id,
            status=Range.Status.PROVISIONING,
            subnet_index=8,
            range_config={},
        )

        consumer = EngineRangeStatusConsumer()

        with caplog.at_level(logging.WARNING, logger="engine.consumers"):
            # Message claims old_status is PENDING (wrong)
            consumer.range_status(
                {
                    "type": "range.status",
                    "range_id": range_obj.id,
                    "new_status": RangeStatus.READY.value,
                    "old_status": RangeStatus.PENDING.value,
                    "user_id": user.id,
                }
            )

        assert "Status mismatch" in caplog.text
        assert "expected old_status" in caplog.text

        # Status SHOULD be updated despite the mismatch
        range_obj.refresh_from_db()
        assert range_obj.status == Range.Status.READY

    # ---------------------------------------------------------------------
    # Success logging
    # ---------------------------------------------------------------------

    def test_logs_info_on_successful_update(self, caplog):
        """Consumer logs INFO when status successfully updated."""
        from engine.consumers import EngineRangeStatusConsumer
        from engine.models import Range

        user = self._create_user()

        range_obj = Range.objects.create(
            user=user,
            cms_user_id=user.id,
            status=Range.Status.PENDING,
            subnet_index=9,
            range_config={},
        )

        consumer = EngineRangeStatusConsumer()

        with caplog.at_level(logging.INFO, logger="engine.consumers"):
            consumer.range_status(
                {
                    "type": "range.status",
                    "range_id": range_obj.id,
                    "new_status": RangeStatus.PROVISIONING.value,
                    "old_status": RangeStatus.PENDING.value,
                    "user_id": user.id,
                }
            )

        assert "Engine updated Range" in caplog.text
        assert f"range_id={range_obj.id}" in caplog.text
        assert "pending" in caplog.text
        assert "provisioning" in caplog.text

    # ---------------------------------------------------------------------
    # Debug logging
    # ---------------------------------------------------------------------

    def test_logs_debug_on_message_receive(self, caplog):
        """Consumer logs DEBUG when message is received."""
        from engine.consumers import EngineRangeStatusConsumer
        from engine.models import Range

        user = self._create_user()

        range_obj = Range.objects.create(
            user=user,
            cms_user_id=user.id,
            status=Range.Status.PENDING,
            subnet_index=10,
            range_config={},
        )

        consumer = EngineRangeStatusConsumer()

        with caplog.at_level(logging.DEBUG, logger="engine.consumers"):
            consumer.range_status(
                {
                    "type": "range.status",
                    "range_id": range_obj.id,
                    "new_status": RangeStatus.PROVISIONING.value,
                    "old_status": RangeStatus.PENDING.value,
                    "user_id": user.id,
                }
            )

        assert "Engine consumer received message" in caplog.text

    def test_logs_debug_on_validation_success(self, caplog):
        """Consumer logs DEBUG after successful validation."""
        from engine.consumers import EngineRangeStatusConsumer
        from engine.models import Range

        user = self._create_user()

        range_obj = Range.objects.create(
            user=user,
            cms_user_id=user.id,
            status=Range.Status.PENDING,
            subnet_index=11,
            range_config={},
        )

        consumer = EngineRangeStatusConsumer()

        with caplog.at_level(logging.DEBUG, logger="engine.consumers"):
            consumer.range_status(
                {
                    "type": "range.status",
                    "range_id": range_obj.id,
                    "new_status": RangeStatus.PROVISIONING.value,
                    "old_status": RangeStatus.PENDING.value,
                    "user_id": user.id,
                }
            )

        assert "Validated status update" in caplog.text
        assert f"range_id={range_obj.id}" in caplog.text

    # ---------------------------------------------------------------------
    # Error handling - database failures
    # ---------------------------------------------------------------------

    def test_logs_exception_on_database_error(self, caplog):
        """Consumer logs exception when database save fails."""
        from engine.consumers import EngineRangeStatusConsumer
        from engine.models import Range

        user = self._create_user()

        range_obj = Range.objects.create(
            user=user,
            cms_user_id=user.id,
            status=Range.Status.PENDING,
            subnet_index=12,
            range_config={},
        )

        consumer = EngineRangeStatusConsumer()

        with (
            caplog.at_level(logging.ERROR, logger="engine.consumers"),
            patch.object(Range, "save", side_effect=Exception("DB down")),
        ):
            consumer.range_status(
                {
                    "type": "range.status",
                    "range_id": range_obj.id,
                    "new_status": RangeStatus.PROVISIONING.value,
                    "old_status": RangeStatus.PENDING.value,
                    "user_id": user.id,
                }
            )

        assert "Database error saving Range" in caplog.text
        assert f"range_id={range_obj.id}" in caplog.text

        # Status should be unchanged in DB
        range_obj.refresh_from_db()
        assert range_obj.status == Range.Status.PENDING

    # ---------------------------------------------------------------------
    # Minimum required input
    # ---------------------------------------------------------------------

    def test_succeeds_with_minimum_required_input(self):
        """Consumer works with only required fields (no error_message)."""
        from engine.consumers import EngineRangeStatusConsumer
        from engine.models import Range

        user = self._create_user()

        range_obj = Range.objects.create(
            user=user,
            cms_user_id=user.id,
            status=Range.Status.PENDING,
            subnet_index=13,
            range_config={},
        )

        consumer = EngineRangeStatusConsumer()
        consumer.range_status(
            {
                "type": "range.status",
                "range_id": range_obj.id,
                "new_status": RangeStatus.PROVISIONING.value,
                "old_status": RangeStatus.PENDING.value,
                "user_id": user.id,
                # No error_message field
            }
        )

        range_obj.refresh_from_db()
        assert range_obj.status == Range.Status.PROVISIONING

    # ---------------------------------------------------------------------
    # Helper methods
    # ---------------------------------------------------------------------

    _user_counter = 0

    def _create_user(self):
        """Create test user with unique username."""
        from django.contrib.auth import get_user_model

        TestEngineRangeStatusConsumer._user_counter += 1

        User = get_user_model()
        return User.objects.create_user(
            username=f"testuser{TestEngineRangeStatusConsumer._user_counter}",
            email=f"test{TestEngineRangeStatusConsumer._user_counter}@example.com",
            password="testpass123",  # noqa: S106
        )
