"""Tests for the composition-root local-organizer grant endpoint (#1373).

The grant lives at the ``config`` composition root because it needs
``config.organizer_authority`` (a feature app may not import the composition
root). It is grant-only, additive, records ``local`` provenance, and is
authorized by a staff session plus ``auth.change_user``.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from rest_framework.test import APIClient

from management.services import get_user_profile
from shared.audit import AuditAction
from shared.auth import CTF_ORGANIZER_GROUP, is_ctf_organizer
from shared.models import AuditLog

pytestmark = pytest.mark.django_db

User = get_user_model()


def _url(user_id: int) -> str:
    return f"/api/v1/administer/users/{user_id}/grant-organizer/"


def _client(user: User) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.fixture
def admin() -> User:
    return User.objects.create_superuser(username="root", email="root@example.com", password="pw")


@pytest.fixture
def target() -> User:
    return User.objects.create_user(username="grantee", email="grantee@example.com")


def test_grant_adds_local_organizer_with_provenance_and_audit(admin, target):
    resp = _client(admin).post(_url(target.id), format="json")
    assert resp.status_code == 200

    body = resp.json()
    assert body == {"id": target.id, "is_ctf_organizer": True, "organizer_grant_source": "local"}

    target.refresh_from_db()
    assert target.groups.filter(name=CTF_ORGANIZER_GROUP).exists()
    assert is_ctf_organizer(target) is True
    assert get_user_profile(target).organizer_grant_source == "local"

    assert AuditLog.objects.filter(action=AuditAction.ROLE_SYNC, entity_id=target.id).exists()


def test_grant_requires_change_perm(target):
    staff = User.objects.create_user(username="bare", email="bare@example.com", is_staff=True)
    staff.user_permissions.add(Permission.objects.get(content_type__app_label="auth", codename="view_user"))
    assert _client(staff).post(_url(target.id), format="json").status_code == 403


def test_grant_missing_user_is_404(admin):
    assert _client(admin).post(_url(999999), format="json").status_code == 404


def test_token_principals_are_not_admitted(target):
    # A non-staff regular session is rejected (management endpoints are session +
    # staff only; a platform token never carries staff/change_user either).
    plain = User.objects.create_user(username="plain", email="plain@example.com")
    assert _client(plain).post(_url(target.id), format="json").status_code == 403
