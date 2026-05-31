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
from dataclasses import dataclass
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
        secret_key: Hex string key (64 characters / 256-bit preferred)

    Returns:
        Base64-encoded encrypted payload for use as 'data' parameter
    """
    # Convert secret key from hex string to bytes
    key_bytes = bytes.fromhex(secret_key)
    if len(key_bytes) not in {16, 24, 32}:
        raise ValueError("Secret key must be 32, 48, or 64 hex characters (128, 192, or 256 bits)")

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


@dataclass(frozen=True)
class RDPConnectionParams:
    """Inputs for ``create_rdp_connection_params``.

    Bundling avoids the function's long positional/keyword signature
    (Sonar python:S107) while preserving every field's semantics.
    """

    hostname: str
    port: int = 3389
    username: str | None = None
    password: str | None = None
    ignore_cert: bool = True
    security: str = "any"
    sftp_root_directory: str | None = None
    sftp_private_key: str | None = None


def create_rdp_connection_params(req: RDPConnectionParams) -> dict[str, str]:
    """Create RDP connection parameters for Guacamole.

    Args:
        req: Bundled RDP connection inputs (see ``RDPConnectionParams``).

    Returns:
        Dictionary of RDP parameters for Guacamole
    """
    hostname = req.hostname
    port = req.port
    username = req.username
    password = req.password
    sftp_root_directory = req.sftp_root_directory
    sftp_private_key = req.sftp_private_key

    params: dict[str, str] = {
        "hostname": hostname,
        "port": str(port),
        "ignore-cert": "true" if req.ignore_cert else "false",
        "security": req.security,
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


# HTTP status codes treated as transient for the Guacamole token exchange.
# 408 (Request Timeout) and 429 (Too Many Requests) are conventional retry candidates;
# 502/503/504 cover gateway/proxy not-ready while guacamole-client warms a new session.
_RETRYABLE_HTTP_STATUSES = frozenset({408, 429, 502, 503, 504})


def _attempt_token_exchange(req: urllib.request.Request) -> str:
    """Single POST against Guacamole's /api/tokens; returns the auth token.

    Raises ``urllib.error.HTTPError`` / ``URLError`` on transport failure and
    ``KeyError`` / ``json.JSONDecodeError`` on malformed responses. The
    surrounding retry loop classifies which of those are retryable.
    """
    # NOSONAR — req.full_url is built from settings.GUACAMOLE_API_BASE_URL,
    # a server-controlled https endpoint, not user input. ruff S310 / bandit
    # B310 both want the scheme to be explicitly verified; the URL is fixed
    # by deployment configuration so the check would be cosmetic.
    with urllib.request.urlopen(req, timeout=10) as response:  # noqa: S310  # nosec B310
        return json.loads(response.read().decode("utf-8"))["authToken"]


def _retry_or_raise_token_exchange(
    exc: Exception,
    attempt: int,
    attempts: int,
    base_delay_ms: int,
) -> None:
    """Decide whether the failed attempt is retryable and either sleep, or raise.

    On a retryable error with attempts left, logs a warning and sleeps for the
    backoff delay. Otherwise logs the final error and raises ``ValueError``.
    """
    attempts_left = attempt + 1 < attempts
    delay_ms = base_delay_ms * (2**attempt)
    if isinstance(exc, urllib.error.HTTPError):
        if exc.code in _RETRYABLE_HTTP_STATUSES and attempts_left:
            logger.warning(
                "Guacamole token request returned %s on attempt %d/%d; retrying in %dms",
                exc.code,
                attempt + 1,
                attempts,
                delay_ms,
            )
            time.sleep(delay_ms / 1000.0)
            return
        logger.exception("Guacamole token request failed: %s %s", exc.code, exc.reason)
        raise ValueError(f"Failed to get Guacamole auth token: {exc.reason}") from exc
    if isinstance(exc, urllib.error.URLError):
        if attempts_left:
            logger.warning(
                "Guacamole token request failed to connect on attempt %d/%d; retrying in %dms",
                attempt + 1,
                attempts,
                delay_ms,
            )
            time.sleep(delay_ms / 1000.0)
            return
        logger.exception("Guacamole token request failed: %s", exc.reason)
        raise ValueError(f"Failed to connect to Guacamole: {exc.reason}") from exc
    # KeyError or json.JSONDecodeError — always fatal, no retry.
    logger.exception("Invalid Guacamole token response: %s", exc)
    raise ValueError("Invalid response from Guacamole") from exc


def get_guacamole_auth_token(
    base_url: str,
    encrypted_data: str,
    *,
    attempts: int | None = None,
    base_delay_ms: int | None = None,
) -> str:
    """Get an auth token from Guacamole API, with bounded readiness retry.

    The Guacamole `/api/tokens` exchange can race with internal session
    propagation immediately after a JSON-auth session is minted; the symptom
    is a 5xx (or refused connection) on the first attempt followed by success
    on the next. This function wraps the POST in a bounded exponential
    backoff so the user's first click does not get redirected to the
    Guacamole login page (issue #395). Non-retryable errors (4xx other than
    408/429, malformed responses) surface immediately.

    Args:
        base_url: Base Guacamole URL (e.g., 'https://portal.example.com/guacamole')
        encrypted_data: Base64-encoded encrypted JSON payload
        attempts: Total attempts (1 initial + N-1 retries). Falls back to
            settings.GUACAMOLE_TOKEN_RETRY_ATTEMPTS.
        base_delay_ms: Initial backoff in milliseconds, doubled per attempt.
            Falls back to settings.GUACAMOLE_TOKEN_RETRY_BASE_DELAY_MS.

    Returns:
        Auth token string

    Raises:
        ValueError: If the token request fails (after exhausting retries for
            transient failures, or immediately for non-retryable failures).
    """
    from django.conf import settings

    if attempts is None:
        attempts = getattr(settings, "GUACAMOLE_TOKEN_RETRY_ATTEMPTS", 3)
    if base_delay_ms is None:
        base_delay_ms = getattr(settings, "GUACAMOLE_TOKEN_RETRY_BASE_DELAY_MS", 200)
    attempts = max(1, int(attempts))
    base_delay_ms = max(0, int(base_delay_ms))

    base_url = base_url.rstrip("/")
    token_url = f"{base_url}/api/tokens"

    req_data = urlencode({"data": encrypted_data}).encode("utf-8")
    # NOSONAR — token_url is built from settings.GUACAMOLE_API_BASE_URL, a
    # server-controlled https endpoint; same trust boundary as the urlopen
    # call inside _attempt_token_exchange.
    req = urllib.request.Request(token_url, data=req_data)  # noqa: S310
    req.add_header("Content-Type", "application/x-www-form-urlencoded")

    for attempt in range(attempts):
        try:
            return _attempt_token_exchange(req)
        except (
            urllib.error.HTTPError,
            urllib.error.URLError,
            KeyError,
            json.JSONDecodeError,
        ) as e:
            _retry_or_raise_token_exchange(e, attempt, attempts, base_delay_ms)

    # Unreachable: every branch above either returns or raises.
    raise ValueError("Failed to get Guacamole auth token: exhausted attempts")


@dataclass(frozen=True)
class GuacRDPUrlRequest:
    """Inputs for ``create_guacamole_rdp_url``.

    Bundling collapses the function's long parameter list (Sonar
    python:S107) into a single object without changing semantics.
    """

    base_url: str
    secret_key: str
    username: str
    connection_name: str
    hostname: str
    port: int = 3389
    expires_minutes: int = 5
    rdp_username: str | None = None
    rdp_password: str | None = None
    api_base_url: str | None = None
    sftp_root_directory: str | None = None
    sftp_private_key: str | None = None


def create_guacamole_rdp_url(req: GuacRDPUrlRequest) -> str:
    """Create a signed Guacamole URL for RDP access.

    This function:
    1. Creates an encrypted JSON payload with connection details
    2. POSTs to Guacamole's /api/tokens to get an auth token
    3. Returns a URL that auto-connects to the RDP session

    Args:
        req: Bundled RDP URL inputs (see ``GuacRDPUrlRequest``).

    Returns:
        Full Guacamole URL with auth token that auto-connects to RDP

    Raises:
        ValueError: If secret key is invalid or token request fails
    """
    # Create connection definition
    connections = {
        req.connection_name: {
            "protocol": "rdp",
            "parameters": create_rdp_connection_params(
                RDPConnectionParams(
                    hostname=req.hostname,
                    port=req.port,
                    username=req.rdp_username,
                    password=req.rdp_password,
                    sftp_root_directory=req.sftp_root_directory,
                    sftp_private_key=req.sftp_private_key,
                )
            ),
        }
    }

    # Create and sign payload
    payload = create_guacamole_auth_payload(req.username, connections, req.expires_minutes)
    encrypted_data = sign_and_encrypt_payload(payload, req.secret_key)

    # Get auth token from Guacamole API (use internal URL if provided)
    api_url = (req.api_base_url or req.base_url).rstrip("/")
    auth_token = get_guacamole_auth_token(api_url, encrypted_data)

    # Build client identifier: connection_name + NULL + "c" + NULL + "json"
    # This tells Guacamole to auto-connect to the specified connection from JSON auth
    client_id = base64.b64encode(f"{req.connection_name}\0c\0json".encode()).decode().rstrip("=")

    # Return public URL for browser
    public_url = req.base_url.rstrip("/")
    return f"{public_url}/#/client/{client_id}?token={auth_token}"


def create_ssh_connection_params(
    username: str,
    hostname: str,
    port: int = 22,
    ssh_private_key: str | None = None,
) -> dict[str, str]:
    """Create SSH connection parameters for Guacamole.

    Args:
        username: SSH username for login
        hostname: Target host IP or hostname
        port: SSH port (default 22)
        ssh_private_key: PEM-encoded private key for authentication

    Returns:
        Dictionary of SSH parameters for Guacamole
    """
    params: dict[str, str] = {
        "hostname": hostname,
        "port": str(port),
        "username": username,
        # Terminal settings
        "color-scheme": "green-black",
        "font-name": "monospace",
        "font-size": "12",
        # Clipboard support
        "enable-clipboard": "true",
    }

    if ssh_private_key:
        params["private-key"] = ssh_private_key

    return params


@dataclass(frozen=True)
class GuacSSHUrlRequest:
    """Inputs for ``create_guacamole_ssh_url``.

    Bundling collapses the function's long parameter list (Sonar
    python:S107) into a single object without changing semantics.
    """

    base_url: str
    secret_key: str
    username: str
    connection_name: str
    hostname: str
    port: int = 22
    ssh_username: str = "admin"
    ssh_private_key: str | None = None
    expires_minutes: int = 5
    api_base_url: str | None = None


def create_guacamole_ssh_url(req: GuacSSHUrlRequest) -> str:
    """Create a signed Guacamole URL for SSH access.

    This function:
    1. Creates an encrypted JSON payload with connection details
    2. POSTs to Guacamole's /api/tokens to get an auth token
    3. Returns a URL that auto-connects to the SSH session

    Args:
        req: Bundled SSH URL inputs (see ``GuacSSHUrlRequest``).

    Returns:
        Full Guacamole URL with auth token that auto-connects to SSH

    Raises:
        ValueError: If secret key is invalid or token request fails
    """
    # Create connection definition
    connections = {
        req.connection_name: {
            "protocol": "ssh",
            "parameters": create_ssh_connection_params(
                username=req.ssh_username,
                hostname=req.hostname,
                port=req.port,
                ssh_private_key=req.ssh_private_key,
            ),
        }
    }

    # Create and sign payload
    payload = create_guacamole_auth_payload(req.username, connections, req.expires_minutes)
    encrypted_data = sign_and_encrypt_payload(payload, req.secret_key)

    # Get auth token from Guacamole API (use internal URL if provided)
    api_url = (req.api_base_url or req.base_url).rstrip("/")
    auth_token = get_guacamole_auth_token(api_url, encrypted_data)

    # Build client identifier: connection_name + NULL + "c" + NULL + "json"
    # This tells Guacamole to auto-connect to the specified connection from JSON auth
    client_id = base64.b64encode(f"{req.connection_name}\0c\0json".encode()).decode().rstrip("=")

    # Return public URL for browser
    public_url = req.base_url.rstrip("/")
    return f"{public_url}/#/client/{client_id}?token={auth_token}"
