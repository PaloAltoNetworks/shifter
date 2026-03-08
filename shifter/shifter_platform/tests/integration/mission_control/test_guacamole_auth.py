"""Integration test for Guacamole JSON auth token exchange.

Requires the Docker Compose stack running (db, guacd, guacamole).
Run with: pytest -m integration tests/integration/mission_control/test_guacamole_auth.py
"""

import os
import urllib.error
import urllib.request

import pytest

from mission_control.guacamole import (
    create_guacamole_auth_payload,
    create_rdp_connection_params,
    get_guacamole_auth_token,
    sign_and_encrypt_payload,
)

pytestmark = pytest.mark.integration

GUACAMOLE_URL = os.environ.get("GUACAMOLE_API_BASE_URL", "http://localhost:8080/guacamole")
GUACAMOLE_SECRET = os.environ.get("GUACAMOLE_JSON_AUTH_SECRET", "4c0b569e4c96df157c1b1fae5ef3a9d0")


def _guacamole_reachable():
    """Check if Guacamole is reachable."""
    try:
        req = urllib.request.Request(f"{GUACAMOLE_URL}/", method="GET")  # noqa: S310
        with urllib.request.urlopen(req, timeout=3):  # noqa: S310
            return True
    except (urllib.error.URLError, OSError):
        return False


skip_if_no_guacamole = pytest.mark.skipif(
    not _guacamole_reachable(),
    reason=f"Guacamole not reachable at {GUACAMOLE_URL}",
)


@skip_if_no_guacamole
class TestGuacamoleJsonAuth:
    """Test the JSON auth token exchange against a live Guacamole instance."""

    def test_token_exchange_with_rdp_connection(self):
        """Verify Django can obtain an auth token from Guacamole.

        This tests the full crypto pipeline:
        1. Create JSON auth payload with an RDP connection
        2. HMAC-SHA256 sign + AES-128-CBC encrypt
        3. POST to /api/tokens
        4. Receive a valid authToken
        """
        connections = {
            "test-rdp": {
                "protocol": "rdp",
                "parameters": create_rdp_connection_params(
                    hostname="10.0.0.1",
                    port=3389,
                ),
            }
        }

        payload = create_guacamole_auth_payload(
            username="integration-test@example.com",
            connections=connections,
        )
        encrypted_data = sign_and_encrypt_payload(payload, GUACAMOLE_SECRET)
        token = get_guacamole_auth_token(GUACAMOLE_URL, encrypted_data)

        assert token, "Expected a non-empty auth token"
        assert isinstance(token, str)
        assert len(token) > 10, "Token looks too short to be valid"

    def test_token_exchange_with_ssh_connection(self):
        """Verify token exchange works for SSH connections too."""
        connections = {
            "test-ssh": {
                "protocol": "ssh",
                "parameters": {
                    "hostname": "10.0.0.2",
                    "port": "22",
                    "username": "kali",
                },
            }
        }

        payload = create_guacamole_auth_payload(
            username="integration-test@example.com",
            connections=connections,
        )
        encrypted_data = sign_and_encrypt_payload(payload, GUACAMOLE_SECRET)
        token = get_guacamole_auth_token(GUACAMOLE_URL, encrypted_data)

        assert token
        assert isinstance(token, str)

    def test_wrong_secret_is_rejected(self):
        """Verify Guacamole rejects payloads signed with wrong key."""
        connections = {
            "test-rdp": {
                "protocol": "rdp",
                "parameters": {"hostname": "10.0.0.1", "port": "3389"},
            }
        }

        payload = create_guacamole_auth_payload(
            username="integration-test@example.com",
            connections=connections,
        )
        wrong_secret = "00000000000000000000000000000000"
        encrypted_data = sign_and_encrypt_payload(payload, wrong_secret)

        with pytest.raises(ValueError, match="Failed to get Guacamole auth token"):
            get_guacamole_auth_token(GUACAMOLE_URL, encrypted_data)
