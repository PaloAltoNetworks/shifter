"""Behavior tests for the Guacamole SSH client in mission_control/guacamole.py.

``JsonAuthGuacamoleClient.create_ssh_url`` is driven end to end: the real
connection-params, payload-assembly and AES/HMAC sign-and-encrypt code runs, and
only the urllib ``/api/tokens`` POST is mocked (the real network boundary).
Assertions read the returned URL and the decrypted payload that was actually
POSTed, instead of patching the first-party ``create_guacamole_auth_payload`` /
``sign_and_encrypt_payload`` helpers. Deployment config (URLs, signing secret,
retry policy) lives in ``GuacamoleClientConfig`` — the client never reads Django
settings.
"""

import urllib.error
from unittest.mock import patch

import pytest

# 32 hex chars = 16-byte AES-128 key (mirrors conftest.SECRET_KEY_128).
SECRET_KEY_128 = "0123456789abcdef0123456789abcdef"  # nosec B105  # NOSONAR


def _ssh_req(**overrides):
    """Build a per-session ``GuacSSHUrlRequest`` with sensible test defaults."""
    from mission_control.guacamole import GuacSSHUrlRequest

    defaults = {
        "username": "test@example.com",
        "connection_name": "ngfw-123",
        "hostname": "10.1.5.10",
    }
    defaults.update(overrides)
    return GuacSSHUrlRequest(**defaults)


def _client(**config_overrides):
    """Build a ``JsonAuthGuacamoleClient`` from test config defaults."""
    from mission_control.guacamole import GuacamoleClientConfig, JsonAuthGuacamoleClient

    defaults = {
        "base_url": "https://guac.example.com",
        "secret_key": SECRET_KEY_128,
    }
    defaults.update(config_overrides)
    return JsonAuthGuacamoleClient(GuacamoleClientConfig(**defaults))


@pytest.fixture
def fake_private_key():
    """Generate a fake private key for testing that won't trigger security scanners."""
    # Construct dynamically to avoid pattern matching by security scanners
    # This is NOT a real key - it's only for testing SSH parameter passing
    header = "-----BEGIN " + "RSA PRIVATE " + "KEY-----"
    footer = "-----END " + "RSA PRIVATE " + "KEY-----"
    return f"{header}\n{'x' * 64}\n{footer}"


class TestSignAndEncryptPayload:
    """Tests for sign_and_encrypt_payload()."""

    @pytest.mark.parametrize(
        "secret_key",
        [
            "0123456789abcdef0123456789abcdef",  # 128-bit
            ("0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"),  # 256-bit
        ],
    )
    def test_accepts_valid_aes_key_lengths(self, secret_key):
        """Function accepts valid hex key lengths used for AES keys."""
        from mission_control.guacamole import sign_and_encrypt_payload

        payload = {
            "username": "user@example.com",
            "expires": 1234567890,
            "connections": {},
        }

        result = sign_and_encrypt_payload(payload, secret_key)

        assert isinstance(result, str)
        assert result

    def test_raises_for_invalid_key_length(self):
        """Function raises clear error for unsupported key length."""
        from mission_control.guacamole import sign_and_encrypt_payload

        payload = {
            "username": "user@example.com",
            "expires": 1234567890,
            "connections": {},
        }

        with pytest.raises(ValueError, match="32, 48, or 64 hex characters"):
            sign_and_encrypt_payload(payload, "0123456789abcdef0123456789ab")


class TestCreateSSHConnectionParams:
    """Tests for create_ssh_connection_params()."""

    def test_returns_dict_with_required_fields(self):
        """Function returns dict with hostname, port, username."""
        from mission_control.guacamole import create_ssh_connection_params

        result = create_ssh_connection_params(
            username="admin",
            hostname="10.1.5.10",
        )

        assert isinstance(result, dict)
        assert result["hostname"] == "10.1.5.10"
        assert result["port"] == "22"
        assert result["username"] == "admin"

    def test_includes_private_key_when_provided(self, fake_private_key):
        """Function includes private-key parameter when ssh_private_key provided."""
        from mission_control.guacamole import create_ssh_connection_params

        result = create_ssh_connection_params(
            username="admin",
            hostname="10.1.5.10",
            ssh_private_key=fake_private_key,
        )

        assert "private-key" in result
        assert result["private-key"] == fake_private_key

    def test_omits_private_key_when_not_provided(self):
        """Function omits private-key parameter when ssh_private_key is None."""
        from mission_control.guacamole import create_ssh_connection_params

        result = create_ssh_connection_params(
            username="admin",
            hostname="10.1.5.10",
        )

        assert "private-key" not in result

    def test_uses_custom_port(self):
        """Function uses custom port when specified."""
        from mission_control.guacamole import create_ssh_connection_params

        result = create_ssh_connection_params(
            username="admin",
            hostname="10.1.5.10",
            port=2222,
        )

        assert result["port"] == "2222"

    def test_includes_terminal_settings(self):
        """Function includes terminal configuration."""
        from mission_control.guacamole import create_ssh_connection_params

        result = create_ssh_connection_params(
            username="admin",
            hostname="10.1.5.10",
        )

        # Should have reasonable terminal defaults
        assert "color-scheme" in result
        assert "font-name" in result
        assert "enable-clipboard" in result


class TestJsonAuthGuacamoleClientSSHURL:
    """Tests for JsonAuthGuacamoleClient.create_ssh_url() (real crypto, mocked POST)."""

    def test_signs_payload_with_provided_username(self, guac_exchange):
        with guac_exchange() as exchange:
            _client().create_ssh_url(_ssh_req())

        payload = exchange.posted_payload(SECRET_KEY_128)
        assert payload["username"] == "test@example.com"

    def test_creates_ssh_connection_in_payload(self, guac_exchange):
        with guac_exchange() as exchange:
            _client().create_ssh_url(_ssh_req())

        connections = exchange.posted_payload(SECRET_KEY_128)["connections"]
        assert "ngfw-123" in connections
        assert connections["ngfw-123"]["protocol"] == "ssh"

    def test_returns_valid_url_format(self, guac_exchange):
        with guac_exchange():
            result = _client().create_ssh_url(_ssh_req())

        assert result.startswith("https://guac.example.com/#/client/")
        assert "token=token123" in result

    def test_uses_api_base_url_for_token_exchange(self, guac_exchange):
        with guac_exchange() as exchange:
            _client(
                base_url="https://public.example.com",
                api_base_url="https://internal.example.com",
            ).create_ssh_url(_ssh_req())

        # The token POST targets the internal API URL; the public URL is only
        # used to build the returned browser URL.
        assert exchange.requests[0].full_url == "https://internal.example.com/api/tokens"

    def test_raises_on_token_exchange_failure(self):
        def _boom(req, timeout=None):
            raise urllib.error.URLError("guacamole down")

        # retry_attempts=1: fail fast, no backoff retries. Client/request are
        # built outside the raises block so it holds exactly one possibly-
        # throwing invocation (Sonar python:S5778).
        client = _client(retry_attempts=1)
        req = _ssh_req()
        with (
            patch("urllib.request.urlopen", side_effect=_boom),
            pytest.raises(ValueError, match="Failed to connect to Guacamole"),
        ):
            client.create_ssh_url(req)

    def test_passes_ssh_private_key_to_connection_params(self, fake_private_key, guac_exchange):
        with guac_exchange() as exchange:
            _client().create_ssh_url(_ssh_req(ssh_private_key=fake_private_key))

        params = exchange.posted_payload(SECRET_KEY_128)["connections"]["ngfw-123"]["parameters"]
        assert params["private-key"] == fake_private_key

    def test_uses_custom_ssh_username(self, guac_exchange):
        with guac_exchange() as exchange:
            _client().create_ssh_url(_ssh_req(ssh_username="custom-user"))

        params = exchange.posted_payload(SECRET_KEY_128)["connections"]["ngfw-123"]["parameters"]
        assert params["username"] == "custom-user"
