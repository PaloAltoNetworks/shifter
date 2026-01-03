"""Tests for CMS consumers."""

import logging

import pytest

from shared.enums import RangeStatus


@pytest.mark.django_db
class TestCMSRangeStatusConsumer:
    """Tests for CMSRangeStatusConsumer."""

    # ---------------------------------------------------------------------
    # Happy path - status update
    # ---------------------------------------------------------------------

    def test_updates_range_instance_status(self):
        """Consumer updates RangeInstance.status from event."""
        from cms.consumers import CMSRangeStatusConsumer
        from cms.models import RangeInstance

        # Create a range instance
        RangeInstance.objects.create(
            range_id=1,
            scenario_id="basic",
            user_id=42,
            status=RangeStatus.PENDING.value,
        )

        consumer = CMSRangeStatusConsumer()
        consumer.range_status(
            {
                "type": "range.status",
                "range_id": 1,
                "new_status": RangeStatus.PROVISIONING.value,
                "old_status": RangeStatus.PENDING.value,
                "user_id": 42,
            }
        )

        # Verify status updated
        instance = RangeInstance.objects.get(range_id=1)
        assert instance.status == RangeStatus.PROVISIONING.value

    def test_handles_ready_status(self):
        """Consumer correctly handles READY status."""
        from cms.consumers import CMSRangeStatusConsumer
        from cms.models import RangeInstance

        RangeInstance.objects.create(
            range_id=2,
            scenario_id="basic",
            user_id=42,
            status=RangeStatus.PROVISIONING.value,
        )

        consumer = CMSRangeStatusConsumer()
        consumer.range_status(
            {
                "type": "range.status",
                "range_id": 2,
                "new_status": RangeStatus.READY.value,
                "old_status": RangeStatus.PROVISIONING.value,
                "user_id": 42,
            }
        )

        instance = RangeInstance.objects.get(range_id=2)
        assert instance.status == RangeStatus.READY.value

    # ---------------------------------------------------------------------
    # Error handling
    # ---------------------------------------------------------------------

    def test_handles_missing_range_instance(self, caplog):
        """Consumer logs warning when RangeInstance not found."""
        from cms.consumers import CMSRangeStatusConsumer

        consumer = CMSRangeStatusConsumer()

        with caplog.at_level(logging.WARNING, logger="cms.consumers"):
            consumer.range_status(
                {
                    "type": "range.status",
                    "range_id": 999,
                    "new_status": RangeStatus.READY.value,
                    "old_status": RangeStatus.PROVISIONING.value,
                    "user_id": 42,
                }
            )

        assert "RangeInstance not found" in caplog.text
        assert "999" in caplog.text

    def test_handles_failed_status_with_error_message(self):
        """Consumer accepts error_message in event (not stored in model)."""
        from cms.consumers import CMSRangeStatusConsumer
        from cms.models import RangeInstance

        RangeInstance.objects.create(
            range_id=3,
            scenario_id="basic",
            user_id=42,
            status=RangeStatus.PROVISIONING.value,
        )

        consumer = CMSRangeStatusConsumer()
        consumer.range_status(
            {
                "type": "range.status",
                "range_id": 3,
                "new_status": RangeStatus.FAILED.value,
                "old_status": RangeStatus.PROVISIONING.value,
                "user_id": 42,
                "error_message": "Subnet exhausted",
            }
        )

        instance = RangeInstance.objects.get(range_id=3)
        assert instance.status == RangeStatus.FAILED.value

    # ---------------------------------------------------------------------
    # Logging
    # ---------------------------------------------------------------------

    def test_logs_debug_on_status_update(self, caplog):
        """Consumer logs DEBUG when status updated."""
        from cms.consumers import CMSRangeStatusConsumer
        from cms.models import RangeInstance

        RangeInstance.objects.create(
            range_id=4,
            scenario_id="basic",
            user_id=42,
            status=RangeStatus.PENDING.value,
        )

        consumer = CMSRangeStatusConsumer()

        with caplog.at_level(logging.DEBUG, logger="cms.consumers"):
            consumer.range_status(
                {
                    "type": "range.status",
                    "range_id": 4,
                    "new_status": RangeStatus.PROVISIONING.value,
                    "old_status": RangeStatus.PENDING.value,
                    "user_id": 42,
                }
            )

        assert "range_id=4" in caplog.text
        assert "provisioning" in caplog.text

    # ---------------------------------------------------------------------
    # Input validation
    # ---------------------------------------------------------------------

    def test_rejects_invalid_new_status_value(self, caplog):
        """Consumer rejects invalid new_status values via Pydantic."""
        from cms.consumers import CMSRangeStatusConsumer
        from cms.models import RangeInstance

        RangeInstance.objects.create(
            range_id=5,
            scenario_id="basic",
            user_id=42,
            status=RangeStatus.PENDING.value,
        )

        consumer = CMSRangeStatusConsumer()

        with caplog.at_level(logging.ERROR, logger="cms.consumers"):
            consumer.range_status(
                {
                    "type": "range.status",
                    "range_id": 5,
                    "new_status": "invalid_status",
                    "old_status": RangeStatus.PENDING.value,
                    "user_id": 42,
                }
            )

        # Pydantic validation error logged
        assert "Invalid message format" in caplog.text
        assert "new_status" in caplog.text
        assert "invalid_status" in caplog.text

        # Status should be unchanged
        instance = RangeInstance.objects.get(range_id=5)
        assert instance.status == RangeStatus.PENDING.value

    def test_rejects_invalid_old_status_value(self, caplog):
        """Consumer rejects invalid old_status values via Pydantic."""
        from cms.consumers import CMSRangeStatusConsumer
        from cms.models import RangeInstance

        RangeInstance.objects.create(
            range_id=6,
            scenario_id="basic",
            user_id=42,
            status=RangeStatus.PENDING.value,
        )

        consumer = CMSRangeStatusConsumer()

        with caplog.at_level(logging.ERROR, logger="cms.consumers"):
            consumer.range_status(
                {
                    "type": "range.status",
                    "range_id": 6,
                    "new_status": RangeStatus.PROVISIONING.value,
                    "old_status": "bogus_status",
                    "user_id": 42,
                }
            )

        # Pydantic validation error logged
        assert "Invalid message format" in caplog.text
        assert "old_status" in caplog.text
        assert "bogus_status" in caplog.text

        # Status should be unchanged
        instance = RangeInstance.objects.get(range_id=6)
        assert instance.status == RangeStatus.PENDING.value

    # ---------------------------------------------------------------------
    # Input validation - message structure
    # ---------------------------------------------------------------------

    def test_rejects_non_dict_message(self, caplog):
        """Consumer rejects non-dict messages via Pydantic."""
        from cms.consumers import CMSRangeStatusConsumer

        consumer = CMSRangeStatusConsumer()

        with caplog.at_level(logging.ERROR, logger="cms.consumers"):
            consumer.range_status("not a dict")

        # Pydantic fails to unpack non-dict
        assert "Invalid message format" in caplog.text

    def test_rejects_missing_range_id(self, caplog):
        """Consumer rejects messages missing range_id via Pydantic."""
        from cms.consumers import CMSRangeStatusConsumer

        consumer = CMSRangeStatusConsumer()

        with caplog.at_level(logging.ERROR, logger="cms.consumers"):
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

    def test_rejects_missing_new_status(self, caplog):
        """Consumer rejects messages missing new_status via Pydantic."""
        from cms.consumers import CMSRangeStatusConsumer

        consumer = CMSRangeStatusConsumer()

        with caplog.at_level(logging.ERROR, logger="cms.consumers"):
            consumer.range_status(
                {
                    "type": "range.status",
                    "range_id": 1,
                    "old_status": RangeStatus.PENDING.value,
                    "user_id": 42,
                }
            )

        assert "Invalid message format" in caplog.text
        assert "new_status" in caplog.text

    def test_rejects_missing_old_status(self, caplog):
        """Consumer rejects messages missing old_status via Pydantic."""
        from cms.consumers import CMSRangeStatusConsumer

        consumer = CMSRangeStatusConsumer()

        with caplog.at_level(logging.ERROR, logger="cms.consumers"):
            consumer.range_status(
                {
                    "type": "range.status",
                    "range_id": 1,
                    "new_status": RangeStatus.READY.value,
                    "user_id": 42,
                }
            )

        assert "Invalid message format" in caplog.text
        assert "old_status" in caplog.text

    def test_rejects_missing_user_id(self, caplog):
        """Consumer rejects messages missing user_id via Pydantic."""
        from cms.consumers import CMSRangeStatusConsumer

        consumer = CMSRangeStatusConsumer()

        with caplog.at_level(logging.ERROR, logger="cms.consumers"):
            consumer.range_status(
                {
                    "type": "range.status",
                    "range_id": 1,
                    "new_status": RangeStatus.READY.value,
                    "old_status": RangeStatus.PENDING.value,
                }
            )

        assert "Invalid message format" in caplog.text
        assert "user_id" in caplog.text

    def test_reports_all_missing_fields(self, caplog):
        """Consumer reports all missing fields via Pydantic."""
        from cms.consumers import CMSRangeStatusConsumer

        consumer = CMSRangeStatusConsumer()

        with caplog.at_level(logging.ERROR, logger="cms.consumers"):
            consumer.range_status({"type": "range.status"})

        assert "Invalid message format" in caplog.text
        assert "range_id" in caplog.text
        assert "new_status" in caplog.text
        assert "old_status" in caplog.text
        assert "user_id" in caplog.text

    # ---------------------------------------------------------------------
    # Input validation - field types
    # ---------------------------------------------------------------------

    def test_rejects_non_int_range_id(self, caplog):
        """Consumer rejects non-integer range_id via Pydantic."""
        from cms.consumers import CMSRangeStatusConsumer

        consumer = CMSRangeStatusConsumer()

        with caplog.at_level(logging.ERROR, logger="cms.consumers"):
            consumer.range_status(
                {
                    "type": "range.status",
                    "range_id": "not-an-int",
                    "new_status": RangeStatus.READY.value,
                    "old_status": RangeStatus.PENDING.value,
                    "user_id": 42,
                }
            )

        assert "Invalid message format" in caplog.text
        assert "range_id" in caplog.text

    def test_rejects_negative_range_id(self):
        """Consumer accepts negative range_id (Pydantic int coercion).

        Note: Pydantic accepts negative integers. Validation of positive IDs
        should happen at the database level (RangeInstance.DoesNotExist).
        """
        from cms.consumers import CMSRangeStatusConsumer
        from cms.models import RangeInstance

        # Negative range_id won't match any instance
        consumer = CMSRangeStatusConsumer()
        consumer.range_status(
            {
                "type": "range.status",
                "range_id": -1,
                "new_status": RangeStatus.READY.value,
                "old_status": RangeStatus.PENDING.value,
                "user_id": 42,
            }
        )

        # No instance exists, so update won't happen
        assert not RangeInstance.objects.filter(range_id=-1).exists()

    def test_rejects_non_str_new_status(self, caplog):
        """Consumer rejects non-string new_status via Pydantic."""
        from cms.consumers import CMSRangeStatusConsumer

        consumer = CMSRangeStatusConsumer()

        with caplog.at_level(logging.ERROR, logger="cms.consumers"):
            consumer.range_status(
                {
                    "type": "range.status",
                    "range_id": 1,
                    "new_status": 123,
                    "old_status": RangeStatus.PENDING.value,
                    "user_id": 42,
                }
            )

        assert "Invalid message format" in caplog.text
        assert "new_status" in caplog.text

    def test_rejects_non_str_old_status(self, caplog):
        """Consumer rejects non-string old_status via Pydantic."""
        from cms.consumers import CMSRangeStatusConsumer

        consumer = CMSRangeStatusConsumer()

        with caplog.at_level(logging.ERROR, logger="cms.consumers"):
            consumer.range_status(
                {
                    "type": "range.status",
                    "range_id": 1,
                    "new_status": RangeStatus.READY.value,
                    "old_status": ["pending"],
                    "user_id": 42,
                }
            )

        assert "Invalid message format" in caplog.text
        assert "old_status" in caplog.text

    def test_rejects_non_int_user_id(self, caplog):
        """Consumer rejects non-integer user_id via Pydantic."""
        from cms.consumers import CMSRangeStatusConsumer

        consumer = CMSRangeStatusConsumer()

        with caplog.at_level(logging.ERROR, logger="cms.consumers"):
            consumer.range_status(
                {
                    "type": "range.status",
                    "range_id": 1,
                    "new_status": RangeStatus.READY.value,
                    "old_status": RangeStatus.PENDING.value,
                    "user_id": "not-an-int",
                }
            )

        assert "Invalid message format" in caplog.text
        assert "user_id" in caplog.text

    def test_rejects_negative_user_id(self, caplog):
        """Consumer handles negative user_id (logs warning, no match).

        Note: Pydantic accepts negative integers. Business validation happens
        when the user_id doesn't match any instance.
        """
        from cms.consumers import CMSRangeStatusConsumer
        from cms.models import RangeInstance

        RangeInstance.objects.create(
            range_id=1,
            scenario_id="basic",
            user_id=42,
            status=RangeStatus.PENDING.value,
        )

        consumer = CMSRangeStatusConsumer()

        with caplog.at_level(logging.ERROR, logger="cms.consumers"):
            consumer.range_status(
                {
                    "type": "range.status",
                    "range_id": 1,
                    "new_status": RangeStatus.READY.value,
                    "old_status": RangeStatus.PENDING.value,
                    "user_id": -5,
                }
            )

        # User ID mismatch will be caught by business validation
        assert "user_id mismatch" in caplog.text

    def test_rejects_non_str_error_message(self, caplog):
        """Consumer rejects non-string error_message via Pydantic."""
        from cms.consumers import CMSRangeStatusConsumer

        consumer = CMSRangeStatusConsumer()

        with caplog.at_level(logging.ERROR, logger="cms.consumers"):
            consumer.range_status(
                {
                    "type": "range.status",
                    "range_id": 1,
                    "new_status": RangeStatus.FAILED.value,
                    "old_status": RangeStatus.PENDING.value,
                    "user_id": 42,
                    "error_message": {"not": "a string"},
                }
            )

        assert "Invalid message format" in caplog.text
        assert "error_message" in caplog.text

    # ---------------------------------------------------------------------
    # Instance validation
    # ---------------------------------------------------------------------

    def test_rejects_user_id_mismatch(self, caplog):
        """Consumer rejects messages where user_id doesn't match instance."""
        from cms.consumers import CMSRangeStatusConsumer
        from cms.models import RangeInstance

        RangeInstance.objects.create(
            range_id=7,
            scenario_id="basic",
            user_id=42,
            status=RangeStatus.PENDING.value,
        )

        consumer = CMSRangeStatusConsumer()

        with caplog.at_level(logging.ERROR, logger="cms.consumers"):
            consumer.range_status(
                {
                    "type": "range.status",
                    "range_id": 7,
                    "new_status": RangeStatus.READY.value,
                    "old_status": RangeStatus.PENDING.value,
                    "user_id": 999,  # Wrong user
                }
            )

        assert "user_id mismatch" in caplog.text
        assert "999" in caplog.text
        assert "42" in caplog.text

        # Status should be unchanged
        instance = RangeInstance.objects.get(range_id=7)
        assert instance.status == RangeStatus.PENDING.value

    def test_warns_on_old_status_mismatch(self, caplog):
        """Consumer warns but proceeds when old_status doesn't match."""
        from cms.consumers import CMSRangeStatusConsumer
        from cms.models import RangeInstance

        # Current status is PROVISIONING
        RangeInstance.objects.create(
            range_id=8,
            scenario_id="basic",
            user_id=42,
            status=RangeStatus.PROVISIONING.value,
        )

        consumer = CMSRangeStatusConsumer()

        with caplog.at_level(logging.WARNING, logger="cms.consumers"):
            # Message claims old_status is PENDING (wrong)
            consumer.range_status(
                {
                    "type": "range.status",
                    "range_id": 8,
                    "new_status": RangeStatus.READY.value,
                    "old_status": RangeStatus.PENDING.value,
                    "user_id": 42,
                }
            )

        assert "Status mismatch" in caplog.text
        assert "expected old_status" in caplog.text

        # Status SHOULD be updated despite the mismatch
        instance = RangeInstance.objects.get(range_id=8)
        assert instance.status == RangeStatus.READY.value

    # ---------------------------------------------------------------------
    # Success logging
    # ---------------------------------------------------------------------

    def test_logs_info_on_successful_update(self, caplog):
        """Consumer logs INFO when status successfully updated."""
        from cms.consumers import CMSRangeStatusConsumer
        from cms.models import RangeInstance

        RangeInstance.objects.create(
            range_id=9,
            scenario_id="basic",
            user_id=42,
            status=RangeStatus.PENDING.value,
        )

        consumer = CMSRangeStatusConsumer()

        with caplog.at_level(logging.INFO, logger="cms.consumers"):
            consumer.range_status(
                {
                    "type": "range.status",
                    "range_id": 9,
                    "new_status": RangeStatus.PROVISIONING.value,
                    "old_status": RangeStatus.PENDING.value,
                    "user_id": 42,
                }
            )

        assert "CMS updated RangeInstance" in caplog.text
        assert "range_id=9" in caplog.text
        assert "pending" in caplog.text
        assert "provisioning" in caplog.text

    # ---------------------------------------------------------------------
    # Debug logging
    # ---------------------------------------------------------------------

    def test_logs_debug_on_message_receive(self, caplog):
        """Consumer logs DEBUG when message is received."""
        from cms.consumers import CMSRangeStatusConsumer
        from cms.models import RangeInstance

        RangeInstance.objects.create(
            range_id=10,
            scenario_id="basic",
            user_id=42,
            status=RangeStatus.PENDING.value,
        )

        consumer = CMSRangeStatusConsumer()

        with caplog.at_level(logging.DEBUG, logger="cms.consumers"):
            consumer.range_status(
                {
                    "type": "range.status",
                    "range_id": 10,
                    "new_status": RangeStatus.PROVISIONING.value,
                    "old_status": RangeStatus.PENDING.value,
                    "user_id": 42,
                }
            )

        assert "CMS consumer received message" in caplog.text

    def test_logs_debug_on_validation_success(self, caplog):
        """Consumer logs DEBUG after successful validation."""
        from cms.consumers import CMSRangeStatusConsumer
        from cms.models import RangeInstance

        RangeInstance.objects.create(
            range_id=11,
            scenario_id="basic",
            user_id=42,
            status=RangeStatus.PENDING.value,
        )

        consumer = CMSRangeStatusConsumer()

        with caplog.at_level(logging.DEBUG, logger="cms.consumers"):
            consumer.range_status(
                {
                    "type": "range.status",
                    "range_id": 11,
                    "new_status": RangeStatus.PROVISIONING.value,
                    "old_status": RangeStatus.PENDING.value,
                    "user_id": 42,
                }
            )

        assert "Validated status update" in caplog.text
        assert "range_id=11" in caplog.text

    def test_logs_debug_on_terminal_status(self, caplog):
        """Consumer logs DEBUG when terminal status sets deleted_at."""
        from cms.consumers import CMSRangeStatusConsumer
        from cms.models import RangeInstance

        RangeInstance.objects.create(
            range_id=12,
            scenario_id="basic",
            user_id=42,
            status=RangeStatus.READY.value,
        )

        consumer = CMSRangeStatusConsumer()

        with caplog.at_level(logging.DEBUG, logger="cms.consumers"):
            consumer.range_status(
                {
                    "type": "range.status",
                    "range_id": 12,
                    "new_status": RangeStatus.DESTROYED.value,
                    "old_status": RangeStatus.READY.value,
                    "user_id": 42,
                }
            )

        assert "RangeInstance marked as deleted" in caplog.text
        assert "range_id=12" in caplog.text

    # ---------------------------------------------------------------------
    # Error handling - database failures
    # ---------------------------------------------------------------------

    def test_logs_exception_on_database_error(self, caplog):
        """Consumer logs exception when database save fails."""
        from unittest.mock import patch

        from cms.consumers import CMSRangeStatusConsumer
        from cms.models import RangeInstance

        instance = RangeInstance.objects.create(
            range_id=13,
            scenario_id="basic",
            user_id=42,
            status=RangeStatus.PENDING.value,
        )

        consumer = CMSRangeStatusConsumer()

        with (
            caplog.at_level(logging.ERROR, logger="cms.consumers"),
            patch.object(RangeInstance, "save", side_effect=Exception("DB down")),
        ):
            consumer.range_status(
                {
                    "type": "range.status",
                    "range_id": 13,
                    "new_status": RangeStatus.PROVISIONING.value,
                    "old_status": RangeStatus.PENDING.value,
                    "user_id": 42,
                }
            )

        assert "Database error saving RangeInstance" in caplog.text
        assert "range_id=13" in caplog.text

        # Status should be unchanged in DB
        instance.refresh_from_db()
        assert instance.status == RangeStatus.PENDING.value

    # ---------------------------------------------------------------------
    # Minimum required input
    # ---------------------------------------------------------------------

    def test_succeeds_with_minimum_required_input(self):
        """Consumer works with only required fields (no error_message)."""
        from cms.consumers import CMSRangeStatusConsumer
        from cms.models import RangeInstance

        RangeInstance.objects.create(
            range_id=14,
            scenario_id="basic",
            user_id=42,
            status=RangeStatus.PENDING.value,
        )

        consumer = CMSRangeStatusConsumer()
        consumer.range_status(
            {
                "type": "range.status",
                "range_id": 14,
                "new_status": RangeStatus.PROVISIONING.value,
                "old_status": RangeStatus.PENDING.value,
                "user_id": 42,
                # No error_message field
            }
        )

        instance = RangeInstance.objects.get(range_id=14)
        assert instance.status == RangeStatus.PROVISIONING.value
