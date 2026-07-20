"""Tests for the bootstrap-admin policy seam (issue #1521).

``apply_bootstrap_admin_flags`` now requires a
:class:`~shared.verified_identity.VerifiedIdentity` instead of a bare email
string, so a caller cannot elevate a user without verified evidence. These
tests drive the real function and the real ``User`` model; only the
constructed ``VerifiedIdentity`` input varies.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings

from config.bootstrap_admin import apply_bootstrap_admin_flags
from shared.verified_identity import VerifiedIdentity

User = get_user_model()


def _identity(email: str) -> VerifiedIdentity:
    return VerifiedIdentity(issuer="https://issuer.example.test", subject="sub-1", email=email, email_verified=True)


@pytest.mark.django_db
class TestApplyBootstrapAdminFlagsRequiresVerifiedIdentity:
    def test_rejects_plain_email_string(self):
        user = User.objects.create_user(username="plain@example.com", email="plain@example.com")
        with pytest.raises(TypeError):
            apply_bootstrap_admin_flags(user, "plain@example.com")

    def test_rejects_none(self):
        user = User.objects.create_user(username="none@example.com", email="none@example.com")
        with pytest.raises(TypeError):
            apply_bootstrap_admin_flags(user, None)


@pytest.mark.django_db
class TestApplyBootstrapAdminFlagsFromVerifiedIdentity:
    @override_settings(
        PLATFORM_BOOTSTRAP_STAFF_EMAILS=["admin@example.com"],
        PLATFORM_BOOTSTRAP_SUPERUSER_EMAILS=["admin@example.com"],
    )
    def test_grants_staff_and_superuser_from_identity_email(self):
        user = User.objects.create_user(username="admin@example.com", email="admin@example.com")

        updated = apply_bootstrap_admin_flags(user, _identity("admin@example.com"))

        user.refresh_from_db()
        assert user.is_staff is True
        assert user.is_superuser is True
        assert set(updated) == {"is_staff", "is_superuser"}

    @override_settings(PLATFORM_BOOTSTRAP_STAFF_EMAILS=[], PLATFORM_BOOTSTRAP_SUPERUSER_EMAILS=[])
    def test_revokes_flags_no_longer_in_bootstrap_lists(self):
        user = User.objects.create_user(
            username="was-admin@example.com", email="was-admin@example.com", is_staff=True, is_superuser=True
        )

        updated = apply_bootstrap_admin_flags(user, _identity("was-admin@example.com"))

        user.refresh_from_db()
        assert user.is_staff is False
        assert user.is_superuser is False
        assert set(updated) == {"is_staff", "is_superuser"}

    def test_returns_empty_list_when_no_change(self):
        user = User.objects.create_user(username="plain2@example.com", email="plain2@example.com")

        updated = apply_bootstrap_admin_flags(user, _identity("plain2@example.com"))

        assert updated == []

    @override_settings(PLATFORM_BOOTSTRAP_STAFF_EMAILS=["MIXED@Example.COM"])
    def test_email_comparison_is_case_and_whitespace_insensitive(self):
        user = User.objects.create_user(username="mixed@example.com", email="mixed@example.com")

        apply_bootstrap_admin_flags(user, _identity("  mixed@example.com  "))

        user.refresh_from_db()
        assert user.is_staff is True
