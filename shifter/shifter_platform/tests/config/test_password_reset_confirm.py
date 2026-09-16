"""Tests for the password-reset confirm landing view (PLAT-236, #1943).

The reset-confirm view re-checks eligibility under lock at token redemption so a
URL issued while an account was eligible cannot be redeemed after the account is
suspended, deleted, or provider-bound (review cycle-2 F3), and it audits the
completed change (review F4).
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.test import Client
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from shared.audit import AuditAction, AuditEntityType
from shared.models import AuditLog

pytestmark = pytest.mark.django_db

User = get_user_model()

NEW_PASSWORD = "Str0ng-New-Passw0rd!"


def _reset_urls(user: User) -> tuple[str, str]:
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    return f"/account/password/reset/{uid}/{token}/", f"/account/password/reset/{uid}/set-password/"


def _redeem(client: Client, user: User) -> None:
    """Drive Django's two-step confirm flow: GET stashes the token, POST sets it."""
    confirm_url, set_password_url = _reset_urls(user)
    client.get(confirm_url)  # moves the token into the session, redirects to set-password
    client.post(set_password_url, {"new_password1": NEW_PASSWORD, "new_password2": NEW_PASSWORD})


def test_eligible_redemption_sets_password_and_audits():
    user = User.objects.create_user(username="local", email="local@example.com", password="old-password")
    _redeem(Client(), user)
    user.refresh_from_db()
    assert user.check_password(NEW_PASSWORD)
    assert AuditLog.objects.filter(
        entity_type=AuditEntityType.USER, entity_id=user.id, action=AuditAction.UPDATE
    ).exists()


def test_redemption_rejected_after_suspension():
    # Token issued while eligible; account suspended before the URL is redeemed.
    user = User.objects.create_user(username="local2", email="local2@example.com", password="old-password")
    confirm_url, set_password_url = _reset_urls(user)
    user.is_active = False
    user.save(update_fields=["is_active"])
    user.profile.suspended_at = timezone.now()
    user.profile.save(update_fields=["suspended_at"])

    client = Client()
    client.get(confirm_url)
    client.post(set_password_url, {"new_password1": NEW_PASSWORD, "new_password2": NEW_PASSWORD})

    user.refresh_from_db()
    assert not user.check_password(NEW_PASSWORD)
    assert user.check_password("old-password")


def test_redemption_rejected_after_provider_binding():
    # Token issued for a local account that later became provider-bound.
    user = User.objects.create_user(username="local3", email="local3@example.com", password="old-password")
    confirm_url, set_password_url = _reset_urls(user)
    user.profile.cognito_sub = "sub-xyz"
    user.profile.save(update_fields=["cognito_sub"])

    client = Client()
    client.get(confirm_url)
    client.post(set_password_url, {"new_password1": NEW_PASSWORD, "new_password2": NEW_PASSWORD})

    user.refresh_from_db()
    assert not user.check_password(NEW_PASSWORD)
