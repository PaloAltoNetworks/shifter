"""Behavior tests for the management service interface.

Drives the real services against real ``UserProfile`` / ``ActivityLog`` /
``AuditLog`` rows instead of patching ``ActivityLog.log`` /
``UserProfile.objects`` / ``audit_log`` / ``get_user_profile``. Note: a
``post_save`` signal (management.apps) auto-creates a ``UserProfile`` for every
new user, so tests that need the "no profile yet" path delete it first.

Generic fault-injection tests (mock a dependency to raise ``IntegrityError`` then
assert it propagates / is logged) are dropped per the boundary-mock-policy intent;
the one real constraint (duplicate ``UserProfile``) is exercised directly.
"""

import logging

import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.utils import timezone

from management import services
from management.models import ActivityLog, UserProfile
from risk_register.models import AuditLog
from shared.constants import USER_CANNOT_BE_NONE

pytestmark = pytest.mark.django_db

User = get_user_model()


def _user(suffix="u"):
    return User.objects.create_user(username=f"mgmt-{suffix}@e.com", email=f"mgmt-{suffix}@e.com")


def _unsaved_user():
    return User(username="unsaved@e.com", email="unsaved@e.com")


# ---------------------------------------------------------------------------
# log_activity
# ---------------------------------------------------------------------------


class TestLogActivity:
    def test_creates_activity_log_row(self):
        user = _user("log")
        services.log_activity("range_launched", user, key1="v1", nested={"a": 1})

        row = ActivityLog.objects.get(action="range_launched")
        assert row.user_id == user.id
        assert row.metadata == {"key1": "v1", "nested": {"a": 1}}

    def test_anonymous_action_has_no_user(self):
        services.log_activity("system_action", user=None)
        row = ActivityLog.objects.get(action="system_action")
        assert row.user is None

    @pytest.mark.parametrize("action", [None, 123])
    def test_rejects_non_string_action(self, action):
        with pytest.raises(TypeError, match="action must be a string"):
            services.log_activity(action, _user("badaction"))

    @pytest.mark.parametrize("action", ["", "   "])
    def test_rejects_empty_action(self, action):
        with pytest.raises(ValueError, match="action cannot be empty"):
            services.log_activity(action, _user("emptyaction"))

    def test_rejects_unsaved_user(self):
        with pytest.raises(ValueError, match="user must have a primary key"):
            services.log_activity("a", _unsaved_user())

    def test_logs_debug_on_success(self, caplog):
        user = _user("logdbg")
        with caplog.at_level(logging.DEBUG, logger="management.services"):
            services.log_activity("audited_action", user)
        assert "audited_action" in caplog.text


# ---------------------------------------------------------------------------
# get_user_profile
# ---------------------------------------------------------------------------


class TestGetUserProfile:
    def test_returns_existing_profile(self):
        user = _user("getexisting")
        profile = UserProfile.objects.get(user=user)  # auto-created by signal
        profile.cognito_sub = "abc-123"
        profile.save(update_fields=["cognito_sub"])

        result = services.get_user_profile(user)
        assert isinstance(result, UserProfile)
        assert result.pk == profile.pk
        assert result.cognito_sub == "abc-123"

    def test_creates_profile_when_missing(self):
        user = _user("getmissing")
        UserProfile.objects.filter(user=user).delete()  # remove the auto-created one

        result = services.get_user_profile(user)
        assert isinstance(result, UserProfile)
        assert UserProfile.objects.filter(user=user).exists()

    def test_raises_typeerror_for_none_user(self):
        with pytest.raises(TypeError, match=USER_CANNOT_BE_NONE):
            services.get_user_profile(None)

    def test_raises_valueerror_for_unsaved_user(self):
        with pytest.raises(ValueError, match="user must have a primary key"):
            services.get_user_profile(_unsaved_user())


# ---------------------------------------------------------------------------
# mark_user_deleted
# ---------------------------------------------------------------------------


class TestMarkUserDeleted:
    def test_sets_deleted_at_and_audits(self):
        user = _user("markdel")
        services.mark_user_deleted(user)

        profile = UserProfile.objects.get(user=user)
        assert profile.deleted_at is not None
        assert AuditLog.objects.filter(
            entity_type=AuditLog.EntityType.USER, entity_id=user.id, action=AuditLog.Action.DELETE
        ).exists()

    def test_idempotent_when_already_deleted(self, caplog):
        user = _user("markdel2")
        profile = UserProfile.objects.get(user=user)
        profile.deleted_at = timezone.now()
        profile.save(update_fields=["deleted_at"])

        with caplog.at_level(logging.WARNING, logger="management.services"):
            services.mark_user_deleted(user)
        profile.refresh_from_db()
        assert profile.deleted_at is not None
        assert "already" in caplog.text.lower()

    def test_records_admin_actor_when_provided(self):
        user = _user("markdel3")
        admin = _user("markdel-admin")
        services.mark_user_deleted(user, admin_user=admin)
        row = AuditLog.objects.get(entity_type=AuditLog.EntityType.USER, entity_id=user.id)
        assert row.actor_id == admin.id

    def test_raises_typeerror_for_none_user(self):
        with pytest.raises(TypeError, match=USER_CANNOT_BE_NONE):
            services.mark_user_deleted(None)

    def test_raises_valueerror_for_unsaved_user(self):
        with pytest.raises(ValueError, match="user must have a primary key"):
            services.mark_user_deleted(_unsaved_user())


# ---------------------------------------------------------------------------
# create_user_profile
# ---------------------------------------------------------------------------


class TestCreateUserProfile:
    def test_creates_profile(self):
        user = _user("createprof")
        UserProfile.objects.filter(user=user).delete()  # remove the auto-created one

        services.create_user_profile(user)
        assert UserProfile.objects.filter(user=user).exists()

    def test_duplicate_profile_raises_integrity_error(self):
        user = _user("createdup")  # already has an auto-created profile
        with pytest.raises(IntegrityError), transaction.atomic():
            services.create_user_profile(user)

    def test_raises_typeerror_for_none_user(self):
        with pytest.raises(TypeError, match=USER_CANNOT_BE_NONE):
            services.create_user_profile(None)

    def test_raises_valueerror_for_unsaved_user(self):
        with pytest.raises(ValueError, match="user must have a primary key"):
            services.create_user_profile(_unsaved_user())


# ---------------------------------------------------------------------------
# save_user_profile
# ---------------------------------------------------------------------------


class TestSaveUserProfile:
    def test_is_idempotent(self):
        user = _user("saveprof")
        services.save_user_profile(user)
        services.save_user_profile(user)
        assert UserProfile.objects.filter(user=user).count() == 1

    def test_raises_typeerror_for_none_user(self):
        with pytest.raises(TypeError, match=USER_CANNOT_BE_NONE):
            services.save_user_profile(None)

    def test_raises_valueerror_for_unsaved_user(self):
        with pytest.raises(ValueError, match="user must have a primary key"):
            services.save_user_profile(_unsaved_user())


# ---------------------------------------------------------------------------
# update_cognito_sub
# ---------------------------------------------------------------------------


class TestUpdateCognitoSub:
    def test_sets_cognito_sub(self):
        user = _user("cog1")
        services.update_cognito_sub(user, "abc-123-sub")
        assert UserProfile.objects.get(user=user).cognito_sub == "abc-123-sub"

    def test_overwrites_existing(self):
        user = _user("cog2")
        services.update_cognito_sub(user, "old")
        services.update_cognito_sub(user, "new")
        assert UserProfile.objects.get(user=user).cognito_sub == "new"

    def test_no_op_when_unchanged(self, caplog):
        user = _user("cog3")
        services.update_cognito_sub(user, "same")
        with caplog.at_level(logging.DEBUG, logger="management.services"):
            services.update_cognito_sub(user, "same")
        assert UserProfile.objects.get(user=user).cognito_sub == "same"
        assert "unchanged" in caplog.text.lower()

    def test_raises_typeerror_for_none_user(self):
        with pytest.raises(TypeError, match=USER_CANNOT_BE_NONE):
            services.update_cognito_sub(None, "abc")

    def test_raises_valueerror_for_unsaved_user(self):
        with pytest.raises(ValueError, match="user must have a primary key"):
            services.update_cognito_sub(_unsaved_user(), "abc")

    def test_raises_typeerror_for_none_cognito_sub(self):
        with pytest.raises(TypeError, match="cognito_sub cannot be None"):
            services.update_cognito_sub(_user("cog-none"), None)

    @pytest.mark.parametrize("value", ["", "   "])
    def test_raises_valueerror_for_empty_cognito_sub(self, value):
        with pytest.raises(ValueError, match="cognito_sub cannot be empty"):
            services.update_cognito_sub(_user("cog-empty"), value)
