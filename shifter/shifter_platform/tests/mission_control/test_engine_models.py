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
        """shared.enums.TERMINAL_STATUSES contains terminal states."""
        from shared.enums import TERMINAL_STATUSES, RangeStatus

        assert RangeStatus.DESTROYED in TERMINAL_STATUSES
        assert RangeStatus.FAILED in TERMINAL_STATUSES

    def test_cancellable_statuses_defined(self):
        """shared.enums.CANCELLABLE_STATUSES contains cancellable states."""
        from shared.enums import CANCELLABLE_STATUSES, RangeStatus

        assert RangeStatus.PENDING in CANCELLABLE_STATUSES
        assert RangeStatus.PROVISIONING in CANCELLABLE_STATUSES

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


@pytest.mark.django_db
class TestRangeGetInstanceByUUID:
    """Tests for Range.get_instance_by_uuid().

    Tests the instance lookup method contract:
    - Inputs: uuid string (required, non-empty)
    - Outputs: instance dict or None
    - Side effects: none (pure read operation)
    - Errors: ValueError for invalid uuid input
    - Logging: none (simple getter)
    """

    @pytest.fixture
    def user(self):
        return User.objects.create_user(
            username="uuid_test@example.com",
            email="uuid_test@example.com",
        )

    # -------------------------------------------------------------------------
    # Outputs - returns matching instance dict
    # -------------------------------------------------------------------------

    def test_returns_instance_when_uuid_matches(self, user):
        """Method returns instance dict when UUID matches."""
        from engine.models import Range

        instance_data = {
            "uuid": "abc-123-def",
            "role": "attacker",
            "private_ip": "10.1.1.10",
            "ssh_key_secret_arn": "arn:aws:secretsmanager:us-east-2:123:secret:key",
        }
        range_obj = Range.objects.create(
            user=user,
            status=Range.Status.READY,
            provisioned_instances=[instance_data],
        )

        result = range_obj.get_instance_by_uuid("abc-123-def")

        assert result == instance_data

    def test_returns_correct_instance_from_multiple(self, user):
        """Method returns correct instance when multiple exist."""
        from engine.models import Range

        attacker = {
            "uuid": "attacker-uuid-111",
            "role": "attacker",
            "private_ip": "10.1.1.10",
        }
        victim = {
            "uuid": "victim-uuid-222",
            "role": "victim",
            "private_ip": "10.1.1.20",
        }
        range_obj = Range.objects.create(
            user=user,
            status=Range.Status.READY,
            provisioned_instances=[attacker, victim],
        )

        result = range_obj.get_instance_by_uuid("victim-uuid-222")

        assert result == victim

    def test_returns_none_when_uuid_not_found(self, user):
        """Method returns None when UUID doesn't match any instance."""
        from engine.models import Range

        instance_data = {
            "uuid": "existing-uuid",
            "role": "attacker",
            "private_ip": "10.1.1.10",
        }
        range_obj = Range.objects.create(
            user=user,
            status=Range.Status.READY,
            provisioned_instances=[instance_data],
        )

        result = range_obj.get_instance_by_uuid("non-existent-uuid")

        assert result is None

    def test_returns_none_when_provisioned_instances_empty(self, user):
        """Method returns None when provisioned_instances is empty list."""
        from engine.models import Range

        range_obj = Range.objects.create(
            user=user,
            status=Range.Status.READY,
            provisioned_instances=[],
        )

        result = range_obj.get_instance_by_uuid("any-uuid")

        assert result is None

    def test_returns_none_when_provisioned_instances_null(self, user):
        """Method returns None when provisioned_instances is None."""
        from engine.models import Range

        range_obj = Range.objects.create(
            user=user,
            status=Range.Status.READY,
            provisioned_instances=None,
        )

        result = range_obj.get_instance_by_uuid("any-uuid")

        assert result is None

    # -------------------------------------------------------------------------
    # Input validation - uuid parameter
    # -------------------------------------------------------------------------

    def test_raises_on_none_uuid(self, user):
        """Method raises ValueError when uuid is None."""
        from engine.models import Range

        range_obj = Range.objects.create(
            user=user,
            status=Range.Status.READY,
            provisioned_instances=[{"uuid": "test", "role": "attacker"}],
        )

        with pytest.raises(ValueError, match="uuid"):
            range_obj.get_instance_by_uuid(None)

    def test_raises_on_empty_uuid(self, user):
        """Method raises ValueError when uuid is empty string."""
        from engine.models import Range

        range_obj = Range.objects.create(
            user=user,
            status=Range.Status.READY,
            provisioned_instances=[{"uuid": "test", "role": "attacker"}],
        )

        with pytest.raises(ValueError, match="uuid"):
            range_obj.get_instance_by_uuid("")

    # -------------------------------------------------------------------------
    # Side effects - none expected (pure read operation)
    # -------------------------------------------------------------------------

    def test_does_not_modify_provisioned_instances(self, user):
        """Method does not modify the provisioned_instances data."""
        from engine.models import Range

        instance_data = {
            "uuid": "abc-123-def",
            "role": "attacker",
            "private_ip": "10.1.1.10",
        }
        range_obj = Range.objects.create(
            user=user,
            status=Range.Status.READY,
            provisioned_instances=[instance_data],
        )
        original_data = range_obj.provisioned_instances.copy()

        range_obj.get_instance_by_uuid("abc-123-def")

        assert range_obj.provisioned_instances == original_data

    def test_does_not_save_to_database(self, user):
        """Method does not trigger database save."""
        from engine.models import Range

        range_obj = Range.objects.create(
            user=user,
            status=Range.Status.READY,
            provisioned_instances=[{"uuid": "test", "role": "attacker"}],
        )
        original_updated_at = range_obj.updated_at

        range_obj.get_instance_by_uuid("test")
        range_obj.refresh_from_db()

        assert range_obj.updated_at == original_updated_at

    # -------------------------------------------------------------------------
    # Error handling - malformed data
    # -------------------------------------------------------------------------

    def test_skips_instances_without_uuid_key(self, user):
        """Method skips instances that don't have a uuid key."""
        from engine.models import Range

        malformed = {"role": "attacker", "private_ip": "10.1.1.10"}  # no uuid
        valid = {"uuid": "valid-uuid", "role": "victim", "private_ip": "10.1.1.20"}
        range_obj = Range.objects.create(
            user=user,
            status=Range.Status.READY,
            provisioned_instances=[malformed, valid],
        )

        result = range_obj.get_instance_by_uuid("valid-uuid")

        assert result == valid

    def test_returns_none_when_all_instances_malformed(self, user):
        """Method returns None when no instances have uuid key."""
        from engine.models import Range

        malformed1 = {"role": "attacker", "private_ip": "10.1.1.10"}
        malformed2 = {"role": "victim", "private_ip": "10.1.1.20"}
        range_obj = Range.objects.create(
            user=user,
            status=Range.Status.READY,
            provisioned_instances=[malformed1, malformed2],
        )

        result = range_obj.get_instance_by_uuid("any-uuid")

        assert result is None

    # -------------------------------------------------------------------------
    # Boundary conditions
    # -------------------------------------------------------------------------

    def test_handles_single_instance(self, user):
        """Method works correctly with single instance in list."""
        from engine.models import Range

        instance = {"uuid": "only-one", "role": "attacker"}
        range_obj = Range.objects.create(
            user=user,
            status=Range.Status.READY,
            provisioned_instances=[instance],
        )

        result = range_obj.get_instance_by_uuid("only-one")

        assert result == instance

    def test_handles_many_instances(self, user):
        """Method finds instance in large list."""
        from engine.models import Range

        instances = [{"uuid": f"uuid-{i}", "role": "victim"} for i in range(100)]
        target = {"uuid": "target-uuid", "role": "attacker"}
        instances.insert(50, target)

        range_obj = Range.objects.create(
            user=user,
            status=Range.Status.READY,
            provisioned_instances=instances,
        )

        result = range_obj.get_instance_by_uuid("target-uuid")

        assert result == target

    def test_case_sensitive_uuid_match(self, user):
        """Method performs case-sensitive UUID matching."""
        from engine.models import Range

        instance = {"uuid": "ABC-123", "role": "attacker"}
        range_obj = Range.objects.create(
            user=user,
            status=Range.Status.READY,
            provisioned_instances=[instance],
        )

        result = range_obj.get_instance_by_uuid("abc-123")

        assert result is None  # lowercase doesn't match uppercase
