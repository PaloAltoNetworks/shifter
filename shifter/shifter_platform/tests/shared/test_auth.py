"""Tests for shared.auth access control utilities."""

from django.contrib.auth.models import AnonymousUser, Group, User
from django.test import RequestFactory, TestCase
from django.urls import reverse

from shared.auth import (
    THREAT_RESEARCH_GROUP,
    _is_staff_or_threat_researcher,
    threat_research_required,
)

TEST_PASSWORD = "test"  # nosec B105


class IsStaffOrThreatResearcherTest(TestCase):
    """Unit tests for _is_staff_or_threat_researcher helper."""

    @classmethod
    def setUpTestData(cls):
        cls.staff = User.objects.create_user(username="staff", password=TEST_PASSWORD, is_staff=True)
        cls.threat_user = User.objects.create_user(username="threat", password=TEST_PASSWORD, is_staff=False)
        group, _ = Group.objects.get_or_create(name=THREAT_RESEARCH_GROUP)
        cls.threat_user.groups.add(group)
        cls.regular = User.objects.create_user(username="regular", password=TEST_PASSWORD, is_staff=False)
        cls.inactive = User.objects.create_user(
            username="inactive", password=TEST_PASSWORD, is_staff=True, is_active=False
        )

    def test_active_staff_returns_true(self):
        assert _is_staff_or_threat_researcher(self.staff) is True

    def test_active_threat_research_member_returns_true(self):
        assert _is_staff_or_threat_researcher(self.threat_user) is True

    def test_inactive_user_returns_false(self):
        assert _is_staff_or_threat_researcher(self.inactive) is False

    def test_regular_user_returns_false(self):
        assert _is_staff_or_threat_researcher(self.regular) is False

    def test_anonymous_user_returns_false(self):
        assert _is_staff_or_threat_researcher(AnonymousUser()) is False


class ThreatResearchRequiredDecoratorTest(TestCase):
    """Unit tests for the threat_research_required decorator."""

    @classmethod
    def setUpTestData(cls):
        cls.staff = User.objects.create_user(username="dec_staff", password=TEST_PASSWORD, is_staff=True)
        cls.threat_user = User.objects.create_user(username="dec_threat", password=TEST_PASSWORD, is_staff=False)
        group, _ = Group.objects.get_or_create(name=THREAT_RESEARCH_GROUP)
        cls.threat_user.groups.add(group)
        cls.regular = User.objects.create_user(username="dec_regular", password=TEST_PASSWORD, is_staff=False)

    def setUp(self):
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
        # Add session and messages support for the middleware
        from django.contrib.messages.storage.fallback import FallbackStorage
        from django.contrib.sessions.backends.db import SessionStore

        request.session = SessionStore()
        request._messages = FallbackStorage(request)
        return request

    def test_unauthenticated_redirects_to_login(self):
        request = self._make_request()
        resp = self.view(request)
        assert resp.status_code == 302
        # Should redirect to LOGIN_URL, not admin:index
        assert "admin" not in resp.url

    def test_unauthorized_redirects_to_dashboard(self):
        request = self._make_request(user=self.regular)
        resp = self.view(request)
        assert resp.status_code == 302
        assert resp.url == reverse("mission_control:dashboard")

    def test_unauthorized_sets_error_message(self):
        request = self._make_request(user=self.regular)
        self.view(request)
        msgs = [str(m) for m in request._messages]
        assert any("permission" in m.lower() for m in msgs)

    def test_staff_passes_through(self):
        request = self._make_request(user=self.staff)
        resp = self.view(request)
        assert resp.status_code == 200
        assert resp.content == b"ok"

    def test_threat_research_member_passes_through(self):
        request = self._make_request(user=self.threat_user)
        resp = self.view(request)
        assert resp.status_code == 200
        assert resp.content == b"ok"
