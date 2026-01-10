"""Pytest configuration and fixtures for Shifter platform tests."""

import os
from pathlib import Path

# Set testing flag before Django loads settings
os.environ["TESTING"] = "1"

import pytest
from django.test import Client

TESTS_DIR = Path(__file__).parent


@pytest.fixture
def authenticated_client(db):
    """
    Return a Django test client that bypasses OIDC authentication.

    The OIDC SessionRefresh middleware checks for 'oidc_id_token_expiration'
    in the session. Without it, force_login users get redirected to OIDC.
    This fixture sets up the session properly.
    """
    import time

    from django.contrib.auth import get_user_model

    User = get_user_model()

    def _make_client(user=None, email="test@example.com"):
        if user is None:
            user, _ = User.objects.get_or_create(username=email, defaults={"email": email})

        client = Client()
        client.force_login(user)

        # Set OIDC session data to prevent SessionRefresh from redirecting
        session = client.session
        session["oidc_id_token_expiration"] = time.time() + 3600  # 1 hour from now
        session.save()

        return client, user

    return _make_client
