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
import time
from typing import Any
from urllib.parse import quote

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


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
) -> dict[str, str]:
    """Create RDP connection parameters for Guacamole.

    Args:
        hostname: Target host IP or hostname
        port: RDP port (default 3389)
        username: Optional RDP username
        password: Optional RDP password
        ignore_cert: Whether to ignore certificate errors
        security: Security mode ('any', 'nla', 'tls', 'rdp')

    Returns:
        Dictionary of RDP parameters for Guacamole
    """
    params: dict[str, str] = {
        "hostname": hostname,
        "port": str(port),
        "ignore-cert": "true" if ignore_cert else "false",
        "security": security,
        "resize-method": "display-update",
        "enable-font-smoothing": "true",
    }

    if username:
        params["username"] = username
    if password:
        params["password"] = password

    return params


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
) -> str:
    """Create a signed Guacamole URL for RDP access.

    Args:
        base_url: Base Guacamole URL (e.g., 'https://portal.example.com/guacamole')
        secret_key: 32-character hex string (128-bit key)
        username: User's email/username for Guacamole session
        connection_name: Identifier for this connection
        hostname: Target host IP for RDP
        port: RDP port (default 3389)
        expires_minutes: Minutes until URL expires
        rdp_username: Windows username for RDP login
        rdp_password: Windows password for RDP login

    Returns:
        Full Guacamole URL with signed 'data' parameter
    """
    # Create connection definition
    connections = {
        connection_name: {
            "protocol": "rdp",
            "parameters": create_rdp_connection_params(hostname, port, username=rdp_username, password=rdp_password),
        }
    }

    # Create and sign payload
    payload = create_guacamole_auth_payload(username, connections, expires_minutes)
    encrypted_data = sign_and_encrypt_payload(payload, secret_key)

    # Build URL - the data parameter triggers JSON auth
    # Remove trailing slash from base_url if present
    base_url = base_url.rstrip("/")

    # URL-encode the base64 data (+ and / characters need encoding)
    encoded_data = quote(encrypted_data, safe="")

    # Build client identifier: connection_name + NULL + "c" + NULL + "json"
    # This tells Guacamole to auto-connect to the specified connection from JSON auth
    # Note: Don't URL-encode - it's in the fragment (#), handled by browser JS directly
    client_id = base64.b64encode(f"{connection_name}\0c\0json".encode()).decode().rstrip("=")

    return f"{base_url}/#/client/{client_id}?data={encoded_data}"
