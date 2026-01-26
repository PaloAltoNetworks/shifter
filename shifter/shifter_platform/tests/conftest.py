"""Pytest configuration and fixtures for Shifter platform tests."""

import logging
import os
import sys
from pathlib import Path

# Add shifter/ to path so 'cyberscript' package is importable
# Must be done before Django loads settings
SHIFTER_DIR = Path(__file__).resolve().parent.parent.parent
if str(SHIFTER_DIR) not in sys.path:
    sys.path.insert(0, str(SHIFTER_DIR))

# Set testing flag before Django loads settings
os.environ["TESTING"] = "1"

import pytest  # noqa: E402
from django.test import Client  # noqa: E402

TESTS_DIR = Path(__file__).parent


@pytest.fixture(autouse=True)
def enable_log_propagation():
    """Enable log propagation for caplog to work with our configured loggers.

    Django settings sets propagate=False on our loggers (engine, cms, etc.)
    which prevents pytest's caplog from capturing log records. This fixture
    temporarily enables propagation for all tests.
    """
    loggers = ["engine", "cms", "mission_control", "engine.handlers"]
    original_propagate = {}

    for name in loggers:
        logger = logging.getLogger(name)
        original_propagate[name] = logger.propagate
        logger.propagate = True

    yield

    # Restore original propagation settings
    for name, propagate in original_propagate.items():
        logging.getLogger(name).propagate = propagate


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
