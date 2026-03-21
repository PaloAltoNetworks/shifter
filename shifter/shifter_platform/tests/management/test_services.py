"""Management service interface tests.

Tests specify the contract for each service function:
- Expected inputs and outputs
- Validation behavior
- Logging behavior
- Error propagation with context

All ORM interactions are mocked — no database required.
"""

import logging
from unittest.mock import Mock, patch

import pytest
from django.db import IntegrityError

from management import services
from management.models import ActivityLog, UserProfile
from shared.constants import USER_CANNOT_BE_NONE


def _saved_user(**overrides):
    """Return a Mock user with pk set (simulates a saved user)."""
    defaults = {"pk": 42, "id": 42, "email": "test@example.com", "username": "test@example.com"}
    defaults.update(overrides)
    return Mock(**defaults)


def _unsaved_user():
    """Return a Mock user with pk=None (simulates an unsaved user)."""
    return Mock(pk=None, email="unsaved@example.com", username="unsaved@example.com")


def _mock_profile(**overrides):
    """Return a Mock profile with spec=UserProfile."""
    defaults = {
        "cognito_sub": None,
        "deleted_at": None,
        "is_deleted": False,
    }
    defaults.update(overrides)
    profile = Mock(spec=UserProfile)
    for attr, val in defaults.items():
        setattr(profile, attr, val)
    return profile


# =============================================================================
# log_activity
# =============================================================================


class TestLogActivityHappyPath:
    """Expected successful behavior for log_activity."""

    def test_creates_activity_log_entry(self):
        """log_activity calls ActivityLog.log to create a record."""
        user = _saved_user()

        with patch.object(ActivityLog, "log") as mock_log:
            services.log_activity("test_action", user)

        mock_log.assert_called_once_with("test_action", user=user)

    def test_stores_metadata_kwargs(self):
        """log_activity passes all kwargs as metadata to ActivityLog.log."""
        user = _saved_user()

        with patch.object(ActivityLog, "log") as mock_log:
            services.log_activity("test_action", user, key1="value1", key2=42, nested={"a": 1})

        mock_log.assert_called_once_with("test_action", user=user, key1="value1", key2=42, nested={"a": 1})

    def test_accepts_none_user_for_anonymous_actions(self):
        """log_activity accepts None user for system/anonymous actions."""
        with patch.object(ActivityLog, "log") as mock_log:
            services.log_activity("system_action", user=None)

        mock_log.assert_called_once_with("system_action", user=None)

    def test_returns_none(self):
        """log_activity returns None (void function)."""
        user = _saved_user()

        with patch.object(ActivityLog, "log"):
            result = services.log_activity("test_action", user)

        assert result is None

    def test_accepts_empty_metadata(self):
        """log_activity works with no metadata kwargs."""
        user = _saved_user()

        with patch.object(ActivityLog, "log") as mock_log:
            services.log_activity("test_action", user)

        mock_log.assert_called_once_with("test_action", user=user)


class TestLogActivityInputValidation:
    """Input validation behavior for log_activity."""

    def test_raises_type_error_for_none_action(self):
        """log_activity raises TypeError when action is None."""
        user = _saved_user()

        with pytest.raises(TypeError, match="action must be a string"):
            services.log_activity(None, user)

    def test_raises_type_error_for_non_string_action(self):
        """log_activity raises TypeError when action is not a string."""
        user = _saved_user()

        with pytest.raises(TypeError, match="action must be a string"):
            services.log_activity(123, user)

    def test_raises_value_error_for_empty_action(self):
        """log_activity raises ValueError when action is empty string."""
        user = _saved_user()

        with pytest.raises(ValueError, match="action cannot be empty"):
            services.log_activity("", user)

    def test_raises_value_error_for_whitespace_only_action(self):
        """log_activity raises ValueError when action is only whitespace."""
        user = _saved_user()

        with pytest.raises(ValueError, match="action cannot be empty"):
            services.log_activity("   ", user)

    def test_raises_value_error_for_unsaved_user(self):
        """log_activity raises ValueError when user has no pk."""
        unsaved_user = _unsaved_user()

        with pytest.raises(ValueError, match="user must have a primary key"):
            services.log_activity("test_action", unsaved_user)


class TestLogActivityLogging:
    """Logging behavior for log_activity."""

    def test_logs_debug_on_success(self, caplog):
        """log_activity logs debug message on successful logging."""
        user = _saved_user()

        with (
            caplog.at_level(logging.DEBUG, logger="management.services"),
            patch.object(ActivityLog, "log"),
        ):
            services.log_activity("test_action", user)

        assert "test_action" in caplog.text
        assert "test@example.com" in caplog.text

    def test_logs_debug_for_anonymous_action(self, caplog):
        """log_activity logs debug message for anonymous actions."""
        with (
            caplog.at_level(logging.DEBUG, logger="management.services"),
            patch.object(ActivityLog, "log"),
        ):
            services.log_activity("system_action", user=None)

        assert "system_action" in caplog.text
        assert "anonymous" in caplog.text.lower()


class TestLogActivityErrorPropagation:
    """Error propagation behavior for log_activity."""

    def test_propagates_database_integrity_error(self):
        """log_activity propagates IntegrityError from ActivityLog.log."""
        user = _saved_user()

        with (
            patch.object(ActivityLog, "log", side_effect=IntegrityError("DB constraint")),
            pytest.raises(IntegrityError, match="DB constraint"),
        ):
            services.log_activity("test_action", user)

    def test_logs_error_on_database_failure(self, caplog):
        """log_activity logs error when database operation fails."""
        user = _saved_user()

        with (
            caplog.at_level(logging.ERROR, logger="management.services"),
            patch.object(ActivityLog, "log", side_effect=IntegrityError("DB error")),
            pytest.raises(IntegrityError),
        ):
            services.log_activity("test_action", user)

        assert "test_action" in caplog.text
        assert "failed" in caplog.text.lower() or "error" in caplog.text.lower()


# =============================================================================
# get_user_profile
# =============================================================================


class TestGetUserProfileHappyPath:
    """Expected successful behavior for get_user_profile."""

    def test_returns_existing_profile(self):
        """get_user_profile returns existing profile without modification."""
        user = _saved_user()
        profile = _mock_profile(cognito_sub="abc-123")

        with patch.object(UserProfile.objects, "get_or_create", return_value=(profile, False)):
            result = services.get_user_profile(user)

        assert result is profile
        assert result.cognito_sub == "abc-123"

    def test_creates_profile_when_missing(self):
        """get_user_profile creates profile if none exists."""
        user = _saved_user()
        profile = _mock_profile()

        with patch.object(UserProfile.objects, "get_or_create", return_value=(profile, True)) as mock_goc:
            result = services.get_user_profile(user)

        assert result is profile
        mock_goc.assert_called_once_with(user=user)

    def test_returns_user_profile_instance(self):
        """get_user_profile returns a UserProfile-like object."""
        user = _saved_user()
        profile = _mock_profile()

        with patch.object(UserProfile.objects, "get_or_create", return_value=(profile, False)):
            result = services.get_user_profile(user)

        assert isinstance(result, UserProfile)


class TestGetUserProfileInputValidation:
    """Input validation behavior for get_user_profile."""

    def test_raises_type_error_for_none_user(self):
        """get_user_profile raises TypeError when user is None."""
        with pytest.raises(TypeError, match=USER_CANNOT_BE_NONE):
            services.get_user_profile(None)

    def test_raises_value_error_for_unsaved_user(self):
        """get_user_profile raises ValueError when user has no pk."""
        unsaved_user = _unsaved_user()

        with pytest.raises(ValueError, match="user must have a primary key"):
            services.get_user_profile(unsaved_user)


class TestGetUserProfileLogging:
    """Logging behavior for get_user_profile."""

    def test_logs_debug_on_success(self, caplog):
        """get_user_profile logs debug message on success."""
        user = _saved_user()
        profile = _mock_profile()

        with (
            caplog.at_level(logging.DEBUG, logger="management.services"),
            patch.object(UserProfile.objects, "get_or_create", return_value=(profile, False)),
        ):
            services.get_user_profile(user)

        assert "test@example.com" in caplog.text or str(user.pk) in caplog.text

    def test_logs_debug_when_creating_profile(self, caplog):
        """get_user_profile logs when creating new profile."""
        user = _saved_user()
        profile = _mock_profile()

        with (
            caplog.at_level(logging.DEBUG, logger="management.services"),
            patch.object(UserProfile.objects, "get_or_create", return_value=(profile, True)),
        ):
            services.get_user_profile(user)

        assert "creat" in caplog.text.lower()


class TestGetUserProfileErrorPropagation:
    """Error propagation behavior for get_user_profile."""

    def test_propagates_database_integrity_error(self):
        """get_user_profile propagates IntegrityError from get_or_create."""
        user = _saved_user()

        with (
            patch.object(UserProfile.objects, "get_or_create", side_effect=IntegrityError("DB constraint")),
            pytest.raises(IntegrityError, match="DB constraint"),
        ):
            services.get_user_profile(user)

    def test_logs_error_on_database_failure(self, caplog):
        """get_user_profile logs error when database operation fails."""
        user = _saved_user()

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


class TestMarkUserDeletedHappyPath:
    """Expected successful behavior for mark_user_deleted."""

    def test_sets_deleted_at_timestamp(self):
        """mark_user_deleted sets deleted_at on the profile and saves it."""
        user = _saved_user()
        profile = _mock_profile(is_deleted=False)

        with (
            patch("management.services.get_user_profile", return_value=profile),
            patch("management.services.audit_log"),
        ):
            services.mark_user_deleted(user)

        profile.save.assert_called_once_with(update_fields=["deleted_at"])
        assert profile.deleted_at is not None

    def test_profile_is_marked_deleted(self):
        """After mark_user_deleted, deleted_at is set on the profile."""
        user = _saved_user()
        profile = _mock_profile(is_deleted=False)

        with (
            patch("management.services.get_user_profile", return_value=profile),
            patch("management.services.audit_log"),
        ):
            services.mark_user_deleted(user)

        assert profile.deleted_at is not None

    def test_creates_profile_via_get_user_profile(self):
        """mark_user_deleted delegates to get_user_profile for profile creation."""
        user = _saved_user()
        profile = _mock_profile(is_deleted=False)

        with (
            patch("management.services.get_user_profile", return_value=profile) as mock_get,
            patch("management.services.audit_log"),
        ):
            services.mark_user_deleted(user)

        mock_get.assert_called_once_with(user)

    def test_returns_none(self):
        """mark_user_deleted returns None (void function)."""
        user = _saved_user()
        profile = _mock_profile(is_deleted=False)

        with (
            patch("management.services.get_user_profile", return_value=profile),
            patch("management.services.audit_log"),
        ):
            result = services.mark_user_deleted(user)

        assert result is None

    def test_is_idempotent(self):
        """mark_user_deleted can be called multiple times (updates timestamp)."""
        user = _saved_user()
        profile = _mock_profile(is_deleted=True)

        with (
            patch("management.services.get_user_profile", return_value=profile),
            patch("management.services.audit_log"),
        ):
            services.mark_user_deleted(user)

        profile.save.assert_called_once_with(update_fields=["deleted_at"])
        assert profile.deleted_at is not None


class TestMarkUserDeletedInputValidation:
    """Input validation behavior for mark_user_deleted."""

    def test_raises_type_error_for_none_user(self):
        """mark_user_deleted raises TypeError when user is None."""
        with pytest.raises(TypeError, match=USER_CANNOT_BE_NONE):
            services.mark_user_deleted(None)

    def test_raises_value_error_for_unsaved_user(self):
        """mark_user_deleted raises ValueError when user has no pk."""
        unsaved_user = _unsaved_user()

        with pytest.raises(ValueError, match="user must have a primary key"):
            services.mark_user_deleted(unsaved_user)


class TestMarkUserDeletedLogging:
    """Logging behavior for mark_user_deleted."""

    def test_logs_debug_on_success(self, caplog):
        """mark_user_deleted logs debug message on success."""
        user = _saved_user()
        profile = _mock_profile(is_deleted=False)

        with (
            caplog.at_level(logging.DEBUG, logger="management.services"),
            patch("management.services.get_user_profile", return_value=profile),
            patch("management.services.audit_log"),
        ):
            services.mark_user_deleted(user)

        assert "test@example.com" in caplog.text or str(user.pk) in caplog.text
        assert "delet" in caplog.text.lower()

    def test_logs_warning_when_already_deleted(self, caplog):
        """mark_user_deleted logs warning when user already deleted."""
        user = _saved_user()
        profile = _mock_profile(is_deleted=True)

        with (
            caplog.at_level(logging.WARNING, logger="management.services"),
            patch("management.services.get_user_profile", return_value=profile),
            patch("management.services.audit_log"),
        ):
            services.mark_user_deleted(user)

        assert "already" in caplog.text.lower()


class TestMarkUserDeletedErrorPropagation:
    """Error propagation behavior for mark_user_deleted."""

    def test_propagates_error_from_get_user_profile(self):
        """mark_user_deleted propagates errors from get_user_profile."""
        user = _saved_user()

        with (
            patch("management.services.get_user_profile", side_effect=IntegrityError("DB constraint")),
            pytest.raises(IntegrityError, match="DB constraint"),
        ):
            services.mark_user_deleted(user)

    def test_propagates_error_from_profile_save(self):
        """mark_user_deleted propagates errors from profile.save()."""
        user = _saved_user()
        profile = _mock_profile(is_deleted=False)
        profile.save.side_effect = IntegrityError("Save failed")

        with (
            patch("management.services.get_user_profile", return_value=profile),
            pytest.raises(IntegrityError, match="Save failed"),
        ):
            services.mark_user_deleted(user)

    def test_logs_error_on_save_failure(self, caplog):
        """mark_user_deleted logs error when save fails."""
        user = _saved_user()
        profile = _mock_profile(is_deleted=False)
        profile.save.side_effect = IntegrityError("Save failed")

        with (
            caplog.at_level(logging.ERROR, logger="management.services"),
            patch("management.services.get_user_profile", return_value=profile),
            pytest.raises(IntegrityError),
        ):
            services.mark_user_deleted(user)

        assert "failed" in caplog.text.lower() or "error" in caplog.text.lower()


# =============================================================================
# create_user_profile
# =============================================================================


class TestCreateUserProfile:
    """Tests for create_user_profile service function."""

    def test_creates_profile_for_user(self):
        """create_user_profile calls UserProfile.objects.create for the user."""
        user = _saved_user()

        with patch.object(UserProfile.objects, "create") as mock_create:
            services.create_user_profile(user)

        mock_create.assert_called_once_with(user=user)

    def test_raises_type_error_for_none_user(self):
        """create_user_profile raises TypeError when user is None."""
        with pytest.raises(TypeError, match=USER_CANNOT_BE_NONE):
            services.create_user_profile(None)

    def test_raises_value_error_for_unsaved_user(self):
        """create_user_profile raises ValueError when user has no pk."""
        unsaved_user = _unsaved_user()

        with pytest.raises(ValueError, match="user must have a primary key"):
            services.create_user_profile(unsaved_user)

    def test_logs_debug_on_success(self, caplog):
        """create_user_profile logs debug message on success."""
        user = _saved_user()

        with (
            caplog.at_level(logging.DEBUG, logger="management.services"),
            patch.object(UserProfile.objects, "create"),
        ):
            services.create_user_profile(user)

        assert "test@example.com" in caplog.text

    def test_logs_error_on_failure(self, caplog):
        """create_user_profile logs error when database operation fails."""
        user = _saved_user()

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


class TestSaveUserProfile:
    """Tests for save_user_profile service function."""

    def test_creates_profile_when_missing(self):
        """save_user_profile calls get_or_create for the user."""
        user = _saved_user()
        profile = _mock_profile()

        with patch.object(UserProfile.objects, "get_or_create", return_value=(profile, True)) as mock_goc:
            services.save_user_profile(user)

        mock_goc.assert_called_once_with(user=user)

    def test_raises_type_error_for_none_user(self):
        """save_user_profile raises TypeError when user is None."""
        with pytest.raises(TypeError, match=USER_CANNOT_BE_NONE):
            services.save_user_profile(None)

    def test_raises_value_error_for_unsaved_user(self):
        """save_user_profile raises ValueError when user has no pk."""
        unsaved_user = _unsaved_user()

        with pytest.raises(ValueError, match="user must have a primary key"):
            services.save_user_profile(unsaved_user)

    def test_logs_debug_on_success(self, caplog):
        """save_user_profile logs debug message on success."""
        user = _saved_user()
        profile = _mock_profile()

        with (
            caplog.at_level(logging.DEBUG, logger="management.services"),
            patch.object(UserProfile.objects, "get_or_create", return_value=(profile, False)),
        ):
            services.save_user_profile(user)

        assert "test@example.com" in caplog.text

    def test_logs_error_on_failure(self, caplog):
        """save_user_profile logs error when database operation fails."""
        user = _saved_user()

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


class TestUpdateCognitoSubHappyPath:
    """Expected successful behavior for update_cognito_sub."""

    def test_updates_cognito_sub_on_profile(self):
        """update_cognito_sub sets cognito_sub on user's profile and saves."""
        user = _saved_user()
        profile = _mock_profile(cognito_sub=None)

        with patch("management.services.get_user_profile", return_value=profile):
            services.update_cognito_sub(user, "abc-123-sub")

        assert profile.cognito_sub == "abc-123-sub"
        profile.save.assert_called_once_with(update_fields=["cognito_sub"])

    def test_creates_profile_when_missing(self):
        """update_cognito_sub delegates to get_user_profile for profile creation."""
        user = _saved_user()
        profile = _mock_profile(cognito_sub=None)

        with patch("management.services.get_user_profile", return_value=profile) as mock_get:
            services.update_cognito_sub(user, "abc-123-sub")

        mock_get.assert_called_once_with(user)
        assert profile.cognito_sub == "abc-123-sub"

    def test_returns_none(self):
        """update_cognito_sub returns None (void function)."""
        user = _saved_user()
        profile = _mock_profile(cognito_sub=None)

        with patch("management.services.get_user_profile", return_value=profile):
            result = services.update_cognito_sub(user, "abc-123-sub")

        assert result is None

    def test_overwrites_existing_cognito_sub(self):
        """update_cognito_sub overwrites existing cognito_sub value."""
        user = _saved_user()
        profile = _mock_profile(cognito_sub="old-sub-value")

        with patch("management.services.get_user_profile", return_value=profile):
            services.update_cognito_sub(user, "new-sub-value")

        assert profile.cognito_sub == "new-sub-value"
        profile.save.assert_called_once_with(update_fields=["cognito_sub"])

    def test_no_op_when_cognito_sub_unchanged(self):
        """update_cognito_sub does not save when value unchanged."""
        user = _saved_user()
        profile = _mock_profile(cognito_sub="same-sub")

        with patch("management.services.get_user_profile", return_value=profile):
            services.update_cognito_sub(user, "same-sub")

        profile.save.assert_not_called()


class TestUpdateCognitoSubInputValidation:
    """Input validation behavior for update_cognito_sub."""

    def test_raises_type_error_for_none_user(self):
        """update_cognito_sub raises TypeError when user is None."""
        with pytest.raises(TypeError, match=USER_CANNOT_BE_NONE):
            services.update_cognito_sub(None, "abc-123")

    def test_raises_value_error_for_unsaved_user(self):
        """update_cognito_sub raises ValueError when user has no pk."""
        unsaved_user = _unsaved_user()

        with pytest.raises(ValueError, match="user must have a primary key"):
            services.update_cognito_sub(unsaved_user, "abc-123")

    def test_raises_type_error_for_none_cognito_sub(self):
        """update_cognito_sub raises TypeError when cognito_sub is None."""
        user = _saved_user()

        with pytest.raises(TypeError, match="cognito_sub cannot be None"):
            services.update_cognito_sub(user, None)

    def test_raises_value_error_for_empty_cognito_sub(self):
        """update_cognito_sub raises ValueError when cognito_sub is empty."""
        user = _saved_user()

        with pytest.raises(ValueError, match="cognito_sub cannot be empty"):
            services.update_cognito_sub(user, "")

    def test_raises_value_error_for_whitespace_cognito_sub(self):
        """update_cognito_sub raises ValueError when cognito_sub is only whitespace."""
        user = _saved_user()

        with pytest.raises(ValueError, match="cognito_sub cannot be empty"):
            services.update_cognito_sub(user, "   ")


class TestUpdateCognitoSubLogging:
    """Logging behavior for update_cognito_sub."""

    def test_logs_info_when_cognito_sub_changes(self, caplog):
        """update_cognito_sub logs INFO when cognito_sub is updated."""
        user = _saved_user()
        profile = _mock_profile(cognito_sub=None)

        with (
            caplog.at_level(logging.INFO, logger="management.services"),
            patch("management.services.get_user_profile", return_value=profile),
        ):
            services.update_cognito_sub(user, "abc-123-sub")

        assert "test@example.com" in caplog.text
        assert "abc-123-sub" in caplog.text

    def test_logs_debug_when_cognito_sub_unchanged(self, caplog):
        """update_cognito_sub logs DEBUG when cognito_sub already matches."""
        user = _saved_user()
        profile = _mock_profile(cognito_sub="same-sub")

        with (
            caplog.at_level(logging.DEBUG, logger="management.services"),
            patch("management.services.get_user_profile", return_value=profile),
        ):
            services.update_cognito_sub(user, "same-sub")

        assert "unchanged" in caplog.text.lower() or "already" in caplog.text.lower()


class TestUpdateCognitoSubErrorPropagation:
    """Error propagation behavior for update_cognito_sub."""

    def test_propagates_error_from_get_user_profile(self):
        """update_cognito_sub propagates errors from get_user_profile."""
        user = _saved_user()

        with (
            patch("management.services.get_user_profile", side_effect=IntegrityError("DB constraint")),
            pytest.raises(IntegrityError, match="DB constraint"),
        ):
            services.update_cognito_sub(user, "abc-123")

    def test_propagates_error_from_profile_save(self):
        """update_cognito_sub propagates errors from profile.save()."""
        user = _saved_user()
        profile = _mock_profile(cognito_sub=None)
        profile.save.side_effect = IntegrityError("Save failed")

        with (
            patch("management.services.get_user_profile", return_value=profile),
            pytest.raises(IntegrityError, match="Save failed"),
        ):
            services.update_cognito_sub(user, "abc-123")

    def test_logs_error_on_save_failure(self, caplog):
        """update_cognito_sub logs error when save fails."""
        user = _saved_user()
        profile = _mock_profile(cognito_sub=None)
        profile.save.side_effect = IntegrityError("Save failed")

        with (
            caplog.at_level(logging.ERROR, logger="management.services"),
            patch("management.services.get_user_profile", return_value=profile),
            pytest.raises(IntegrityError),
        ):
            services.update_cognito_sub(user, "abc-123")

        assert "failed" in caplog.text.lower() or "error" in caplog.text.lower()
