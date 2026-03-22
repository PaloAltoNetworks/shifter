"""Tests for Engine models.

These tests verify Range model behavior using in-memory construction
and mocks instead of database access.
"""

from unittest.mock import MagicMock, Mock, patch

import pytest

from engine.models import Range


class TestRangeModel:
    """Tests for Range model in engine.models."""

    # -------------------------------------------------------------------------
    # Import tests - Range should be importable from engine.models
    # -------------------------------------------------------------------------

    def test_range_status_enum_exists(self):
        """Range.Status enum exists with expected values."""
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
        from shared.enums import TERMINAL_STATUSES, ResourceStatus

        assert ResourceStatus.DESTROYED in TERMINAL_STATUSES
        assert ResourceStatus.FAILED in TERMINAL_STATUSES

    def test_cancellable_statuses_defined(self):
        """shared.enums.CANCELLABLE_STATUSES contains cancellable states."""
        from shared.enums import CANCELLABLE_STATUSES, ResourceStatus

        assert ResourceStatus.PENDING in CANCELLABLE_STATUSES
        assert ResourceStatus.PROVISIONING in CANCELLABLE_STATUSES

    # -------------------------------------------------------------------------
    # Model method tests (class methods use mocked querysets)
    # -------------------------------------------------------------------------

    def test_get_active_for_user_returns_none_when_no_range(self):
        """get_active_for_user returns None when user has no active range."""
        user = Mock()
        mock_qs = MagicMock()
        mock_qs.filter.return_value.first.return_value = None

        with patch.object(Range, "objects", mock_qs):
            result = Range.get_active_for_user(user)

        assert result is None

    def test_get_active_for_user_returns_active_range(self):
        """get_active_for_user returns user's active range."""
        user = Mock()
        expected_range = Range(user_id=1, status=Range.Status.READY)
        mock_qs = MagicMock()
        mock_qs.filter.return_value.first.return_value = expected_range

        with patch.object(Range, "objects", mock_qs):
            result = Range.get_active_for_user(user)

        assert result == expected_range
        mock_qs.filter.assert_called_once_with(
            user=user,
            status__in=[
                Range.Status.PENDING,
                Range.Status.PROVISIONING,
                Range.Status.READY,
                Range.Status.PAUSED,
                Range.Status.RESUMING,
            ],
        )

    def test_get_active_for_user_excludes_destroying(self):
        """get_active_for_user excludes DESTROYING ranges via the filter."""
        user = Mock()
        mock_qs = MagicMock()
        mock_qs.filter.return_value.first.return_value = None

        with patch.object(Range, "objects", mock_qs):
            Range.get_active_for_user(user)

        # Verify DESTROYING is not in the status__in list
        call_kwargs = mock_qs.filter.call_args[1]
        assert Range.Status.DESTROYING not in call_kwargs["status__in"]

    def test_get_destroyable_for_user_includes_failed(self):
        """get_destroyable_for_user includes FAILED ranges."""
        user = Mock()
        failed_range = Range(user_id=1, status=Range.Status.FAILED)
        mock_qs = MagicMock()
        mock_qs.filter.return_value.first.return_value = failed_range

        with patch.object(Range, "objects", mock_qs):
            result = Range.get_destroyable_for_user(user)

        assert result == failed_range
        call_kwargs = mock_qs.filter.call_args[1]
        assert Range.Status.FAILED in call_kwargs["status__in"]

    def test_allocate_subnet_index_returns_first_available(self):
        """allocate_subnet_index returns the first available index."""
        mock_qs = MagicMock()
        # No used indices
        mock_qs.exclude.return_value.exclude.return_value.values_list.return_value = []

        with (
            patch.object(Range, "objects", mock_qs),
            patch("engine.models.transaction") as mock_txn,
            patch("engine.models.connection", create=True) as mock_conn,
        ):
            # Mock the atomic context manager
            mock_txn.atomic.return_value.__enter__ = Mock(return_value=None)
            mock_txn.atomic.return_value.__exit__ = Mock(return_value=False)
            mock_conn.vendor = "sqlite"

            index = Range.allocate_subnet_index()

        assert index == 1

    def test_allocate_subnet_index_skips_used_indices(self):
        """allocate_subnet_index skips indices used by active ranges."""
        mock_qs = MagicMock()
        # Index 1 is used
        mock_qs.exclude.return_value.exclude.return_value.values_list.return_value = [1]

        with (
            patch.object(Range, "objects", mock_qs),
            patch("engine.models.transaction") as mock_txn,
            patch("engine.models.connection", create=True) as mock_conn,
        ):
            mock_txn.atomic.return_value.__enter__ = Mock(return_value=None)
            mock_txn.atomic.return_value.__exit__ = Mock(return_value=False)
            mock_conn.vendor = "sqlite"

            index = Range.allocate_subnet_index()

        assert index == 2

    def test_allocate_subnet_index_reuses_destroyed(self):
        """allocate_subnet_index reuses indices from DESTROYED ranges.

        DESTROYED ranges are excluded from the used_indices query, so their
        indices become available for reuse.
        """
        mock_qs = MagicMock()
        # No active ranges using any index (destroyed index 1 excluded by filter)
        mock_qs.exclude.return_value.exclude.return_value.values_list.return_value = []

        with (
            patch.object(Range, "objects", mock_qs),
            patch("engine.models.transaction") as mock_txn,
            patch("engine.models.connection", create=True) as mock_conn,
        ):
            mock_txn.atomic.return_value.__enter__ = Mock(return_value=None)
            mock_txn.atomic.return_value.__exit__ = Mock(return_value=False)
            mock_conn.vendor = "sqlite"

            index = Range.allocate_subnet_index()

        assert index == 1

    # -------------------------------------------------------------------------
    # Model property tests
    # -------------------------------------------------------------------------

    def test_is_usable_ready(self):
        """is_usable returns True for READY ranges."""
        r = Range(user_id=1, status=Range.Status.READY)
        assert r.is_usable is True

    def test_is_usable_paused(self):
        """is_usable returns True for PAUSED ranges."""
        r = Range(user_id=1, status=Range.Status.PAUSED)
        assert r.is_usable is True

    def test_is_usable_failed(self):
        """is_usable returns False for FAILED ranges."""
        r = Range(user_id=1, status=Range.Status.FAILED)
        assert r.is_usable is False

    def test_is_terminal_destroyed(self):
        """is_terminal returns True for DESTROYED ranges."""
        r = Range(user_id=1, status=Range.Status.DESTROYED)
        assert r.is_terminal is True

    def test_is_terminal_failed(self):
        """is_terminal returns True for FAILED ranges."""
        r = Range(user_id=1, status=Range.Status.FAILED)
        assert r.is_terminal is True

    def test_is_terminal_ready(self):
        """is_terminal returns False for READY ranges."""
        r = Range(user_id=1, status=Range.Status.READY)
        assert r.is_terminal is False


class TestRangeGetInstanceByUUID:
    """Tests for Range.get_instance_by_uuid().

    Tests the instance lookup method contract:
    - Inputs: uuid string (required, non-empty)
    - Outputs: instance dict or None
    - Side effects: none (pure read operation)
    - Errors: ValueError for invalid uuid input
    """

    # -------------------------------------------------------------------------
    # Outputs - returns matching instance dict
    # -------------------------------------------------------------------------

    def test_returns_instance_when_uuid_matches(self):
        """Method returns instance dict when UUID matches."""
        instance_data = {
            "uuid": "abc-123-def",
            "role": "attacker",
            "private_ip": "10.1.1.10",
            "ssh_key_secret_arn": "arn:aws:secretsmanager:us-east-2:123:secret:key",
        }
        range_obj = Range(
            user_id=1,
            status=Range.Status.READY,
            provisioned_instances=[instance_data],
        )

        result = range_obj.get_instance_by_uuid("abc-123-def")

        assert result == instance_data

    def test_returns_correct_instance_from_multiple(self):
        """Method returns correct instance when multiple exist."""
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
        range_obj = Range(
            user_id=1,
            status=Range.Status.READY,
            provisioned_instances=[attacker, victim],
        )

        result = range_obj.get_instance_by_uuid("victim-uuid-222")

        assert result == victim

    def test_returns_none_when_uuid_not_found(self):
        """Method returns None when UUID doesn't match any instance."""
        instance_data = {
            "uuid": "existing-uuid",
            "role": "attacker",
            "private_ip": "10.1.1.10",
        }
        range_obj = Range(
            user_id=1,
            status=Range.Status.READY,
            provisioned_instances=[instance_data],
        )

        result = range_obj.get_instance_by_uuid("non-existent-uuid")

        assert result is None

    def test_returns_none_when_provisioned_instances_empty_or_null(self):
        """Method returns None when provisioned_instances is empty or None."""
        for instances_value in [[], None]:
            range_obj = Range(
                user_id=1,
                status=Range.Status.READY,
                provisioned_instances=instances_value,
            )

            result = range_obj.get_instance_by_uuid("any-uuid")
            assert result is None, f"Expected None for provisioned_instances={instances_value}"

    # -------------------------------------------------------------------------
    # Input validation - uuid parameter
    # -------------------------------------------------------------------------

    def test_raises_on_invalid_uuid(self):
        """Method raises ValueError for None or empty uuid."""
        range_obj = Range(
            user_id=1,
            status=Range.Status.READY,
            provisioned_instances=[{"uuid": "test", "role": "attacker"}],
        )

        for invalid_uuid in [None, ""]:
            with pytest.raises(ValueError, match="uuid"):
                range_obj.get_instance_by_uuid(invalid_uuid)

    # -------------------------------------------------------------------------
    # Side effects - none expected (pure read operation)
    # -------------------------------------------------------------------------

    def test_has_no_side_effects(self):
        """Method does not modify the provisioned_instances data."""
        instance_data = {
            "uuid": "abc-123-def",
            "role": "attacker",
            "private_ip": "10.1.1.10",
        }
        range_obj = Range(
            user_id=1,
            status=Range.Status.READY,
            provisioned_instances=[instance_data],
        )
        original_data = range_obj.provisioned_instances.copy()

        range_obj.get_instance_by_uuid("abc-123-def")

        assert range_obj.provisioned_instances == original_data

    # -------------------------------------------------------------------------
    # Error handling - malformed data
    # -------------------------------------------------------------------------

    def test_skips_instances_without_uuid_key(self):
        """Method skips instances that don't have a uuid key."""
        malformed = {"role": "attacker", "private_ip": "10.1.1.10"}  # no uuid
        valid = {"uuid": "valid-uuid", "role": "victim", "private_ip": "10.1.1.20"}
        range_obj = Range(
            user_id=1,
            status=Range.Status.READY,
            provisioned_instances=[malformed, valid],
        )

        result = range_obj.get_instance_by_uuid("valid-uuid")

        assert result == valid

    def test_returns_none_when_all_instances_malformed(self):
        """Method returns None when no instances have uuid key."""
        malformed1 = {"role": "attacker", "private_ip": "10.1.1.10"}
        malformed2 = {"role": "victim", "private_ip": "10.1.1.20"}
        range_obj = Range(
            user_id=1,
            status=Range.Status.READY,
            provisioned_instances=[malformed1, malformed2],
        )

        result = range_obj.get_instance_by_uuid("any-uuid")

        assert result is None

    # -------------------------------------------------------------------------
    # Boundary conditions
    # -------------------------------------------------------------------------

    def test_handles_single_instance(self):
        """Method works correctly with single instance in list."""
        instance = {"uuid": "only-one", "role": "attacker"}
        range_obj = Range(
            user_id=1,
            status=Range.Status.READY,
            provisioned_instances=[instance],
        )

        result = range_obj.get_instance_by_uuid("only-one")

        assert result == instance

    def test_handles_many_instances(self):
        """Method finds instance in large list."""
        instances = [{"uuid": f"uuid-{i}", "role": "victim"} for i in range(100)]
        target = {"uuid": "target-uuid", "role": "attacker"}
        instances.insert(50, target)

        range_obj = Range(
            user_id=1,
            status=Range.Status.READY,
            provisioned_instances=instances,
        )

        result = range_obj.get_instance_by_uuid("target-uuid")

        assert result == target

    def test_case_sensitive_uuid_match(self):
        """Method performs case-sensitive UUID matching."""
        instance = {"uuid": "ABC-123", "role": "attacker"}
        range_obj = Range(
            user_id=1,
            status=Range.Status.READY,
            provisioned_instances=[instance],
        )

        result = range_obj.get_instance_by_uuid("abc-123")

        assert result is None  # lowercase doesn't match uppercase
