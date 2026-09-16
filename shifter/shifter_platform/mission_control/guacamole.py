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
from typing import Any, Protocol
from urllib.parse import urlencode, urlparse

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from mission_control._guacamole_connection_params import (
    RDPConnectionParams,
    create_rdp_connection_params,
    create_ssh_connection_params,
)

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


# HTTP status codes treated as transient for the Guacamole token exchange.
# 408 (Request Timeout) and 429 (Too Many Requests) are conventional retry candidates;
# 502/503/504 cover gateway/proxy not-ready while guacamole-client warms a new session.
_RETRYABLE_HTTP_STATUSES = frozenset({408, 429, 502, 503, 504})


_ALLOWED_GUACAMOLE_SCHEMES = frozenset({"http", "https"})


def _attempt_token_exchange(req: urllib.request.Request, timeout: float) -> str:
    """Single POST against Guacamole's /api/tokens; returns the auth token.

    The request URL's scheme is validated by the caller; the suppressions
    below are for static-checker awareness (ruff S310 / bandit B310) which
    can't see the upstream guard.
    """
    with urllib.request.urlopen(req, timeout=timeout) as response:  # noqa: S310 # nosec B310
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


@dataclass(frozen=True)
class GuacamoleClientConfig:
    """Immutable Guacamole client configuration bound once at the service edge.

    Carries every deployment-controlled value the client needs so its methods
    never read ``django.conf.settings`` mid-stack (issue #993). ``base_url`` is
    the public browser URL/path returned to the client; ``api_base_url`` is the
    internal server-to-server token endpoint (falls back to ``base_url`` when
    unset). Retry policy and the finite HTTP timeout are bound here too.
    """

    base_url: str
    secret_key: str
    api_base_url: str | None = None
    retry_attempts: int = 3
    retry_base_delay_ms: int = 200
    timeout_seconds: float = 10.0


@dataclass(frozen=True)
class GuacRDPUrlRequest:
    """Per-session inputs for :meth:`GuacamoleClient.create_rdp_url`.

    Bundling collapses the long parameter list (Sonar python:S107) into a
    single object. Deployment configuration (URLs, signing secret) lives in
    :class:`GuacamoleClientConfig`, not here.
    """

    username: str
    connection_name: str
    hostname: str
    port: int = 3389
    expires_minutes: int = 5
    rdp_username: str | None = None
    rdp_password: str | None = None
    sftp_root_directory: str | None = None
    sftp_private_key: str | None = None
    sftp_enabled: bool = True
    security: str = "any"


@dataclass(frozen=True)
class GuacSSHUrlRequest:
    """Per-session inputs for :meth:`GuacamoleClient.create_ssh_url`.

    Bundling collapses the long parameter list (Sonar python:S107) into a
    single object. Deployment configuration (URLs, signing secret) lives in
    :class:`GuacamoleClientConfig`, not here.
    """

    username: str
    connection_name: str
    hostname: str
    port: int = 22
    ssh_username: str = "admin"
    ssh_private_key: str | None = None
    expires_minutes: int = 5


class GuacamoleClient(Protocol):
    """Port for minting signed Guacamole auto-connect URLs.

    Two real operations, mirroring the persisted access kinds. A fake with the
    same shape substitutes at the orchestration layer in tests without touching
    ``urllib`` or global settings; the concrete adapter still owns the JSON-auth
    crypto and token-exchange wire protocol.
    """

    def create_rdp_url(self, req: GuacRDPUrlRequest) -> str:
        """Return a signed Guacamole URL that auto-connects to RDP."""
        ...

    def create_ssh_url(self, req: GuacSSHUrlRequest) -> str:
        """Return a signed Guacamole URL that auto-connects to SSH."""
        ...


class JsonAuthGuacamoleClient:
    """Concrete :class:`GuacamoleClient` over the Guacamole JSON-auth HTTP API.

    Owns the HMAC-SHA256/AES-128-CBC payload signing, the bounded first-click
    readiness retry (issue #395), and the HTTP(S)-scheme validation. Constructed
    from an immutable :class:`GuacamoleClientConfig`; it never reads Django
    settings.
    """

    def __init__(self, config: GuacamoleClientConfig) -> None:
        self._config = config

    def create_rdp_url(self, req: GuacRDPUrlRequest) -> str:
        """Create a signed Guacamole URL for RDP access.

        Raises:
            ValueError: If the signing key is invalid or the token request fails.
        """
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
                        sftp_enabled=req.sftp_enabled,
                        security=req.security,
                    )
                ),
            }
        }
        return self._mint_url(
            username=req.username,
            connection_name=req.connection_name,
            connections=connections,
            expires_minutes=req.expires_minutes,
        )

    def create_ssh_url(self, req: GuacSSHUrlRequest) -> str:
        """Create a signed Guacamole URL for SSH access.

        Raises:
            ValueError: If the signing key is invalid or the token request fails.
        """
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
        return self._mint_url(
            username=req.username,
            connection_name=req.connection_name,
            connections=connections,
            expires_minutes=req.expires_minutes,
        )

    def _mint_url(
        self,
        *,
        username: str,
        connection_name: str,
        connections: dict[str, dict[str, Any]],
        expires_minutes: int,
    ) -> str:
        """Sign the payload, exchange it for a token, and build the browser URL."""
        payload = create_guacamole_auth_payload(username, connections, expires_minutes)
        encrypted_data = sign_and_encrypt_payload(payload, self._config.secret_key)
        auth_token = self._get_auth_token(encrypted_data)

        # Build client identifier: connection_name + NULL + "c" + NULL + "json"
        # This tells Guacamole to auto-connect to the connection from JSON auth.
        client_id = base64.b64encode(f"{connection_name}\0c\0json".encode()).decode().rstrip("=")

        # Return public URL for browser (never the internal API URL).
        public_url = self._config.base_url.rstrip("/")
        return f"{public_url}/#/client/{client_id}?token={auth_token}"

    def _get_auth_token(self, encrypted_data: str) -> str:
        """Exchange the encrypted payload for an auth token, with bounded retry.

        The Guacamole ``/api/tokens`` exchange can race with internal session
        propagation immediately after a JSON-auth session is minted; the symptom
        is a 5xx (or refused connection) on the first attempt followed by success
        on the next. The POST is wrapped in bounded exponential backoff so the
        user's first click is not redirected to the login page (issue #395).
        Non-retryable errors (4xx other than 408/429, malformed responses)
        surface immediately.
        """
        attempts = max(1, int(self._config.retry_attempts))
        base_delay_ms = max(0, int(self._config.retry_base_delay_ms))

        api_base = (self._config.api_base_url or self._config.base_url).rstrip("/")
        token_url = f"{api_base}/api/tokens"

        # Validate the scheme explicitly so the urlopen() audit checks
        # (ruff S310 / bandit B310 / Sonar S6713) are satisfied without a lint
        # suppression. The URL is deployment-controlled; the explicit check
        # turns a config mistake into a clear ValueError instead of an opaque
        # urlopen failure.
        parsed_scheme = urlparse(token_url).scheme
        if parsed_scheme not in _ALLOWED_GUACAMOLE_SCHEMES:
            raise ValueError(f"Refusing to call Guacamole API with non-http(s) scheme: {parsed_scheme!r}")

        req_data = urlencode({"data": encrypted_data}).encode("utf-8")
        req = urllib.request.Request(token_url, data=req_data)  # noqa: S310
        req.add_header("Content-Type", "application/x-www-form-urlencoded")

        for attempt in range(attempts):
            try:
                return _attempt_token_exchange(req, self._config.timeout_seconds)
            except (
                urllib.error.HTTPError,
                urllib.error.URLError,
                KeyError,
                json.JSONDecodeError,
            ) as e:
                _retry_or_raise_token_exchange(e, attempt, attempts, base_delay_ms)

        # Unreachable: every branch above either returns or raises.
        raise ValueError("Failed to get Guacamole auth token: exhausted attempts")


def get_guacamole_client(config: GuacamoleClientConfig) -> GuacamoleClient:
    """Return a Guacamole client for ``config``.

    Mirrors the ``shared.cloud`` ``get_*`` factory *shape* only: Guacamole is a
    single provider-agnostic presentation gateway, not a cloud capability, so
    there is no provider branch, backend-capability registry, or per-provider
    adapter.
    """
    return JsonAuthGuacamoleClient(config)
