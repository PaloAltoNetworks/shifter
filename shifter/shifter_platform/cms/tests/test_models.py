"""Tests for CMS models."""

import pytest
from django.utils import timezone

from shared.enums import RangeStatus


@pytest.mark.django_db
class TestRangeInstanceModel:
    """Tests for RangeInstance model."""

    # ---------------------------------------------------------------------
    # Status field
    # ---------------------------------------------------------------------

    def test_has_status_field(self):
        """RangeInstance has status field."""
        from cms.models import RangeInstance

        instance = RangeInstance(
            range_id=1,
            scenario_id="basic",
            user_id=42,
        )

        assert hasattr(instance, "status")

    def test_status_defaults_to_pending(self):
        """RangeInstance.status defaults to PENDING."""
        from cms.models import RangeInstance

        instance = RangeInstance(
            range_id=1,
            scenario_id="basic",
            user_id=42,
        )

        assert instance.status == RangeStatus.PENDING.value

    def test_status_accepts_valid_values(self):
        """RangeInstance.status accepts all RangeStatus values."""
        from cms.models import RangeInstance

        for status in RangeStatus:
            instance = RangeInstance(
                range_id=1,
                scenario_id="basic",
                user_id=42,
                status=status.value,
            )
            assert instance.status == status.value

    def test_status_persists_to_database(self):
        """RangeInstance.status is saved to database."""
        from cms.models import RangeInstance

        instance = RangeInstance.objects.create(
            range_id=1,
            scenario_id="basic",
            user_id=42,
            status=RangeStatus.PROVISIONING.value,
        )

        # Reload from database
        instance.refresh_from_db()
        assert instance.status == RangeStatus.PROVISIONING.value

    # ---------------------------------------------------------------------
    # Deleted_at field
    # ---------------------------------------------------------------------

    def test_has_deleted_at_field(self):
        """RangeInstance has deleted_at field."""
        from cms.models import RangeInstance

        instance = RangeInstance(
            range_id=2,
            scenario_id="basic",
            user_id=42,
        )

        assert hasattr(instance, "deleted_at")

    def test_deleted_at_defaults_to_none(self):
        """RangeInstance.deleted_at defaults to None."""
        from cms.models import RangeInstance

        instance = RangeInstance(
            range_id=2,
            scenario_id="basic",
            user_id=42,
        )

        assert instance.deleted_at is None

    def test_deleted_at_accepts_datetime(self):
        """RangeInstance.deleted_at accepts datetime values."""
        from cms.models import RangeInstance

        now = timezone.now()
        instance = RangeInstance(
            range_id=2,
            scenario_id="basic",
            user_id=42,
            deleted_at=now,
        )

        assert instance.deleted_at == now

    def test_deleted_at_persists_to_database(self):
        """RangeInstance.deleted_at is saved to database."""
        from cms.models import RangeInstance

        now = timezone.now()
        instance = RangeInstance.objects.create(
            range_id=3,
            scenario_id="basic",
            user_id=42,
            deleted_at=now,
        )

        # Reload from database
        instance.refresh_from_db()
        assert instance.deleted_at is not None

    # ---------------------------------------------------------------------
    # Active manager
    # ---------------------------------------------------------------------

    def test_active_manager_excludes_deleted(self):
        """RangeInstance.active excludes soft-deleted instances."""
        from cms.models import RangeInstance

        # Create active instance
        RangeInstance.objects.create(
            range_id=10,
            scenario_id="basic",
            user_id=42,
        )

        # Create soft-deleted instance
        RangeInstance.objects.create(
            range_id=11,
            scenario_id="basic",
            user_id=42,
            deleted_at=timezone.now(),
        )

        active = RangeInstance.active.all()
        assert active.count() == 1
        assert active.first().range_id == 10

    def test_objects_manager_includes_all(self):
        """RangeInstance.objects includes soft-deleted instances."""
        from cms.models import RangeInstance

        # Create active instance
        RangeInstance.objects.create(
            range_id=20,
            scenario_id="basic",
            user_id=42,
        )

        # Create soft-deleted instance
        RangeInstance.objects.create(
            range_id=21,
            scenario_id="basic",
            user_id=42,
            deleted_at=timezone.now(),
        )

        all_instances = RangeInstance.objects.all()
        assert all_instances.count() == 2

    # ---------------------------------------------------------------------
    # Terminal status invariant
    # ---------------------------------------------------------------------

    def test_terminal_status_auto_sets_deleted_at(self):
        """Setting status to DESTROYED auto-sets deleted_at."""
        from cms.models import RangeInstance

        instance = RangeInstance.objects.create(
            range_id=30,
            scenario_id="basic",
            user_id=42,
            status=RangeStatus.READY.value,
        )

        # Verify not deleted initially
        assert instance.deleted_at is None

        # Update to terminal status
        instance.status = RangeStatus.DESTROYED.value
        instance.save()

        # Verify deleted_at was auto-set
        assert instance.deleted_at is not None

    def test_failed_status_auto_sets_deleted_at(self):
        """Setting status to FAILED auto-sets deleted_at."""
        from cms.models import RangeInstance

        instance = RangeInstance.objects.create(
            range_id=31,
            scenario_id="basic",
            user_id=42,
            status=RangeStatus.PROVISIONING.value,
        )

        # Update to failed status
        instance.status = RangeStatus.FAILED.value
        instance.save()

        # Verify deleted_at was auto-set
        assert instance.deleted_at is not None

    def test_terminal_status_preserves_existing_deleted_at(self):
        """Terminal status doesn't overwrite existing deleted_at."""
        from cms.models import RangeInstance

        earlier = timezone.now()
        instance = RangeInstance.objects.create(
            range_id=32,
            scenario_id="basic",
            user_id=42,
            status=RangeStatus.READY.value,
            deleted_at=earlier,
        )

        # Update to terminal status
        instance.status = RangeStatus.DESTROYED.value
        instance.save()

        # Verify original deleted_at preserved
        assert instance.deleted_at == earlier

    def test_non_terminal_status_does_not_set_deleted_at(self):
        """Non-terminal status changes don't affect deleted_at."""
        from cms.models import RangeInstance

        instance = RangeInstance.objects.create(
            range_id=33,
            scenario_id="basic",
            user_id=42,
            status=RangeStatus.PENDING.value,
        )

        # Transition through non-terminal statuses
        for status in [RangeStatus.PROVISIONING, RangeStatus.READY]:
            instance.status = status.value
            instance.save()
            assert instance.deleted_at is None

    def test_terminal_status_with_update_fields_still_sets_deleted_at(self):
        """Terminal status with update_fields=['status'] still sets deleted_at.

        This tests the pattern used by CMSRangeStatusConsumer which uses
        save(update_fields=['status']) for efficiency.
        """
        from cms.models import RangeInstance

        instance = RangeInstance.objects.create(
            range_id=34,
            scenario_id="basic",
            user_id=42,
            status=RangeStatus.READY.value,
        )

        # Verify not deleted initially
        assert instance.deleted_at is None

        # Update to terminal status using update_fields (like the consumer)
        instance.status = RangeStatus.DESTROYED.value
        instance.save(update_fields=["status"])

        # Verify deleted_at was auto-set and persisted
        instance.refresh_from_db()
        assert instance.deleted_at is not None
