"""Tests for shared.auth access control utilities."""

from unittest.mock import MagicMock

from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory

from shared.auth import (
    THREAT_RESEARCH_GROUP,
    can_edit_cms_authoring,
    threat_research_required,
)


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


class TestCanEditCmsAuthoring:
    """Unit tests for can_edit_cms_authoring helper."""

    def test_active_staff_returns_true(self):
        user = _make_user(is_staff=True)
        assert can_edit_cms_authoring(user) is True

    def test_active_threat_research_member_returns_true(self):
        user = _make_user(is_staff=False, groups=[THREAT_RESEARCH_GROUP])
        assert can_edit_cms_authoring(user) is True

    def test_inactive_staff_returns_false(self):
        user = _make_user(is_staff=True, is_active=False)
        assert can_edit_cms_authoring(user) is False

    def test_inactive_threat_research_member_returns_false(self):
        user = _make_user(is_staff=False, is_active=False, groups=[THREAT_RESEARCH_GROUP])
        assert can_edit_cms_authoring(user) is False

    def test_regular_user_returns_false(self):
        user = _make_user(is_staff=False)
        assert can_edit_cms_authoring(user) is False

    def test_anonymous_user_returns_false(self):
        assert can_edit_cms_authoring(AnonymousUser()) is False


class TestThreatResearchRequiredDecorator:
    """Unit tests for the threat_research_required decorator."""

    def setup_method(self):
        self.factory = RequestFactory()

        from django.http import HttpResponse

        @threat_research_required
        def dummy_view(request):
            return HttpResponse("ok")

        self.view = dummy_view

    def _make_request(self, user=None):
        request = self.factory.get("/test/")
        if user is None:
            request.user = AnonymousUser()
        else:
            request.user = user
        from django.contrib.messages.storage.fallback import FallbackStorage

        request.session = {}
        request._messages = FallbackStorage(request)
        return request

    def test_unauthenticated_redirects_to_login(self):
        request = self._make_request()
        resp = self.view(request)
        assert resp.status_code == 302
        assert "admin" not in resp.url

    def test_unauthorized_redirects_to_dashboard(self):
        user = _make_user(is_staff=False)
        request = self._make_request(user=user)
        resp = self.view(request)
        assert resp.status_code == 302
        # The redirect URL should be the mission_control:dashboard URL
        assert "mission-control" in resp.url

    def test_unauthorized_sets_error_message(self):
        user = _make_user(is_staff=False)
        request = self._make_request(user=user)
        self.view(request)
        msgs = [str(m) for m in request._messages]
        assert any("permission" in m.lower() for m in msgs)

    def test_staff_passes_through(self):
        user = _make_user(is_staff=True)
        request = self._make_request(user=user)
        resp = self.view(request)
        assert resp.status_code == 200
        assert resp.content == b"ok"

    def test_threat_research_member_passes_through(self):
        user = _make_user(is_staff=False, groups=[THREAT_RESEARCH_GROUP])
        request = self._make_request(user=user)
        resp = self.view(request)
        assert resp.status_code == 200
        assert resp.content == b"ok"
