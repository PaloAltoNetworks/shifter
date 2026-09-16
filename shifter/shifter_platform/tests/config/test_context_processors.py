"""Behavior tests for config.context_processors (moved from shared in #1523).

Drives the real ``user_permissions`` context processor against real ``User`` /
``Group`` rows so the ORM path ``shared.auth.get_user_group_names`` actually
runs (ADR-019-R1 boundary-mock policy).
"""

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser, Group
from django.test import RequestFactory

from config.context_processors import user_permissions
from shared.auth import THREAT_RESEARCH_GROUP

pytestmark = pytest.mark.django_db

User = get_user_model()


def _user(*, is_staff=False, is_active=True, groups=()):
    user = User.objects.create_user(
        username=f"ctx-{is_staff}-{is_active}-{'-'.join(groups) or 'none'}@example.com",
        email="ctx@example.com",
        is_staff=is_staff,
        is_active=is_active,
    )
    for name in groups:
        group, _ = Group.objects.get_or_create(name=name)
        user.groups.add(group)
    return user


def _request(user):
    request = RequestFactory().get("/")
    request.user = user
    return request


class TestUserPermissionsContextProcessor:
    """Unit tests for the user_permissions context processor."""

    def test_unauthenticated_returns_false(self):
        result = user_permissions(_request(AnonymousUser()))
        assert result == {"can_access_threat_research": False}

    def test_staff_returns_true(self):
        result = user_permissions(_request(_user(is_staff=True)))
        assert result["can_access_threat_research"] is True

    def test_threat_research_member_returns_true(self):
        result = user_permissions(_request(_user(groups=[THREAT_RESEARCH_GROUP])))
        assert result == {"can_access_threat_research": True}

    def test_regular_user_returns_false(self):
        result = user_permissions(_request(_user()))
        assert result == {"can_access_threat_research": False}
