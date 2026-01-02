"""Tests for Engine models.

These tests verify that Range and UserNGFW models are properly located
in engine.models as per the architecture documentation.
"""

import pytest
from django.contrib.auth import get_user_model

User = get_user_model()


@pytest.mark.django_db
class TestRangeModel:
    """Tests for Range model in engine.models."""

    @pytest.fixture
    def user(self):
        return User.objects.create_user(
            username="test@example.com",
            email="test@example.com",
        )

    # -------------------------------------------------------------------------
    # Import tests - Range should be importable from engine.models
    # -------------------------------------------------------------------------

    def test_range_importable_from_engine(self):
        """Range model can be imported from engine.models."""
        from engine.models import Range

        assert Range is not None

    def test_range_status_enum_exists(self):
        """Range.Status enum exists with expected values."""
        from engine.models import Range

        assert hasattr(Range, "Status")
        assert Range.Status.PENDING == "pending"
        assert Range.Status.PROVISIONING == "provisioning"
        assert Range.Status.READY == "ready"
        assert Range.Status.PAUSED == "paused"
        assert Range.Status.RESUMING == "resuming"
        assert Range.Status.DESTROYING == "destroying"
        assert Range.Status.DESTROYED == "destroyed"
        assert Range.Status.FAILED == "failed"

    def test_terminal_statuses_defined(self):
        """Range.TERMINAL_STATUSES is defined."""
        from engine.models import Range

        assert hasattr(Range, "TERMINAL_STATUSES")
        assert Range.Status.DESTROYED in Range.TERMINAL_STATUSES
        assert Range.Status.FAILED in Range.TERMINAL_STATUSES

    def test_cancellable_statuses_defined(self):
        """Range.CANCELLABLE_STATUSES is defined."""
        from engine.models import Range

        assert hasattr(Range, "CANCELLABLE_STATUSES")
        assert Range.Status.PENDING in Range.CANCELLABLE_STATUSES
        assert Range.Status.PROVISIONING in Range.CANCELLABLE_STATUSES

    # -------------------------------------------------------------------------
    # Model method tests
    # -------------------------------------------------------------------------

    def test_get_active_for_user_returns_none_when_no_range(self, user):
        """get_active_for_user returns None when user has no active range."""
        from engine.models import Range

        result = Range.get_active_for_user(user)
        assert result is None

    def test_get_active_for_user_returns_active_range(self, user):
        """get_active_for_user returns user's active range."""
        from engine.models import Range

        range_obj = Range.objects.create(
            user=user,
            status=Range.Status.READY,
        )

        result = Range.get_active_for_user(user)
        assert result == range_obj

    def test_get_active_for_user_excludes_destroying(self, user):
        """get_active_for_user excludes DESTROYING ranges."""
        from engine.models import Range

        Range.objects.create(
            user=user,
            status=Range.Status.DESTROYING,
        )

        result = Range.get_active_for_user(user)
        assert result is None

    def test_get_destroyable_for_user_includes_failed(self, user):
        """get_destroyable_for_user includes FAILED ranges."""
        from engine.models import Range

        range_obj = Range.objects.create(
            user=user,
            status=Range.Status.FAILED,
        )

        result = Range.get_destroyable_for_user(user)
        assert result == range_obj

    def test_allocate_subnet_index_returns_first_available(self):
        """allocate_subnet_index returns the first available index."""
        from engine.models import Range

        index = Range.allocate_subnet_index()
        assert index == 1

    def test_allocate_subnet_index_skips_used_indices(self, user):
        """allocate_subnet_index skips indices used by active ranges."""
        from engine.models import Range

        # Create a range using index 1
        Range.objects.create(
            user=user,
            status=Range.Status.READY,
            subnet_index=1,
        )

        index = Range.allocate_subnet_index()
        assert index == 2

    def test_allocate_subnet_index_reuses_destroyed(self, user):
        """allocate_subnet_index reuses indices from DESTROYED ranges."""
        from engine.models import Range

        # Create a destroyed range using index 1
        Range.objects.create(
            user=user,
            status=Range.Status.DESTROYED,
            subnet_index=1,
        )

        index = Range.allocate_subnet_index()
        assert index == 1

    # -------------------------------------------------------------------------
    # Model property tests
    # -------------------------------------------------------------------------

    def test_is_active_property(self, user):
        """is_active returns True for READY and PAUSED ranges."""
        from engine.models import Range

        ready_range = Range.objects.create(user=user, status=Range.Status.READY)
        assert ready_range.is_active is True

        paused_range = Range.objects.create(user=user, status=Range.Status.PAUSED)
        assert paused_range.is_active is True

        failed_range = Range.objects.create(user=user, status=Range.Status.FAILED)
        assert failed_range.is_active is False

    def test_is_terminal_property(self, user):
        """is_terminal returns True for DESTROYED and FAILED ranges."""
        from engine.models import Range

        destroyed_range = Range.objects.create(user=user, status=Range.Status.DESTROYED)
        assert destroyed_range.is_terminal is True

        failed_range = Range.objects.create(user=user, status=Range.Status.FAILED)
        assert failed_range.is_terminal is True

        ready_range = Range.objects.create(user=user, status=Range.Status.READY)
        assert ready_range.is_terminal is False


@pytest.mark.django_db
class TestUserNGFWModel:
    """Tests for UserNGFW model in engine.models."""

    @pytest.fixture
    def user(self):
        return User.objects.create_user(
            username="ngfwtest@example.com",
            email="ngfwtest@example.com",
        )

    # -------------------------------------------------------------------------
    # Import tests - UserNGFW should be importable from engine.models
    # -------------------------------------------------------------------------

    def test_userngfw_importable_from_engine(self):
        """UserNGFW model can be imported from engine.models."""
        from engine.models import UserNGFW

        assert UserNGFW is not None

    def test_userngfw_status_enum_exists(self):
        """UserNGFW.Status enum exists with expected values."""
        from engine.models import UserNGFW

        assert hasattr(UserNGFW, "Status")
        assert UserNGFW.Status.NOT_PROVISIONED == "not_provisioned"
        assert UserNGFW.Status.PROVISIONING == "provisioning"
        assert UserNGFW.Status.READY == "ready"
        assert UserNGFW.Status.STARTING == "starting"
        assert UserNGFW.Status.ACTIVE == "active"
        assert UserNGFW.Status.STOPPING == "stopping"
        assert UserNGFW.Status.STOPPED == "stopped"
        assert UserNGFW.Status.DEPROVISIONING == "deprovisioning"
        assert UserNGFW.Status.FAILED == "failed"

    # -------------------------------------------------------------------------
    # Model method tests
    # -------------------------------------------------------------------------

    def test_active_for_user_excludes_deleted(self, user):
        """active_for_user excludes soft-deleted NGFWs."""
        from django.utils import timezone

        from engine.models import UserNGFW

        active_ngfw = UserNGFW.objects.create(user=user, name="Active NGFW")
        UserNGFW.objects.create(
            user=user,
            name="Deleted NGFW",
            deleted_at=timezone.now(),
        )

        result = list(UserNGFW.active_for_user(user))
        assert len(result) == 1
        assert result[0] == active_ngfw

    def test_active_for_user_filters_by_user(self, user):
        """active_for_user only returns NGFWs for specified user."""
        from engine.models import UserNGFW

        other_user = User.objects.create_user(
            username="other@example.com",
            email="other@example.com",
        )

        my_ngfw = UserNGFW.objects.create(user=user, name="My NGFW")
        UserNGFW.objects.create(user=other_user, name="Other NGFW")

        result = list(UserNGFW.active_for_user(user))
        assert len(result) == 1
        assert result[0] == my_ngfw

    def test_default_status_is_not_provisioned(self, user):
        """Default status is NOT_PROVISIONED."""
        from engine.models import UserNGFW

        ngfw = UserNGFW.objects.create(user=user, name="New NGFW")
        assert ngfw.status == UserNGFW.Status.NOT_PROVISIONED

    def test_str_returns_name(self, user):
        """__str__ returns the NGFW name."""
        from engine.models import UserNGFW

        ngfw = UserNGFW(user=user, name="Test NGFW")
        assert str(ngfw) == "Test NGFW"
