"""Unit tests for NGFW-related models.

Tests for:
- UserNGFW (decoupled from credentials)
- Range.ngfw FK relationship

These tests focus on edge cases and subtle bugs:
- Status transitions
- Query filtering logic

Note: UserNGFW no longer has FK relationships to credential models.
Credentials are managed by CMS (see tests/cms/test_models.py).
"""

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from mission_control.models import (
    Range,
    UserNGFW,
)

User = get_user_model()


# --- UserNGFW Tests ---


@pytest.mark.django_db
class TestUserNGFW:
    """Tests for UserNGFW model.

    Note: UserNGFW no longer has credential FKs. Credentials are managed by CMS
    and passed as hydrated config values at provisioning time.
    """

    @pytest.fixture
    def user(self):
        return User.objects.create_user(username="test@example.com", email="test@example.com")

    def test_create_with_required_fields(self, user):
        """UserNGFW can be created with just user and name."""
        ngfw = UserNGFW.objects.create(
            user=user,
            name="My NGFW",
        )
        assert ngfw.pk is not None
        assert ngfw.status == UserNGFW.Status.NOT_PROVISIONED

    def test_no_credential_fks(self, user):
        """UserNGFW should not have credential FK fields (decoupled architecture)."""
        ngfw = UserNGFW(user=user, name="Test")
        assert not hasattr(ngfw, "deployment_profile")
        assert not hasattr(ngfw, "scm_credential")

    def test_str_returns_name(self, user):
        """__str__ returns the NGFW name."""
        ngfw = UserNGFW(user=user, name="Test NGFW")
        assert str(ngfw) == "Test NGFW"

    def test_default_status_is_not_provisioned(self, user):
        """Default status is NOT_PROVISIONED."""
        ngfw = UserNGFW.objects.create(user=user, name="New NGFW")
        assert ngfw.status == "not_provisioned"

    def test_all_status_choices_valid(self, user):
        """All status choices can be set."""
        valid_statuses = [
            "not_provisioned",
            "provisioning",
            "ready",
            "starting",
            "active",
            "stopping",
            "stopped",
            "deprovisioning",
            "failed",
        ]
        for status in valid_statuses:
            ngfw = UserNGFW.objects.create(
                user=user,
                name=f"NGFW {status}",
                status=status,
            )
            ngfw.full_clean()
            assert ngfw.status == status

    def test_user_cascade_deletes_ngfw(self, user):
        """Deleting user cascades to delete their NGFWs."""
        ngfw = UserNGFW.objects.create(user=user, name="User's NGFW")
        ngfw_pk = ngfw.pk

        user.delete()

        assert not UserNGFW.objects.filter(pk=ngfw_pk).exists()

    # --- active_for_user tests ---

    def test_active_for_user_excludes_deleted(self, user):
        """active_for_user excludes soft-deleted NGFWs."""
        active = UserNGFW.objects.create(user=user, name="Active NGFW")
        UserNGFW.objects.create(
            user=user,
            name="Deleted NGFW",
            deleted_at=timezone.now(),
        )

        result = list(UserNGFW.active_for_user(user))
        assert len(result) == 1
        assert result[0] == active

    def test_active_for_user_filters_by_user(self, user):
        """active_for_user only returns NGFWs for specified user."""
        other_user = User.objects.create_user(username="other@example.com", email="other@example.com")

        UserNGFW.objects.create(user=user, name="My NGFW")
        UserNGFW.objects.create(user=other_user, name="Other NGFW")

        result = list(UserNGFW.active_for_user(user))
        assert len(result) == 1
        assert result[0].name == "My NGFW"


# --- Range NGFW relationship tests ---


@pytest.mark.django_db
class TestRangeNGFWRelationship:
    """Tests for Range.ngfw FK relationship."""

    @pytest.fixture
    def user(self):
        return User.objects.create_user(username="test@example.com", email="test@example.com")

    @pytest.fixture
    def ngfw(self, user):
        return UserNGFW.objects.create(user=user, name="Test NGFW")

    def test_range_ngfw_nullable(self, user):
        """Range.ngfw can be null (no NGFW attached)."""
        range_obj = Range.objects.create(user=user, ngfw=None)
        assert range_obj.ngfw is None

    def test_range_ngfw_can_be_set(self, user, ngfw):
        """Range.ngfw can reference a UserNGFW."""
        range_obj = Range.objects.create(user=user, ngfw=ngfw)
        assert range_obj.ngfw == ngfw

    def test_ngfw_delete_sets_range_ngfw_null(self, user, ngfw):
        """Deleting NGFW sets Range.ngfw to NULL (SET_NULL behavior)."""
        range_obj = Range.objects.create(user=user, ngfw=ngfw)

        ngfw.delete()

        range_obj.refresh_from_db()
        assert range_obj.ngfw is None

    def test_gwlb_endpoint_id_field_exists(self, user):
        """Range has gwlb_endpoint_id field."""
        range_obj = Range.objects.create(
            user=user,
            gwlb_endpoint_id="vpce-abc123def456",
        )
        assert range_obj.gwlb_endpoint_id == "vpce-abc123def456"

    def test_gwlb_endpoint_id_default_empty(self, user):
        """gwlb_endpoint_id defaults to empty string."""
        range_obj = Range.objects.create(user=user)
        assert range_obj.gwlb_endpoint_id == ""

    def test_multiple_ranges_can_use_same_ngfw(self, user, ngfw):
        """Multiple ranges can reference the same NGFW."""
        range1 = Range.objects.create(user=user, ngfw=ngfw)
        range2 = Range.objects.create(user=user, ngfw=ngfw)

        assert range1.ngfw == range2.ngfw == ngfw
        assert list(ngfw.ranges.all()) == [range2, range1]  # ordered by -created_at
