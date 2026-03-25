"""CTF Programmable Flag Validators.

Provides a registry of named validator functions for programmable flag types,
and an HTTP validation helper for HTTP flag types.

Validators are Python callables with the signature:
    (submitted_flag: str, params: dict[str, Any]) -> bool
"""

from __future__ import annotations

import ipaddress
import logging
from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)

# Type alias for validator functions
ValidatorFunc = Callable[[str, dict[str, Any]], bool]

# Registry of named validators
_VALIDATORS: dict[str, ValidatorFunc] = {}

# Maximum timeout for HTTP validators (seconds)
MAX_HTTP_TIMEOUT = 30
DEFAULT_HTTP_TIMEOUT = 10

# Blocked hostnames for SSRF protection
_BLOCKED_HOSTNAMES = frozenset(
    {
        "localhost",
        "metadata.google.internal",
    }
)


def is_blocked_url(url: str) -> bool:
    """Check if a URL targets a blocked or private network address.

    Blocks requests to loopback, private (RFC 1918), link-local (169.254.x.x),
    and cloud metadata endpoints.

    Args:
        url: The URL to check.

    Returns:
        True if the URL should be blocked.
    """
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname or ""
    except ValueError:
        return True

    if not hostname:
        return True

    # Block known metadata/internal hostnames
    if hostname in _BLOCKED_HOSTNAMES:
        return True

    # Check if hostname is an IP literal
    try:
        addr = ipaddress.ip_address(hostname)
        if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved:
            return True
    except ValueError:
        # hostname is a DNS name — resolve and check for private IPs (SSRF)
        import socket

        try:
            results = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC)
            for _, _, _, _, sockaddr in results:
                resolved_ip = ipaddress.ip_address(sockaddr[0])
                if (
                    resolved_ip.is_private
                    or resolved_ip.is_loopback
                    or resolved_ip.is_link_local
                    or resolved_ip.is_reserved
                ):
                    return True
        except (socket.gaierror, OSError):
            # DNS resolution failed — allow, since the URL is validated
            # at config time (HTTPS required) and the request will fail
            # naturally at call time if the host is unreachable.
            pass

    return False


def register_validator(name: str, func: ValidatorFunc) -> None:
    """Register a named validator function.

    Args:
        name: Unique name for the validator.
        func: Callable with signature (submitted_flag, params) -> bool.
    """
    _VALIDATORS[name] = func


def get_validator(name: str) -> ValidatorFunc | None:
    """Get a registered validator by name.

    Args:
        name: The validator name.

    Returns:
        The validator function, or None if not found.
    """
    return _VALIDATORS.get(name)


def list_validators() -> list[str]:
    """List all registered validator names.

    Returns:
        Sorted list of registered validator names.
    """
    return sorted(_VALIDATORS.keys())


def validate_http(
    submitted_flag: str,
    config: dict[str, Any],
    challenge_id: Any,
) -> bool:
    """Validate a flag submission via an external HTTP endpoint.

    Makes a POST (or configured method) request to the endpoint with the
    submitted flag and challenge ID. Expects a JSON response with a
    ``valid`` boolean field.

    Args:
        submitted_flag: The flag value submitted by the participant.
        config: Validator configuration dict with keys:
            - url (str, required): Endpoint URL.
            - headers (dict, optional): Additional request headers.
            - timeout (int, optional): Request timeout in seconds (default 10, max 30).
            - method (str, optional): HTTP method, default "POST".
        challenge_id: The challenge UUID (passed to the endpoint for context).

    Returns:
        True if the endpoint responds with ``{"valid": true}``, False otherwise.
    """
    url = config.get("url")
    if not url:
        logger.error("HTTP validator missing 'url' in config")
        return False

    # Enforce HTTPS at runtime (not just at config validation time) to
    # prevent requests to cloud metadata endpoints via DNS rebinding.
    if not url.startswith("https://"):
        logger.error("HTTP validator URL must use HTTPS for challenge %s", challenge_id)
        return False

    if is_blocked_url(url):
        logger.error("HTTP validator URL blocked (private/reserved address) for challenge %s", challenge_id)
        return False

    timeout = min(config.get("timeout", DEFAULT_HTTP_TIMEOUT), MAX_HTTP_TIMEOUT)
    if timeout < 1:
        timeout = DEFAULT_HTTP_TIMEOUT

    headers = config.get("headers", {})
    method = config.get("method", "POST").upper()

    payload = {
        "flag": submitted_flag,
        "challenge_id": str(challenge_id),
    }

    try:
        # Disable redirects to prevent SSRF via 302 to internal endpoints.
        if method == "GET":
            resp = requests.get(url, params=payload, headers=headers, timeout=timeout, allow_redirects=False)
        else:
            resp = requests.post(url, json=payload, headers=headers, timeout=timeout, allow_redirects=False)

        if resp.status_code != 200:
            logger.warning(
                "HTTP validator returned status %d for challenge %s",
                resp.status_code,
                challenge_id,
            )
            return False

        data = resp.json()
        return bool(data.get("valid", False))

    except requests.Timeout:
        logger.warning(
            "HTTP validator timed out after %ds for challenge %s",
            timeout,
            challenge_id,
        )
        return False
    except requests.ConnectionError:
        logger.warning(
            "HTTP validator connection error for challenge %s: %s",
            challenge_id,
            url,
        )
        return False
    except (requests.RequestException, ValueError) as e:
        logger.error(
            "HTTP validator error for challenge %s: %s",
            challenge_id,
            e,
        )
        return False


# ---------------------------------------------------------------------------
# Built-in validators
# ---------------------------------------------------------------------------


def _always_true(submitted_flag: str, params: dict[str, Any]) -> bool:
    """Always returns True. Useful for testing."""
    return True


def _contains_substring(submitted_flag: str, params: dict[str, Any]) -> bool:
    """Check if the submitted flag contains a configured substring.

    Params:
        substring (str): The substring to search for.
        case_sensitive (bool): Whether comparison is case-sensitive (default True).
    """
    substring = params.get("substring", "")
    if not substring:
        return False
    case_sensitive = params.get("case_sensitive", True)
    if case_sensitive:
        return substring in submitted_flag
    return substring.lower() in submitted_flag.lower()


# Register built-in validators
register_validator("always_true", _always_true)
register_validator("contains_substring", _contains_substring)
