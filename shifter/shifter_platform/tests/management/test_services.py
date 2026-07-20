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
from shared.audit import (
    AuditAction,
    AuditEntityType,
)
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
        user_2 = _user("badaction")
        with pytest.raises(TypeError, match="action must be a string"):
            services.log_activity(action, user_2)

    @pytest.mark.parametrize("action", ["", "   "])
    def test_rejects_empty_action(self, action):
        user_2 = _user("emptyaction")
        with pytest.raises(ValueError, match="action cannot be empty"):
            services.log_activity(action, user_2)

    def test_rejects_unsaved_user(self):
        unsaved_user = _unsaved_user()
        with pytest.raises(ValueError, match="user must have a primary key"):
            services.log_activity("a", unsaved_user)

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
        unsaved_user = _unsaved_user()
        with pytest.raises(ValueError, match="user must have a primary key"):
            services.get_user_profile(unsaved_user)


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
            entity_type=AuditEntityType.USER, entity_id=user.id, action=AuditAction.DELETE
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
        row = AuditLog.objects.get(entity_type=AuditEntityType.USER, entity_id=user.id)
        assert row.actor_id == admin.id

    def test_raises_typeerror_for_none_user(self):
        with pytest.raises(TypeError, match=USER_CANNOT_BE_NONE):
            services.mark_user_deleted(None)

    def test_raises_valueerror_for_unsaved_user(self):
        unsaved_user = _unsaved_user()
        with pytest.raises(ValueError, match="user must have a primary key"):
            services.mark_user_deleted(unsaved_user)


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
        unsaved_user = _unsaved_user()
        with pytest.raises(ValueError, match="user must have a primary key"):
            services.create_user_profile(unsaved_user)


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
        unsaved_user = _unsaved_user()
        with pytest.raises(ValueError, match="user must have a primary key"):
            services.save_user_profile(unsaved_user)


# ---------------------------------------------------------------------------
# bind_provider_identity (issue #1521)
#
# Replaces the overwrite-style ``update_cognito_sub`` with bind-once/compare
# semantics: an exact tuple is idempotent, a legacy subject-only row may
# acquire the verified issuer, a fully unbound profile binds once, and any
# other issuer/subject difference -- or a uniqueness collision with a
# different user -- fails closed (``BindingConflictError``), never
# overwrites/backfills/"heals" a stored identity.
# ---------------------------------------------------------------------------

ISSUER_A = "https://issuer-a.example.test"
ISSUER_B = "https://issuer-b.example.test"


class TestBindProviderIdentity:
    def test_binds_unbound_profile_once(self):
        user = _user("bind-fresh")
        outcome = services.bind_provider_identity(user, ISSUER_A, "sub-fresh")

        assert outcome == services.BindOutcome.BOUND
        profile = UserProfile.objects.get(user=user)
        assert profile.issuer == ISSUER_A
        assert profile.cognito_sub == "sub-fresh"

    def test_exact_tuple_is_idempotent(self, caplog):
        user = _user("bind-idem")
        services.bind_provider_identity(user, ISSUER_A, "sub-idem")

        with caplog.at_level(logging.DEBUG, logger="management.services"):
            outcome = services.bind_provider_identity(user, ISSUER_A, "sub-idem")

        assert outcome == services.BindOutcome.UNCHANGED
        profile = UserProfile.objects.get(user=user)
        assert profile.issuer == ISSUER_A
        assert profile.cognito_sub == "sub-idem"

    def test_legacy_subject_only_row_acquires_issuer(self):
        """A pre-#1521 row (subject bound, no issuer) acquires the verified
        issuer only when the presented subject is identical (historical
        unbound/subject-only migration state)."""
        user = _user("bind-legacy")
        profile = UserProfile.objects.get(user=user)
        profile.cognito_sub = "sub-legacy"
        profile.issuer = ""
        profile.save(update_fields=["cognito_sub", "issuer"])

        outcome = services.bind_provider_identity(user, ISSUER_A, "sub-legacy")

        assert outcome == services.BindOutcome.ISSUER_ACQUIRED
        profile.refresh_from_db()
        assert profile.issuer == ISSUER_A
        assert profile.cognito_sub == "sub-legacy"

    def test_issuer_drift_raises_binding_conflict_and_never_rebinds(self):
        user = _user("bind-issuer-drift")
        services.bind_provider_identity(user, ISSUER_A, "sub-drift")

        with pytest.raises(services.BindingConflictError):
            services.bind_provider_identity(user, ISSUER_B, "sub-drift")

        profile = UserProfile.objects.get(user=user)
        assert profile.issuer == ISSUER_A
        assert profile.cognito_sub == "sub-drift"

    def test_subject_drift_raises_binding_conflict_and_never_rebinds(self):
        user = _user("bind-subject-drift")
        services.bind_provider_identity(user, ISSUER_A, "sub-orig")

        with pytest.raises(services.BindingConflictError):
            services.bind_provider_identity(user, ISSUER_A, "sub-new")

        profile = UserProfile.objects.get(user=user)
        assert profile.issuer == ISSUER_A
        assert profile.cognito_sub == "sub-orig"

    def test_collision_with_different_user_raises_binding_conflict(self):
        user_a = _user("bind-collide-a")
        user_b = _user("bind-collide-b")
        services.bind_provider_identity(user_a, ISSUER_A, "sub-shared")

        with pytest.raises(services.BindingConflictError), transaction.atomic():
            services.bind_provider_identity(user_b, ISSUER_A, "sub-shared")

        assert not UserProfile.objects.get(user=user_b).cognito_sub
        assert UserProfile.objects.get(user=user_a).cognito_sub == "sub-shared"

    def test_raises_typeerror_for_none_user(self):
        with pytest.raises(TypeError, match=USER_CANNOT_BE_NONE):
            services.bind_provider_identity(None, ISSUER_A, "sub")

    def test_raises_valueerror_for_unsaved_user(self):
        unsaved_user = _unsaved_user()
        with pytest.raises(ValueError, match="user must have a primary key"):
            services.bind_provider_identity(unsaved_user, ISSUER_A, "sub")

    @pytest.mark.parametrize("value", ["", "   ", None])
    def test_raises_valueerror_for_blank_issuer(self, value):
        user_2 = _user("bind-blank-iss")
        with pytest.raises(ValueError, match="issuer cannot be empty"):
            services.bind_provider_identity(user_2, value, "sub")

    @pytest.mark.parametrize("value", ["", "   ", None])
    def test_raises_valueerror_for_blank_subject(self, value):
        user_2 = _user("bind-blank-sub")
        with pytest.raises(ValueError, match="subject cannot be empty"):
            services.bind_provider_identity(user_2, ISSUER_A, value)
