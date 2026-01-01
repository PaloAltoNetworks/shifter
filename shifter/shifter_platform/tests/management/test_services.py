"""Management service interface tests.

Tests specify the contract for each service function:
- Expected inputs and outputs
- Validation behavior
- Logging behavior
- Error propagation with context
"""

import logging
from unittest.mock import patch

import pytest
from django.contrib.auth.models import User
from django.db import IntegrityError
from django.utils import timezone

from management import services
from management.models import ActivityLog, UserProfile

# =============================================================================
# log_activity
# =============================================================================


@pytest.mark.django_db
class TestLogActivityHappyPath:
    """Expected successful behavior for log_activity."""

    def test_creates_activity_log_entry(self):
        """log_activity creates an ActivityLog record."""
        user = User.objects.create_user(username="test@example.com", email="test@example.com")

        services.log_activity("test_action", user)

        assert ActivityLog.objects.filter(action="test_action", user=user).exists()

    def test_stores_metadata_kwargs(self):
        """log_activity stores all kwargs as metadata JSON."""
        user = User.objects.create_user(username="test@example.com", email="test@example.com")

        services.log_activity("test_action", user, key1="value1", key2=42, nested={"a": 1})

        log = ActivityLog.objects.get(action="test_action")
        assert log.metadata == {"key1": "value1", "key2": 42, "nested": {"a": 1}}

    def test_accepts_none_user_for_anonymous_actions(self):
        """log_activity accepts None user for system/anonymous actions."""
        services.log_activity("system_action", user=None)

        log = ActivityLog.objects.get(action="system_action")
        assert log.user is None

    def test_returns_none(self):
        """log_activity returns None (void function)."""
        user = User.objects.create_user(username="test@example.com", email="test@example.com")

        result = services.log_activity("test_action", user)

        assert result is None

    def test_accepts_empty_metadata(self):
        """log_activity works with no metadata kwargs."""
        user = User.objects.create_user(username="test@example.com", email="test@example.com")

        services.log_activity("test_action", user)

        log = ActivityLog.objects.get(action="test_action")
        assert log.metadata == {}


@pytest.mark.django_db
class TestLogActivityInputValidation:
    """Input validation behavior for log_activity."""

    def test_raises_type_error_for_none_action(self):
        """log_activity raises TypeError when action is None."""
        user = User.objects.create_user(username="test@example.com", email="test@example.com")

        with pytest.raises(TypeError, match="action must be a string"):
            services.log_activity(None, user)

    def test_raises_type_error_for_non_string_action(self):
        """log_activity raises TypeError when action is not a string."""
        user = User.objects.create_user(username="test@example.com", email="test@example.com")

        with pytest.raises(TypeError, match="action must be a string"):
            services.log_activity(123, user)

    def test_raises_value_error_for_empty_action(self):
        """log_activity raises ValueError when action is empty string."""
        user = User.objects.create_user(username="test@example.com", email="test@example.com")

        with pytest.raises(ValueError, match="action cannot be empty"):
            services.log_activity("", user)

    def test_raises_value_error_for_whitespace_only_action(self):
        """log_activity raises ValueError when action is only whitespace."""
        user = User.objects.create_user(username="test@example.com", email="test@example.com")

        with pytest.raises(ValueError, match="action cannot be empty"):
            services.log_activity("   ", user)

    def test_raises_value_error_for_unsaved_user(self):
        """log_activity raises ValueError when user has no pk."""
        unsaved_user = User(username="unsaved@example.com", email="unsaved@example.com")

        with pytest.raises(ValueError, match="user must have a primary key"):
            services.log_activity("test_action", unsaved_user)


@pytest.mark.django_db
class TestLogActivityLogging:
    """Logging behavior for log_activity."""

    def test_logs_debug_on_success(self, caplog):
        """log_activity logs debug message on successful logging."""
        user = User.objects.create_user(username="test@example.com", email="test@example.com")

        with caplog.at_level(logging.DEBUG, logger="management.services"):
            services.log_activity("test_action", user)

        assert "test_action" in caplog.text
        assert "test@example.com" in caplog.text

    def test_logs_debug_for_anonymous_action(self, caplog):
        """log_activity logs debug message for anonymous actions."""
        with caplog.at_level(logging.DEBUG, logger="management.services"):
            services.log_activity("system_action", user=None)

        assert "system_action" in caplog.text
        assert "anonymous" in caplog.text.lower()


@pytest.mark.django_db
class TestLogActivityErrorPropagation:
    """Error propagation behavior for log_activity."""

    def test_propagates_database_integrity_error(self):
        """log_activity propagates IntegrityError from ActivityLog.log."""
        user = User.objects.create_user(username="test@example.com", email="test@example.com")

        with (
            patch.object(ActivityLog.objects, "create", side_effect=IntegrityError("DB constraint")),
            pytest.raises(IntegrityError, match="DB constraint"),
        ):
            services.log_activity("test_action", user)

    def test_logs_error_on_database_failure(self, caplog):
        """log_activity logs error when database operation fails."""
        user = User.objects.create_user(username="test@example.com", email="test@example.com")

        with (
            caplog.at_level(logging.ERROR, logger="management.services"),
            patch.object(ActivityLog.objects, "create", side_effect=IntegrityError("DB error")),
            pytest.raises(IntegrityError),
        ):
            services.log_activity("test_action", user)

        assert "test_action" in caplog.text
        assert "failed" in caplog.text.lower() or "error" in caplog.text.lower()


# =============================================================================
# get_user_profile
# =============================================================================


@pytest.mark.django_db
class TestGetUserProfileHappyPath:
    """Expected successful behavior for get_user_profile."""

    def test_returns_existing_profile(self):
        """get_user_profile returns existing profile without modification."""
        user = User.objects.create_user(username="test@example.com", email="test@example.com")
        profile = user.profile
        profile.cognito_sub = "abc-123"
        profile.save()

        result = services.get_user_profile(user)

        assert result == profile
        assert result.cognito_sub == "abc-123"

    def test_creates_profile_when_missing(self):
        """get_user_profile creates profile if none exists."""
        user = User.objects.create_user(username="test@example.com", email="test@example.com")
        UserProfile.objects.filter(user=user).delete()
        assert not UserProfile.objects.filter(user=user).exists()

        result = services.get_user_profile(user)

        assert result.user == user
        assert UserProfile.objects.filter(user=user).exists()

    def test_returns_user_profile_instance(self):
        """get_user_profile returns UserProfile instance."""
        user = User.objects.create_user(username="test@example.com", email="test@example.com")

        result = services.get_user_profile(user)

        assert isinstance(result, UserProfile)


@pytest.mark.django_db
class TestGetUserProfileInputValidation:
    """Input validation behavior for get_user_profile."""

    def test_raises_type_error_for_none_user(self):
        """get_user_profile raises TypeError when user is None."""
        with pytest.raises(TypeError, match="user cannot be None"):
            services.get_user_profile(None)

    def test_raises_value_error_for_unsaved_user(self):
        """get_user_profile raises ValueError when user has no pk."""
        unsaved_user = User(username="unsaved@example.com", email="unsaved@example.com")

        with pytest.raises(ValueError, match="user must have a primary key"):
            services.get_user_profile(unsaved_user)


@pytest.mark.django_db
class TestGetUserProfileLogging:
    """Logging behavior for get_user_profile."""

    def test_logs_debug_on_success(self, caplog):
        """get_user_profile logs debug message on success."""
        user = User.objects.create_user(username="test@example.com", email="test@example.com")

        with caplog.at_level(logging.DEBUG, logger="management.services"):
            services.get_user_profile(user)

        assert "test@example.com" in caplog.text or str(user.pk) in caplog.text

    def test_logs_debug_when_creating_profile(self, caplog):
        """get_user_profile logs when creating new profile."""
        user = User.objects.create_user(username="test@example.com", email="test@example.com")
        UserProfile.objects.filter(user=user).delete()

        with caplog.at_level(logging.DEBUG, logger="management.services"):
            services.get_user_profile(user)

        assert "creat" in caplog.text.lower()


@pytest.mark.django_db
class TestGetUserProfileErrorPropagation:
    """Error propagation behavior for get_user_profile."""

    def test_propagates_database_integrity_error(self):
        """get_user_profile propagates IntegrityError from get_or_create."""
        user = User.objects.create_user(username="test@example.com", email="test@example.com")
        UserProfile.objects.filter(user=user).delete()

        with (
            patch.object(UserProfile.objects, "get_or_create", side_effect=IntegrityError("DB constraint")),
            pytest.raises(IntegrityError, match="DB constraint"),
        ):
            services.get_user_profile(user)

    def test_logs_error_on_database_failure(self, caplog):
        """get_user_profile logs error when database operation fails."""
        user = User.objects.create_user(username="test@example.com", email="test@example.com")
        UserProfile.objects.filter(user=user).delete()

        with (
            caplog.at_level(logging.ERROR, logger="management.services"),
            patch.object(UserProfile.objects, "get_or_create", side_effect=IntegrityError("DB error")),
            pytest.raises(IntegrityError),
        ):
            services.get_user_profile(user)

        assert "failed" in caplog.text.lower() or "error" in caplog.text.lower()


# =============================================================================
# mark_user_deleted
# =============================================================================


@pytest.mark.django_db
class TestMarkUserDeletedHappyPath:
    """Expected successful behavior for mark_user_deleted."""

    def test_sets_deleted_at_timestamp(self):
        """mark_user_deleted sets deleted_at to current time."""
        user = User.objects.create_user(username="test@example.com", email="test@example.com")
        before = timezone.now()

        services.mark_user_deleted(user)

        profile = UserProfile.objects.get(user=user)
        assert profile.deleted_at is not None
        assert profile.deleted_at >= before

    def test_profile_is_deleted_returns_true(self):
        """After mark_user_deleted, is_deleted property returns True."""
        user = User.objects.create_user(username="test@example.com", email="test@example.com")

        services.mark_user_deleted(user)

        profile = UserProfile.objects.get(user=user)
        assert profile.is_deleted is True

    def test_creates_profile_when_missing(self):
        """mark_user_deleted creates profile if none exists before deleting."""
        user = User.objects.create_user(username="test@example.com", email="test@example.com")
        UserProfile.objects.filter(user=user).delete()

        services.mark_user_deleted(user)

        profile = UserProfile.objects.get(user=user)
        assert profile.is_deleted is True

    def test_returns_none(self):
        """mark_user_deleted returns None (void function)."""
        user = User.objects.create_user(username="test@example.com", email="test@example.com")

        result = services.mark_user_deleted(user)

        assert result is None

    def test_is_idempotent(self):
        """mark_user_deleted can be called multiple times (updates timestamp)."""
        user = User.objects.create_user(username="test@example.com", email="test@example.com")

        services.mark_user_deleted(user)
        first_deleted_at = UserProfile.objects.get(user=user).deleted_at

        import time

        time.sleep(0.01)

        services.mark_user_deleted(user)
        second_deleted_at = UserProfile.objects.get(user=user).deleted_at

        assert second_deleted_at >= first_deleted_at


@pytest.mark.django_db
class TestMarkUserDeletedInputValidation:
    """Input validation behavior for mark_user_deleted."""

    def test_raises_type_error_for_none_user(self):
        """mark_user_deleted raises TypeError when user is None."""
        with pytest.raises(TypeError, match="user cannot be None"):
            services.mark_user_deleted(None)

    def test_raises_value_error_for_unsaved_user(self):
        """mark_user_deleted raises ValueError when user has no pk."""
        unsaved_user = User(username="unsaved@example.com", email="unsaved@example.com")

        with pytest.raises(ValueError, match="user must have a primary key"):
            services.mark_user_deleted(unsaved_user)


@pytest.mark.django_db
class TestMarkUserDeletedLogging:
    """Logging behavior for mark_user_deleted."""

    def test_logs_debug_on_success(self, caplog):
        """mark_user_deleted logs debug message on success."""
        user = User.objects.create_user(username="test@example.com", email="test@example.com")

        with caplog.at_level(logging.DEBUG, logger="management.services"):
            services.mark_user_deleted(user)

        assert "test@example.com" in caplog.text or str(user.pk) in caplog.text
        assert "delet" in caplog.text.lower()

    def test_logs_warning_when_already_deleted(self, caplog):
        """mark_user_deleted logs warning when user already deleted."""
        user = User.objects.create_user(username="test@example.com", email="test@example.com")
        services.mark_user_deleted(user)

        with caplog.at_level(logging.WARNING, logger="management.services"):
            services.mark_user_deleted(user)

        assert "already" in caplog.text.lower()


@pytest.mark.django_db
class TestMarkUserDeletedErrorPropagation:
    """Error propagation behavior for mark_user_deleted."""

    def test_propagates_error_from_get_user_profile(self):
        """mark_user_deleted propagates errors from get_user_profile."""
        user = User.objects.create_user(username="test@example.com", email="test@example.com")
        UserProfile.objects.filter(user=user).delete()

        with (
            patch.object(UserProfile.objects, "get_or_create", side_effect=IntegrityError("DB constraint")),
            pytest.raises(IntegrityError, match="DB constraint"),
        ):
            services.mark_user_deleted(user)

    def test_propagates_error_from_profile_save(self):
        """mark_user_deleted propagates errors from profile.save()."""
        user = User.objects.create_user(username="test@example.com", email="test@example.com")

        with (
            patch.object(UserProfile, "save", side_effect=IntegrityError("Save failed")),
            pytest.raises(IntegrityError, match="Save failed"),
        ):
            services.mark_user_deleted(user)

    def test_logs_error_on_save_failure(self, caplog):
        """mark_user_deleted logs error when save fails."""
        user = User.objects.create_user(username="test@example.com", email="test@example.com")

        with (
            caplog.at_level(logging.ERROR, logger="management.services"),
            patch.object(UserProfile, "save", side_effect=IntegrityError("Save failed")),
            pytest.raises(IntegrityError),
        ):
            services.mark_user_deleted(user)

        assert "failed" in caplog.text.lower() or "error" in caplog.text.lower()


# =============================================================================
# create_user_profile
# =============================================================================


@pytest.mark.django_db
class TestCreateUserProfile:
    """Tests for create_user_profile service function."""

    def test_creates_profile_for_user(self):
        """create_user_profile creates a UserProfile for the user."""
        user = User.objects.create_user(username="test@example.com", email="test@example.com")
        UserProfile.objects.filter(user=user).delete()

        services.create_user_profile(user)

        assert UserProfile.objects.filter(user=user).exists()

    def test_raises_type_error_for_none_user(self):
        """create_user_profile raises TypeError when user is None."""
        with pytest.raises(TypeError, match="user cannot be None"):
            services.create_user_profile(None)

    def test_raises_value_error_for_unsaved_user(self):
        """create_user_profile raises ValueError when user has no pk."""
        unsaved_user = User(username="unsaved@example.com", email="unsaved@example.com")

        with pytest.raises(ValueError, match="user must have a primary key"):
            services.create_user_profile(unsaved_user)

    def test_logs_debug_on_success(self, caplog):
        """create_user_profile logs debug message on success."""
        user = User.objects.create_user(username="test@example.com", email="test@example.com")
        UserProfile.objects.filter(user=user).delete()

        with caplog.at_level(logging.DEBUG, logger="management.services"):
            services.create_user_profile(user)

        assert "test@example.com" in caplog.text

    def test_logs_error_on_failure(self, caplog):
        """create_user_profile logs error when database operation fails."""
        user = User.objects.create_user(username="test@example.com", email="test@example.com")
        UserProfile.objects.filter(user=user).delete()

        with (
            caplog.at_level(logging.ERROR, logger="management.services"),
            patch.object(UserProfile.objects, "create", side_effect=IntegrityError("DB error")),
            pytest.raises(IntegrityError),
        ):
            services.create_user_profile(user)

        assert "test@example.com" in caplog.text


# =============================================================================
# save_user_profile
# =============================================================================


@pytest.mark.django_db
class TestSaveUserProfile:
    """Tests for save_user_profile service function."""

    def test_creates_profile_when_missing(self):
        """save_user_profile creates profile if none exists."""
        user = User.objects.create_user(username="test@example.com", email="test@example.com")
        UserProfile.objects.filter(user=user).delete()

        services.save_user_profile(user)

        assert UserProfile.objects.filter(user=user).exists()

    def test_raises_type_error_for_none_user(self):
        """save_user_profile raises TypeError when user is None."""
        with pytest.raises(TypeError, match="user cannot be None"):
            services.save_user_profile(None)

    def test_raises_value_error_for_unsaved_user(self):
        """save_user_profile raises ValueError when user has no pk."""
        unsaved_user = User(username="unsaved@example.com", email="unsaved@example.com")

        with pytest.raises(ValueError, match="user must have a primary key"):
            services.save_user_profile(unsaved_user)

    def test_logs_debug_on_success(self, caplog):
        """save_user_profile logs debug message on success."""
        user = User.objects.create_user(username="test@example.com", email="test@example.com")
        UserProfile.objects.filter(user=user).delete()

        with caplog.at_level(logging.DEBUG, logger="management.services"):
            services.save_user_profile(user)

        assert "test@example.com" in caplog.text

    def test_logs_error_on_failure(self, caplog):
        """save_user_profile logs error when database operation fails."""
        user = User.objects.create_user(username="test@example.com", email="test@example.com")
        UserProfile.objects.filter(user=user).delete()

        with (
            caplog.at_level(logging.ERROR, logger="management.services"),
            patch.object(UserProfile.objects, "get_or_create", side_effect=IntegrityError("DB error")),
            pytest.raises(IntegrityError),
        ):
            services.save_user_profile(user)

        assert "test@example.com" in caplog.text


# =============================================================================
# update_cognito_sub
# =============================================================================


@pytest.mark.django_db
class TestUpdateCognitoSubHappyPath:
    """Expected successful behavior for update_cognito_sub."""

    def test_updates_cognito_sub_on_profile(self):
        """update_cognito_sub sets cognito_sub on user's profile."""
        user = User.objects.create_user(username="test@example.com", email="test@example.com")

        services.update_cognito_sub(user, "abc-123-sub")

        profile = UserProfile.objects.get(user=user)
        assert profile.cognito_sub == "abc-123-sub"

    def test_creates_profile_when_missing(self):
        """update_cognito_sub creates profile if none exists."""
        user = User.objects.create_user(username="test@example.com", email="test@example.com")
        UserProfile.objects.filter(user=user).delete()

        services.update_cognito_sub(user, "abc-123-sub")

        profile = UserProfile.objects.get(user=user)
        assert profile.cognito_sub == "abc-123-sub"

    def test_returns_none(self):
        """update_cognito_sub returns None (void function)."""
        user = User.objects.create_user(username="test@example.com", email="test@example.com")

        result = services.update_cognito_sub(user, "abc-123-sub")

        assert result is None

    def test_overwrites_existing_cognito_sub(self):
        """update_cognito_sub overwrites existing cognito_sub value."""
        user = User.objects.create_user(username="test@example.com", email="test@example.com")
        profile = user.profile
        profile.cognito_sub = "old-sub-value"
        profile.save()

        services.update_cognito_sub(user, "new-sub-value")

        profile.refresh_from_db()
        assert profile.cognito_sub == "new-sub-value"

    def test_no_op_when_cognito_sub_unchanged(self):
        """update_cognito_sub does not save when value unchanged."""
        user = User.objects.create_user(username="test@example.com", email="test@example.com")
        profile = user.profile
        profile.cognito_sub = "same-sub"
        profile.save()

        with patch.object(UserProfile, "save") as mock_save:
            services.update_cognito_sub(user, "same-sub")

        mock_save.assert_not_called()


@pytest.mark.django_db
class TestUpdateCognitoSubInputValidation:
    """Input validation behavior for update_cognito_sub."""

    def test_raises_type_error_for_none_user(self):
        """update_cognito_sub raises TypeError when user is None."""
        with pytest.raises(TypeError, match="user cannot be None"):
            services.update_cognito_sub(None, "abc-123")

    def test_raises_value_error_for_unsaved_user(self):
        """update_cognito_sub raises ValueError when user has no pk."""
        unsaved_user = User(username="unsaved@example.com", email="unsaved@example.com")

        with pytest.raises(ValueError, match="user must have a primary key"):
            services.update_cognito_sub(unsaved_user, "abc-123")

    def test_raises_type_error_for_none_cognito_sub(self):
        """update_cognito_sub raises TypeError when cognito_sub is None."""
        user = User.objects.create_user(username="test@example.com", email="test@example.com")

        with pytest.raises(TypeError, match="cognito_sub cannot be None"):
            services.update_cognito_sub(user, None)

    def test_raises_value_error_for_empty_cognito_sub(self):
        """update_cognito_sub raises ValueError when cognito_sub is empty."""
        user = User.objects.create_user(username="test@example.com", email="test@example.com")

        with pytest.raises(ValueError, match="cognito_sub cannot be empty"):
            services.update_cognito_sub(user, "")

    def test_raises_value_error_for_whitespace_cognito_sub(self):
        """update_cognito_sub raises ValueError when cognito_sub is only whitespace."""
        user = User.objects.create_user(username="test@example.com", email="test@example.com")

        with pytest.raises(ValueError, match="cognito_sub cannot be empty"):
            services.update_cognito_sub(user, "   ")


@pytest.mark.django_db
class TestUpdateCognitoSubLogging:
    """Logging behavior for update_cognito_sub."""

    def test_logs_info_when_cognito_sub_changes(self, caplog):
        """update_cognito_sub logs INFO when cognito_sub is updated."""
        user = User.objects.create_user(username="test@example.com", email="test@example.com")

        with caplog.at_level(logging.INFO, logger="management.services"):
            services.update_cognito_sub(user, "abc-123-sub")

        assert "test@example.com" in caplog.text
        assert "abc-123-sub" in caplog.text

    def test_logs_debug_when_cognito_sub_unchanged(self, caplog):
        """update_cognito_sub logs DEBUG when cognito_sub already matches."""
        user = User.objects.create_user(username="test@example.com", email="test@example.com")
        profile = user.profile
        profile.cognito_sub = "same-sub"
        profile.save()

        with caplog.at_level(logging.DEBUG, logger="management.services"):
            services.update_cognito_sub(user, "same-sub")

        assert "unchanged" in caplog.text.lower() or "already" in caplog.text.lower()


@pytest.mark.django_db
class TestUpdateCognitoSubErrorPropagation:
    """Error propagation behavior for update_cognito_sub."""

    def test_propagates_error_from_get_user_profile(self):
        """update_cognito_sub propagates errors from get_user_profile."""
        user = User.objects.create_user(username="test@example.com", email="test@example.com")
        UserProfile.objects.filter(user=user).delete()

        with (
            patch.object(UserProfile.objects, "get_or_create", side_effect=IntegrityError("DB constraint")),
            pytest.raises(IntegrityError, match="DB constraint"),
        ):
            services.update_cognito_sub(user, "abc-123")

    def test_propagates_error_from_profile_save(self):
        """update_cognito_sub propagates errors from profile.save()."""
        user = User.objects.create_user(username="test@example.com", email="test@example.com")

        with (
            patch.object(UserProfile, "save", side_effect=IntegrityError("Save failed")),
            pytest.raises(IntegrityError, match="Save failed"),
        ):
            services.update_cognito_sub(user, "abc-123")

    def test_logs_error_on_save_failure(self, caplog):
        """update_cognito_sub logs error when save fails."""
        user = User.objects.create_user(username="test@example.com", email="test@example.com")

        with (
            caplog.at_level(logging.ERROR, logger="management.services"),
            patch.object(UserProfile, "save", side_effect=IntegrityError("Save failed")),
            pytest.raises(IntegrityError),
        ):
            services.update_cognito_sub(user, "abc-123")

        assert "failed" in caplog.text.lower() or "error" in caplog.text.lower()
