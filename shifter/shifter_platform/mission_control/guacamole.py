"""Guacamole JSON authentication utilities.

This module provides functions to create signed Guacamole URLs for
on-the-fly RDP/VNC/SSH connections. It implements the JSON auth extension
protocol which uses HMAC-SHA256 signing and AES-128-CBC encryption.

See: https://guacamole.apache.org/doc/gug/json-auth.html
"""

import base64
import hashlib
import hmac
import json
import logging
import time
import urllib.request
from typing import Any
from urllib.parse import urlencode

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

logger = logging.getLogger(__name__)


def create_guacamole_auth_payload(
    username: str,
    connections: dict[str, dict[str, Any]],
    expires_minutes: int = 5,
) -> dict[str, Any]:
    """Create the JSON payload for Guacamole JSON auth.

    Args:
        username: Username for the Guacamole session (typically user's email)
        connections: Dictionary of connection definitions
        expires_minutes: Minutes until the payload expires

    Returns:
        Dictionary payload ready for signing

    Example connection:
        {
            "rdp-connection": {
                "protocol": "rdp",
                "parameters": {
                    "hostname": "10.1.5.10",
                    "port": "3389",
                    "ignore-cert": "true",
                    "security": "any"
                }
            }
        }
    """
    expires_ms = int((time.time() + expires_minutes * 60) * 1000)

    return {
        "username": username,
        "expires": expires_ms,
        "connections": connections,
    }


def sign_and_encrypt_payload(payload: dict[str, Any], secret_key: str) -> str:
    """Sign and encrypt a Guacamole JSON auth payload.

    The process follows Guacamole's JSON auth specification:
    1. Convert payload to JSON bytes
    2. Create HMAC-SHA256 signature using secret key
    3. Prepend binary signature to JSON bytes
    4. Encrypt with AES-128-CBC using zero IV
    5. Base64 encode the result

    Args:
        payload: The JSON auth payload dictionary
        secret_key: 32-character hex string (128-bit key)

    Returns:
        Base64-encoded encrypted payload for use as 'data' parameter
    """
    # Convert secret key from hex string to bytes
    key_bytes = bytes.fromhex(secret_key)
    if len(key_bytes) != 16:
        raise ValueError("Secret key must be 32 hex characters (128 bits)")

    # Convert payload to JSON bytes
    json_bytes = json.dumps(payload, separators=(",", ":")).encode("utf-8")

    # Create HMAC-SHA256 signature
    signature = hmac.new(key_bytes, json_bytes, hashlib.sha256).digest()

    # Prepend signature to JSON
    signed_data = signature + json_bytes

    # Pad to AES block size (16 bytes)
    block_size = 16
    padding_length = block_size - (len(signed_data) % block_size)
    padded_data = signed_data + bytes([padding_length]) * padding_length

    # Encrypt with AES-128-CBC using zero IV
    iv = b"\x00" * 16
    cipher = Cipher(algorithms.AES(key_bytes), modes.CBC(iv))
    encryptor = cipher.encryptor()
    encrypted_data = encryptor.update(padded_data) + encryptor.finalize()

    # Base64 encode
    return base64.b64encode(encrypted_data).decode("utf-8")


def create_rdp_connection_params(
    hostname: str,
    port: int = 3389,
    username: str | None = None,
    password: str | None = None,
    ignore_cert: bool = True,
    security: str = "any",
    sftp_root_directory: str | None = None,
    sftp_private_key: str | None = None,
) -> dict[str, str]:
    """Create RDP connection parameters for Guacamole.

    Args:
        hostname: Target host IP or hostname
        port: RDP port (default 3389)
        username: Optional RDP username
        password: Optional RDP password
        ignore_cert: Whether to ignore certificate errors
        security: Security mode ('any', 'nla', 'tls', 'rdp')
        sftp_root_directory: Root directory for SFTP file transfers
        sftp_private_key: PEM-encoded private key for SFTP (used instead of password)

    Returns:
        Dictionary of RDP parameters for Guacamole
    """
    params: dict[str, str] = {
        "hostname": hostname,
        "port": str(port),
        "ignore-cert": "true" if ignore_cert else "false",
        "security": security,
        "resize-method": "display-update",
        # Clipboard support
        "disable-copy": "false",
        "disable-paste": "false",
        # Performance optimizations - reduce bandwidth and server-side rendering load
        "color-depth": "16",
        "disable-audio": "true",
        "enable-wallpaper": "false",
        "enable-theming": "false",
        "enable-font-smoothing": "false",
        "enable-full-window-drag": "false",
        "enable-desktop-composition": "false",
        "enable-menu-animations": "false",
    }

    # SFTP file transfer - works reliably for both Windows and Linux (xrdp)
    # Uses SSH connection for file transfers via Guacamole menu (Ctrl+Alt+Shift)
    if username and (password or sftp_private_key):
        params["enable-sftp"] = "true"
        params["sftp-hostname"] = hostname
        params["sftp-port"] = "22"
        params["sftp-username"] = username
        # Prefer key-based auth (required for Windows OpenSSH)
        if sftp_private_key:
            params["sftp-private-key"] = sftp_private_key
        elif password:
            params["sftp-password"] = password
        if sftp_root_directory:
            params["sftp-root-directory"] = sftp_root_directory
            # sftp-directory is the upload destination for drag-and-drop transfers
            params["sftp-directory"] = sftp_root_directory

    if username:
        params["username"] = username
    if password:
        params["password"] = password

    return params


def get_guacamole_auth_token(base_url: str, encrypted_data: str) -> str:
    """Get an auth token from Guacamole API.

    Args:
        base_url: Base Guacamole URL (e.g., 'https://portal.example.com/guacamole')
        encrypted_data: Base64-encoded encrypted JSON payload

    Returns:
        Auth token string

    Raises:
        ValueError: If token request fails
    """
    base_url = base_url.rstrip("/")
    token_url = f"{base_url}/api/tokens"

    # POST the encrypted data to get a token
    req_data = urlencode({"data": encrypted_data}).encode("utf-8")
    req = urllib.request.Request(token_url, data=req_data)  # noqa: S310
    req.add_header("Content-Type", "application/x-www-form-urlencoded")

    try:
        with urllib.request.urlopen(req, timeout=10) as response:  # noqa: S310 # nosec B310
            result = json.loads(response.read().decode("utf-8"))
            return result["authToken"]
    except urllib.error.HTTPError as e:
        logger.error(f"Guacamole token request failed: {e.code} {e.reason}")
        raise ValueError(f"Failed to get Guacamole auth token: {e.reason}") from e
    except urllib.error.URLError as e:
        logger.error(f"Guacamole token request failed: {e.reason}")
        raise ValueError(f"Failed to connect to Guacamole: {e.reason}") from e
    except (KeyError, json.JSONDecodeError) as e:
        logger.error(f"Invalid Guacamole token response: {e}")
        raise ValueError("Invalid response from Guacamole") from e


def create_guacamole_rdp_url(
    base_url: str,
    secret_key: str,
    username: str,
    connection_name: str,
    hostname: str,
    port: int = 3389,
    expires_minutes: int = 5,
    rdp_username: str | None = None,
    rdp_password: str | None = None,
    api_base_url: str | None = None,
    sftp_root_directory: str | None = None,
    sftp_private_key: str | None = None,
) -> str:
    """Create a signed Guacamole URL for RDP access.

    This function:
    1. Creates an encrypted JSON payload with connection details
    2. POSTs to Guacamole's /api/tokens to get an auth token
    3. Returns a URL that auto-connects to the RDP session

    Args:
        base_url: Public Guacamole URL for browser (e.g., 'https://portal.example.com/guacamole')
        secret_key: 32-character hex string (128-bit key)
        username: User's email/username for Guacamole session
        connection_name: Identifier for this connection
        hostname: Target host IP for RDP
        port: RDP port (default 3389)
        expires_minutes: Minutes until URL expires
        rdp_username: Username for RDP login
        rdp_password: Password for RDP login
        api_base_url: Internal URL for server-to-server API calls (defaults to base_url)
        sftp_root_directory: Root directory for SFTP file transfers
        sftp_private_key: PEM-encoded private key for SFTP (used instead of password)

    Returns:
        Full Guacamole URL with auth token that auto-connects to RDP

    Raises:
        ValueError: If secret key is invalid or token request fails
    """
    # Create connection definition
    connections = {
        connection_name: {
            "protocol": "rdp",
            "parameters": create_rdp_connection_params(
                hostname,
                port,
                username=rdp_username,
                password=rdp_password,
                sftp_root_directory=sftp_root_directory,
                sftp_private_key=sftp_private_key,
            ),
        }
    }

    # Create and sign payload
    payload = create_guacamole_auth_payload(username, connections, expires_minutes)
    encrypted_data = sign_and_encrypt_payload(payload, secret_key)

    # Get auth token from Guacamole API (use internal URL if provided)
    api_url = (api_base_url or base_url).rstrip("/")
    auth_token = get_guacamole_auth_token(api_url, encrypted_data)

    # Build client identifier: connection_name + NULL + "c" + NULL + "json"
    # This tells Guacamole to auto-connect to the specified connection from JSON auth
    client_id = base64.b64encode(f"{connection_name}\0c\0json".encode()).decode().rstrip("=")

    # Return public URL for browser
    base_url = base_url.rstrip("/")
    return f"{base_url}/#/client/{client_id}?token={auth_token}"
