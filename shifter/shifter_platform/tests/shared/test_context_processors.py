"""Tests for shared.context_processors."""

from django.contrib.auth.models import AnonymousUser, Group, User
from django.test import RequestFactory, TestCase

from shared.auth import THREAT_RESEARCH_GROUP
from shared.context_processors import user_permissions

TEST_PASSWORD = "test"  # nosec B105


class UserPermissionsContextProcessorTest(TestCase):
    """Unit tests for the user_permissions context processor."""

    @classmethod
    def setUpTestData(cls):
        cls.staff = User.objects.create_user(username="cp_staff", password=TEST_PASSWORD, is_staff=True)
        cls.threat_user = User.objects.create_user(username="cp_threat", password=TEST_PASSWORD, is_staff=False)
        group, _ = Group.objects.get_or_create(name=THREAT_RESEARCH_GROUP)
        cls.threat_user.groups.add(group)
        cls.regular = User.objects.create_user(username="cp_regular", password=TEST_PASSWORD, is_staff=False)

    def setUp(self):
        self.factory = RequestFactory()

    def _make_request(self, user=None):
        request = self.factory.get("/")
        request.user = user if user else AnonymousUser()
        return request

    def test_unauthenticated_returns_false(self):
        result = user_permissions(self._make_request())
        assert result == {"can_access_threat_research": False}

    def test_staff_returns_true(self):
        result = user_permissions(self._make_request(self.staff))
        assert result == {"can_access_threat_research": True}

    def test_threat_research_member_returns_true(self):
        result = user_permissions(self._make_request(self.threat_user))
        assert result == {"can_access_threat_research": True}

    def test_regular_user_returns_false(self):
        result = user_permissions(self._make_request(self.regular))
        assert result == {"can_access_threat_research": False}
