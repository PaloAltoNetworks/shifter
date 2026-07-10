"""Tests for shared.context_processors."""

from unittest.mock import MagicMock

from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, override_settings

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
    # Group predicates resolve membership via shared.auth.get_user_group_names,
    # which reads values_list("name", flat=True) once per request.
    user.groups.values_list.return_value = list(groups or [])
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
        assert result == {
            "can_access_threat_research": False,
            "can_access_risk_register": False,
        }

    def test_staff_returns_true(self):
        result = user_permissions(self._make_request(_make_user(is_staff=True)))
        assert result["can_access_threat_research"] is True
        assert result["can_access_risk_register"] is False

    def test_threat_research_member_returns_true(self):
        result = user_permissions(self._make_request(_make_user(is_staff=False, groups=[THREAT_RESEARCH_GROUP])))
        assert result == {
            "can_access_threat_research": True,
            "can_access_risk_register": False,
        }

    def test_regular_user_returns_false(self):
        result = user_permissions(self._make_request(_make_user(is_staff=False)))
        assert result == {
            "can_access_threat_research": False,
            "can_access_risk_register": False,
        }

    @override_settings(RISK_REGISTER_ALLOWED_COGNITO_GROUPS=["security"])
    def test_risk_register_flag_propagates_when_authorized(self, monkeypatch):
        monkeypatch.setattr(
            "shared.context_processors.principal_has_risk_register_access",
            lambda request: True,
        )
        result = user_permissions(self._make_request(_make_user(is_staff=False)))
        assert result["can_access_risk_register"] is True
