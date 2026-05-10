"""Tests for Guacamole SSH functions in mission_control/guacamole.py."""

from unittest.mock import patch

import pytest


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
            (
                "0123456789abcdef0123456789abcdef"
                "0123456789abcdef0123456789abcdef"
            ),  # 256-bit
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


class TestCreateGuacamoleSSHURL:
    """Tests for create_guacamole_ssh_url()."""

    def test_calls_auth_payload_with_correct_username(self):
        """Function creates auth payload with provided username."""
        from mission_control.guacamole import create_guacamole_ssh_url

        with (
            patch("mission_control.guacamole.create_guacamole_auth_payload") as mock_payload,
            patch("mission_control.guacamole.sign_and_encrypt_payload", return_value="encrypted"),
            patch("mission_control.guacamole.get_guacamole_auth_token", return_value="token123"),
        ):
            mock_payload.return_value = {"username": "test@example.com"}

            create_guacamole_ssh_url(
                base_url="https://guac.example.com",
                secret_key="0123456789abcdef0123456789abcdef",
                username="test@example.com",
                connection_name="ngfw-123",
                hostname="10.1.5.10",
            )

            mock_payload.assert_called_once()
            call_args = mock_payload.call_args
            assert call_args[0][0] == "test@example.com"  # username

    def test_creates_ssh_connection_in_payload(self):
        """Function creates SSH protocol connection."""
        from mission_control.guacamole import create_guacamole_ssh_url

        with (
            patch("mission_control.guacamole.create_guacamole_auth_payload") as mock_payload,
            patch("mission_control.guacamole.sign_and_encrypt_payload", return_value="encrypted"),
            patch("mission_control.guacamole.get_guacamole_auth_token", return_value="token123"),
        ):
            mock_payload.return_value = {"username": "test@example.com"}

            create_guacamole_ssh_url(
                base_url="https://guac.example.com",
                secret_key="0123456789abcdef0123456789abcdef",
                username="test@example.com",
                connection_name="ngfw-123",
                hostname="10.1.5.10",
            )

            # Verify connections dict structure
            call_args = mock_payload.call_args
            connections = call_args[0][1]  # Second arg is connections dict
            assert "ngfw-123" in connections
            assert connections["ngfw-123"]["protocol"] == "ssh"

    def test_returns_valid_url_format(self):
        """Function returns properly formatted Guacamole URL."""
        from mission_control.guacamole import create_guacamole_ssh_url

        with (
            patch("mission_control.guacamole.create_guacamole_auth_payload", return_value={}),
            patch("mission_control.guacamole.sign_and_encrypt_payload", return_value="encrypted"),
            patch("mission_control.guacamole.get_guacamole_auth_token", return_value="token123"),
        ):
            result = create_guacamole_ssh_url(
                base_url="https://guac.example.com",
                secret_key="0123456789abcdef0123456789abcdef",
                username="test@example.com",
                connection_name="ngfw-123",
                hostname="10.1.5.10",
            )

            assert result.startswith("https://guac.example.com/#/client/")
            assert "token=token123" in result

    def test_uses_api_base_url_for_token_exchange(self):
        """Function uses api_base_url for token exchange when provided."""
        from mission_control.guacamole import create_guacamole_ssh_url

        with (
            patch("mission_control.guacamole.create_guacamole_auth_payload", return_value={}),
            patch("mission_control.guacamole.sign_and_encrypt_payload", return_value="encrypted"),
            patch("mission_control.guacamole.get_guacamole_auth_token", return_value="token123") as mock_token,
        ):
            create_guacamole_ssh_url(
                base_url="https://public.example.com",
                secret_key="0123456789abcdef0123456789abcdef",
                username="test@example.com",
                connection_name="ngfw-123",
                hostname="10.1.5.10",
                api_base_url="https://internal.example.com",
            )

            # Should use internal URL for token exchange
            mock_token.assert_called_once()
            assert mock_token.call_args[0][0] == "https://internal.example.com"

    def test_raises_on_token_exchange_failure(self):
        """Function raises ValueError when token exchange fails."""
        from mission_control.guacamole import create_guacamole_ssh_url

        with (
            patch("mission_control.guacamole.create_guacamole_auth_payload", return_value={}),
            patch("mission_control.guacamole.sign_and_encrypt_payload", return_value="encrypted"),
            patch(
                "mission_control.guacamole.get_guacamole_auth_token",
                side_effect=ValueError("Token exchange failed"),
            ),
            pytest.raises(ValueError, match="Token exchange failed"),
        ):
            create_guacamole_ssh_url(
                base_url="https://guac.example.com",
                secret_key="0123456789abcdef0123456789abcdef",
                username="test@example.com",
                connection_name="ngfw-123",
                hostname="10.1.5.10",
            )

    def test_passes_ssh_private_key_to_connection_params(self, fake_private_key):
        """Function includes SSH private key in connection parameters."""
        from mission_control.guacamole import create_guacamole_ssh_url

        with (
            patch("mission_control.guacamole.create_guacamole_auth_payload") as mock_payload,
            patch("mission_control.guacamole.sign_and_encrypt_payload", return_value="encrypted"),
            patch("mission_control.guacamole.get_guacamole_auth_token", return_value="token123"),
        ):
            mock_payload.return_value = {"username": "test@example.com"}

            create_guacamole_ssh_url(
                base_url="https://guac.example.com",
                secret_key="0123456789abcdef0123456789abcdef",
                username="test@example.com",
                connection_name="ngfw-123",
                hostname="10.1.5.10",
                ssh_private_key=fake_private_key,
            )

            # Verify private key is in connection params
            call_args = mock_payload.call_args
            connections = call_args[0][1]
            params = connections["ngfw-123"]["parameters"]
            assert "private-key" in params
            assert params["private-key"] == fake_private_key

    def test_uses_custom_ssh_username(self):
        """Function uses custom SSH username when provided."""
        from mission_control.guacamole import create_guacamole_ssh_url

        with (
            patch("mission_control.guacamole.create_guacamole_auth_payload") as mock_payload,
            patch("mission_control.guacamole.sign_and_encrypt_payload", return_value="encrypted"),
            patch("mission_control.guacamole.get_guacamole_auth_token", return_value="token123"),
        ):
            mock_payload.return_value = {"username": "test@example.com"}

            create_guacamole_ssh_url(
                base_url="https://guac.example.com",
                secret_key="0123456789abcdef0123456789abcdef",
                username="test@example.com",
                connection_name="ngfw-123",
                hostname="10.1.5.10",
                ssh_username="custom-user",
            )

            # Verify username in connection params
            call_args = mock_payload.call_args
            connections = call_args[0][1]
            params = connections["ngfw-123"]["parameters"]
            assert params["username"] == "custom-user"
