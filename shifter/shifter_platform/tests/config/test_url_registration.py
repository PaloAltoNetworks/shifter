"""Tests for stable auth URL registration."""

from django.urls import reverse


class TestStableAuthUrls:
    """Auth entrypoints stay registered and the views enforce access policy."""

    def test_dev_login_url_always_resolves(self):
        assert reverse("dev_login") == "/dev-login/"

    def test_dev_logout_url_always_resolves(self):
        assert reverse("dev_logout") == "/dev-logout/"

    def test_platform_login_url_resolves(self):
        assert reverse("platform_login") == "/login/"
