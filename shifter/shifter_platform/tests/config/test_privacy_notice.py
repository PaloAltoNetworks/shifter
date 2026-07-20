"""Behavior tests for the public privacy notice route and cookie notice shell."""

import pytest
from django.test import Client
from django.urls import reverse

pytestmark = pytest.mark.django_db


class TestPrivacyNoticeView:
    URL = reverse("privacy_notice")

    def test_public_get_renders_placeholder(self):
        response = Client().get(self.URL)
        assert response.status_code == 200
        content = response.content.decode()
        assert "deployment operator" in content.lower()
        assert "/terms/" not in content

    def test_public_head_allowed(self):
        assert Client().head(self.URL).status_code == 200

    def test_post_not_allowed(self):
        assert Client().post(self.URL).status_code == 405

    def test_includes_cookie_notice_partial(self):
        response = Client().get(self.URL)
        content = response.content.decode()
        assert 'id="cookie-notice"' in content
        assert "cookie-notice.js" in content


class TestCookieNoticeOnPortalShell:
    def test_home_includes_cookie_notice(self):
        response = Client().get(reverse("home"))
        assert response.status_code == 200
        content = response.content.decode()
        assert 'id="cookie-notice"' in content
        assert reverse("privacy_notice") in content
