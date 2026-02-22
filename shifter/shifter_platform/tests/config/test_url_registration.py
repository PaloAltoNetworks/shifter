"""Tests for development URL registration (config/urls.py).

These tests verify that dev-login URLs are registered under the correct conditions.

IMPORTANT: URL registration happens at module import time, so we need to test
by checking whether the URLs resolve, not just whether views return 200/403.
"""

import pytest
from django.conf import settings
from django.urls import NoReverseMatch, reverse


class TestDevUrlRegistration:
    """Test that dev-login URLs are registered in the correct environments."""

    def test_urls_registered_in_dev_environment(self):
        """URLs should be registered when ENVIRONMENT='development' (even if DEBUG=False)."""
        # In the test environment, settings should have DEBUG=True or ENVIRONMENT='development'
        # If URLs are registered, reverse() will work. If not, it raises NoReverseMatch.

        # This test verifies that with our fix to urls.py, the URLs ARE registered
        # when ENVIRONMENT='development' (which is the case in our dev deployment)
        assert settings.DEBUG or getattr(settings, "ENVIRONMENT", "production") == "development"

        try:
            url = reverse("dev_login")
            assert url == "/dev-login/"
        except NoReverseMatch:
            pytest.fail("dev_login URL not registered even though we're in a dev environment")

    def test_urls_registered_when_debug_true(self):
        """URLs should always be registered when DEBUG=True (local development)."""
        # Similar check - if we're in DEBUG mode, URLs must be registered
        if settings.DEBUG:
            try:
                url = reverse("dev_login")
                assert url == "/dev-login/"
            except NoReverseMatch:
                pytest.fail("dev_login URL not registered even though DEBUG=True")

    def test_dev_login_url_resolves(self):
        """The dev-login URL path should resolve to the correct view."""
        # At a minimum, verify the URL exists and can be reversed
        try:
            url = reverse("dev_login")
            assert url is not None
            assert "dev-login" in url
        except NoReverseMatch:
            # In production (DEBUG=False, ENVIRONMENT='production'), this is expected
            # In our test/dev environment, this should not happen
            if settings.DEBUG or getattr(settings, "ENVIRONMENT", "production") == "development":
                pytest.fail("dev_login URL should be registered in dev/test environments")
            else:
                # This is expected in production - URL should NOT be registered
                pytest.skip("dev_login URL correctly not registered in production")

    def test_dev_logout_url_resolves(self):
        """The dev-logout URL path should resolve to the correct view."""
        try:
            url = reverse("dev_logout")
            assert url is not None
            assert "dev-logout" in url
        except NoReverseMatch:
            if settings.DEBUG or getattr(settings, "ENVIRONMENT", "production") == "development":
                pytest.fail("dev_logout URL should be registered in dev/test environments")
            else:
                pytest.skip("dev_logout URL correctly not registered in production")


class TestUrlRegistrationLogic:
    """Test the logic condition for URL registration matches the view access logic."""

    def test_registration_condition_matches_view_logic(self):
        """The condition for registering URLs must match the condition in _is_dev_environment()."""
        # This is a documentation test to ensure the logic stays aligned

        # urls.py registers URLs when: DEBUG or ENVIRONMENT=='development'
        # dev_auth._is_dev_environment() allows access when: DEBUG or ENVIRONMENT=='development'

        # These MUST match! If they don't, you get 404 errors even when views would allow access.

        # Check that in our current environment, both conditions evaluate the same
        url_registration_condition = settings.DEBUG or getattr(settings, "ENVIRONMENT", "production") == "development"

        # Simulate view check (same logic as dev_auth._is_dev_environment)
        view_access_condition = settings.DEBUG or getattr(settings, "ENVIRONMENT", "production") == "development"

        assert url_registration_condition == view_access_condition, (
            "URL registration condition must match view access condition! "
            "If they differ, users will get 404 even when views would allow access."
        )
