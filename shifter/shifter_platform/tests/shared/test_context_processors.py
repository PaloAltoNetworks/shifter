"""Tests for shared.context_processors."""

from unittest.mock import MagicMock

from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory

from shared.auth import THREAT_RESEARCH_GROUP
from shared.context_processors import user_permissions


def _make_user(is_staff=False, is_active=True, groups=None):
    """Create a mock user with the given properties."""
    user = MagicMock()
    user.is_staff = is_staff
    user.is_active = is_active
    user.is_authenticated = True
    user.is_anonymous = False
    user.pk = 1
    if groups:
        user.groups.filter.return_value.exists.return_value = True
    else:
        user.groups.filter.return_value.exists.return_value = False
    return user


class TestUserPermissionsContextProcessor:
    """Unit tests for the user_permissions context processor."""

    def setup_method(self):
        self.factory = RequestFactory()

    def _make_request(self, user=None):
        request = self.factory.get("/")
        request.user = user if user else AnonymousUser()
        return request

    def test_unauthenticated_returns_false(self):
        result = user_permissions(self._make_request())
        assert result == {"can_access_threat_research": False}

    def test_staff_returns_true(self):
        result = user_permissions(self._make_request(_make_user(is_staff=True)))
        assert result == {"can_access_threat_research": True}

    def test_threat_research_member_returns_true(self):
        result = user_permissions(self._make_request(_make_user(is_staff=False, groups=[THREAT_RESEARCH_GROUP])))
        assert result == {"can_access_threat_research": True}

    def test_regular_user_returns_false(self):
        result = user_permissions(self._make_request(_make_user(is_staff=False)))
        assert result == {"can_access_threat_research": False}
