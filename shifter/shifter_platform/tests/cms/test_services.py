"""Tests for CMS services."""

from unittest.mock import MagicMock, patch

import pytest

from shared.constants import USER_CANNOT_BE_NONE
from shared.enums import ResourceStatus


@pytest.fixture
def mock_user():
    """Create a mock user with an id attribute."""
    user = MagicMock()
    user.id = 42
    return user


@pytest.fixture
def mock_range_instance():
    """Create a mock RangeInstance returned from queryset."""
    inst = MagicMock()
    inst.range_id = 1
    inst.scenario_id = "basic"
    inst.user_id = 42
    inst.status = ResourceStatus.READY.value
    inst.range_spec = None
    inst.agent = None
    inst.request = MagicMock()
    inst.request.request_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    return inst


def _patch_active_queryset(return_value):
    """Create a patch context that mocks the RangeInstance.active queryset chain.

    Returns (patch_context, mock_active) so callers can further inspect the mock.
    """
    mock_active = MagicMock()
    mock_active.filter.return_value.exclude.return_value.order_by.return_value.first.return_value = return_value
    return patch("cms.services.RangeInstance.active", mock_active), mock_active


class TestGetActiveRange:
    """Tests for get_active_range service."""

    # ---------------------------------------------------------------------
    # Happy path
    # ---------------------------------------------------------------------

    def test_returns_active_range(self, mock_user, mock_range_instance):
        """Returns RangeContext for non-deleted, non-terminal range."""
        from cms.services import get_active_range
        from shared.schemas import RangeContext

        ctx, _ = _patch_active_queryset(mock_range_instance)
        with ctx:
            result = get_active_range(mock_user)

        assert result is not None
        assert isinstance(result, RangeContext)
        assert result.range_id == 1
        assert result.user_id == 42
        assert result.status == ResourceStatus.READY

    def test_returns_provisioning_range(self, mock_user, mock_range_instance):
        """Returns RangeContext for range in PROVISIONING status."""
        from cms.services import get_active_range

        mock_range_instance.range_id = 2
        mock_range_instance.status = ResourceStatus.PROVISIONING.value

        ctx, _ = _patch_active_queryset(mock_range_instance)
        with ctx:
            result = get_active_range(mock_user)

        assert result is not None
        assert result.range_id == 2
        assert result.status == ResourceStatus.PROVISIONING

    def test_returns_none_when_no_ranges(self, mock_user):
        """Returns None when user has no ranges."""
        from cms.services import get_active_range

        ctx, _ = _patch_active_queryset(None)
        with ctx:
            result = get_active_range(mock_user)

        assert result is None

    # ---------------------------------------------------------------------
    # Filtering behavior
    # ---------------------------------------------------------------------

    def test_excludes_deleted_ranges(self, mock_user):
        """Returns None when queryset returns no match (deleted ranges filtered out)."""
        from cms.services import get_active_range

        ctx, _ = _patch_active_queryset(None)
        with ctx:
            result = get_active_range(mock_user)

        assert result is None

    def test_excludes_destroyed_ranges(self, mock_user):
        """Returns None when queryset returns no match (DESTROYED filtered out)."""
        from cms.services import get_active_range

        ctx, _ = _patch_active_queryset(None)
        with ctx:
            result = get_active_range(mock_user)

        assert result is None

    def test_excludes_failed_ranges(self, mock_user):
        """Returns None when queryset returns no match (FAILED filtered out)."""
        from cms.services import get_active_range

        ctx, _ = _patch_active_queryset(None)
        with ctx:
            result = get_active_range(mock_user)

        assert result is None

    def test_excludes_destroying_ranges(self, mock_user):
        """Verifies DESTROYING status is excluded from the queryset."""
        from cms.services import get_active_range

        ctx, mock_active = _patch_active_queryset(None)
        with ctx:
            get_active_range(mock_user)

        # Verify .exclude() was called with DESTROYING status
        mock_active.filter.return_value.exclude.assert_called_once_with(status=ResourceStatus.DESTROYING.value)

    def test_returns_most_recent_active_range(self, mock_user, mock_range_instance):
        """Returns RangeContext for the most recently created active range."""
        from cms.services import get_active_range

        mock_range_instance.range_id = 11
        mock_range_instance.scenario_id = "new"

        ctx, mock_active = _patch_active_queryset(mock_range_instance)
        with ctx:
            result = get_active_range(mock_user)

        # Verify order_by("-created_at") was used
        mock_active.filter.return_value.exclude.return_value.order_by.assert_called_once_with("-created_at")
        assert result is not None
        assert result.range_id == 11

    # ---------------------------------------------------------------------
    # Input validation
    # ---------------------------------------------------------------------

    def test_raises_type_error_for_none_user(self):
        """Raises TypeError when user is None."""
        from cms.services import get_active_range

        with pytest.raises(TypeError, match=USER_CANNOT_BE_NONE):
            get_active_range(None)

    def test_raises_type_error_for_invalid_user(self):
        """Raises TypeError when user lacks id attribute."""
        from cms.services import get_active_range

        with pytest.raises(TypeError, match="user must be a User instance"):
            get_active_range("not a user")

    # ---------------------------------------------------------------------
    # Error handling - database failures
    # ---------------------------------------------------------------------

    def test_propagates_database_error(self, mock_user):
        """Propagates database errors to caller."""
        from django.db import DatabaseError

        from cms.services import get_active_range

        with (
            patch("cms.services.RangeInstance.active") as mock_active,
            pytest.raises(DatabaseError, match="DB connection failed"),
        ):
            mock_active.filter.side_effect = DatabaseError("DB connection failed")
            get_active_range(mock_user)

    # ---------------------------------------------------------------------
    # Validation - RangeContext validates on creation
    # ---------------------------------------------------------------------

    def test_validates_range_context_on_creation(self, mock_user):
        """RangeContext validates data (range_id must be positive)."""
        from pydantic import ValidationError

        from cms.services import get_active_range

        # Create a mock instance with invalid range_id
        mock_instance = MagicMock()
        mock_instance.range_id = 0  # Invalid: must be positive
        mock_instance.user_id = 42
        mock_instance.status = ResourceStatus.READY.value
        mock_instance.range_spec = None
        mock_instance.agent = None
        mock_instance.request = MagicMock()
        mock_instance.request.request_id = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"

        ctx, _ = _patch_active_queryset(mock_instance)
        with ctx, pytest.raises(ValidationError, match="range_id"):
            get_active_range(mock_user)

    # ---------------------------------------------------------------------
    # Instance extraction from range_spec
    # ---------------------------------------------------------------------

    def test_extracts_instances_from_nested_subnets_format(self, mock_user, mock_range_instance):
        """Extracts instances from range_spec with nested subnets format."""
        from cms.services import get_active_range

        mock_range_instance.range_id = 100
        mock_range_instance.range_spec = {
            "subnets": [
                {
                    "name": "core",
                    "instances": [
                        {"uuid": "att-uuid", "role": "attacker", "os_type": "kali", "join_domain": False},
                        {"uuid": "vic-uuid", "role": "victim", "os_type": "windows", "join_domain": False},
                    ],
                }
            ]
        }

        ctx, _ = _patch_active_queryset(mock_range_instance)
        with ctx:
            result = get_active_range(mock_user)

        assert result is not None
        assert len(result.instances) == 2
        assert result.instances[0].uuid == "att-uuid"
        assert result.instances[0].role == "attacker"
        assert result.instances[1].uuid == "vic-uuid"
        assert result.instances[1].role == "victim"

    def test_extracts_instances_from_legacy_flat_format(self, mock_user, mock_range_instance):
        """Extracts instances from range_spec with legacy flat format."""
        from cms.services import get_active_range

        mock_range_instance.range_id = 101
        mock_range_instance.range_spec = {
            "instances": [
                {"uuid": "leg-att", "role": "attacker", "os_type": "kali", "join_domain": False},
            ]
        }

        ctx, _ = _patch_active_queryset(mock_range_instance)
        with ctx:
            result = get_active_range(mock_user)

        assert result is not None
        assert len(result.instances) == 1
        assert result.instances[0].uuid == "leg-att"
        assert result.instances[0].role == "attacker"
