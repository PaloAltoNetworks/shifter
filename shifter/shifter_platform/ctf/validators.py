"""CTF Programmable Flag Validators.

Provides a registry of named validator functions for programmable flag types,
and an HTTP validation helper for HTTP flag types.

Validators are Python callables with the signature:
    (submitted_flag: str, params: dict[str, Any]) -> bool
"""

from __future__ import annotations

import contextlib
import http.client
import ipaddress
import json
import logging
import socket
import ssl
from collections.abc import Callable
from typing import Any
from urllib.parse import urlencode, urlparse

from shared.log_sanitize import safe_log

logger = logging.getLogger(__name__)

# Type alias for validator functions
ValidatorFunc = Callable[[str, dict[str, Any]], bool]

# Registry of named validators
_VALIDATORS: dict[str, ValidatorFunc] = {}

# Maximum timeout for HTTP validators (seconds)
MAX_HTTP_TIMEOUT = 30
DEFAULT_HTTP_TIMEOUT = 10

# Maximum response body to read from a validator endpoint (bytes).
# Caps memory/CPU exposure to an arbitrary attacker-controlled response.
_MAX_RESPONSE_BYTES = 1 * 1024 * 1024

# Blocked hostnames for SSRF protection
_BLOCKED_HOSTNAMES = frozenset(
    {
        "localhost",
        "metadata.google.internal",
    }
)


class _BlockedDestinationError(Exception):
    """Raised when DNS resolution returns a blocked address.

    Used by the HTTP validator path so the caller can distinguish
    "every answer in the DNS reply violates SSRF policy" from a
    "resolution failed" outcome and fail closed in either case.
    """


def _is_blocked_address(addr: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Return True if *addr* is in a range we never allow as a network target."""
    return bool(
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_reserved
        or addr.is_multicast
        or addr.is_unspecified
    )


def _resolve_and_validate(hostname: str, port: int) -> list[str]:
    """Resolve *hostname* and apply SSRF policy to every address returned.

    Returns the list of resolved address strings (all of which passed
    policy). Raises ``_BlockedDestinationError`` if any address in the
    DNS reply is blocked, or if the reply is empty. ``socket.gaierror``
    propagates unchanged for callers that want to distinguish lookup
    failure.

    The address list returned here is the input to
    ``_PinnedHTTPSConnection``: the actual socket must be opened to one
    of these addresses, never re-resolved, so a hostname that flips to
    a blocked address between this call and the connect step cannot
    reach the wire.
    """
    infos = socket.getaddrinfo(hostname, port, socket.AF_UNSPEC, socket.SOCK_STREAM)
    addresses: list[str] = []
    for _family, _type, _proto, _canon, sockaddr in infos:
        addr_str = str(sockaddr[0])
        try:
            addr_obj = ipaddress.ip_address(addr_str)
        except ValueError as exc:
            raise _BlockedDestinationError(f"non-IP address in DNS response: {addr_str!r}") from exc
        if _is_blocked_address(addr_obj):
            raise _BlockedDestinationError(f"blocked address from DNS for {hostname!r}")
        addresses.append(addr_str)
    if not addresses:
        raise _BlockedDestinationError(f"DNS returned no addresses for {hostname!r}")
    return addresses


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """HTTPS connection pinned to a pre-validated IP.

    The TCP socket is opened to ``pinned_ip``; TLS uses the original
    ``hostname`` for SNI and certificate verification; ``Host:`` keeps
    the original hostname (set by the stdlib from ``self.host``).
    Coupling DNS policy to the actual connection target closes the
    rebinding window between policy check and connect.
    """

    def __init__(
        self,
        hostname: str,
        pinned_ip: str,
        port: int,
        *,
        timeout: float,
        context: ssl.SSLContext,
    ) -> None:
        super().__init__(host=hostname, port=port, timeout=timeout, context=context)
        self._pinned_ip = pinned_ip

    def connect(self) -> None:  # pragma: no cover - exercised in dedicated unit test
        sock = socket.create_connection(
            (self._pinned_ip, self.port),
            timeout=self.timeout,
        )
        try:
            if self._tunnel_host:  # type: ignore[attr-defined]
                self.sock = sock
                self._tunnel()  # type: ignore[attr-defined]
            self.sock = self._context.wrap_socket(  # type: ignore[attr-defined]
                sock, server_hostname=self.host
            )
        except Exception:
            sock.close()
            raise


def _build_https_connection(
    *,
    hostname: str,
    pinned_ip: str,
    port: int,
    timeout: float,
    context: ssl.SSLContext,
) -> _PinnedHTTPSConnection:
    """Factory seam — kept module-level so tests can patch it cleanly."""
    return _PinnedHTTPSConnection(
        hostname=hostname,
        pinned_ip=pinned_ip,
        port=port,
        timeout=timeout,
        context=context,
    )


def _safe_parse_url(url: str) -> tuple[Any, str, int] | None:
    """Return ``(parsed, hostname, port)`` for *url*, or None if malformed.

    Folds ``urlparse`` failures, missing hostnames, and invalid or
    out-of-range ports (``parsed.port`` raises ``ValueError`` for inputs
    such as ``https://example.com:bad/`` or ``https://example.com:99999/``)
    into a single ``None`` verdict so the caller can treat the URL as
    unsafe in one place. Centralizing this here closes the class of bug
    where downstream code accesses ``parsed.port`` outside the
    ``urlparse`` try/except envelope and leaks a ``ValueError`` to its
    own caller.
    """
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname or ""
        port = parsed.port if parsed.port is not None else 443
    except (ValueError, TypeError):
        return None
    if not hostname:
        return None
    return parsed, hostname, port


def is_blocked_url(url: str) -> bool:
    """Return True if *url* targets a blocked or private network address.

    Applied at flag-creation time (``_validate_http_config``) so organizers
    cannot persist an obviously unsafe destination. The runtime validator
    re-resolves with pinning, so config-time DNS-lookup failures here are
    tolerated (return False) rather than rejecting a legitimate URL whose
    DNS is briefly unavailable at organizer-edit time.
    """
    parsed_tuple = _safe_parse_url(url)
    if parsed_tuple is None:
        return True
    _parsed, hostname, port = parsed_tuple

    if hostname in _BLOCKED_HOSTNAMES:
        return True

    try:
        addr = ipaddress.ip_address(hostname)
    except ValueError:
        try:
            _resolve_and_validate(hostname, port)
        except _BlockedDestinationError:
            return True
        except (socket.gaierror, OSError):
            # DNS resolution failed; runtime validator will re-resolve
            # with pinning and fail closed there if the destination is
            # actually unsafe.
            return False
        return False

    return _is_blocked_address(addr)


def register_validator(name: str, func: ValidatorFunc) -> None:
    """Register a named validator function."""
    _VALIDATORS[name] = func


def get_validator(name: str) -> ValidatorFunc | None:
    """Get a registered validator by name, or None if unknown."""
    return _VALIDATORS.get(name)


def list_validators() -> list[str]:
    """Sorted list of registered validator names."""
    return sorted(_VALIDATORS.keys())


def _resolve_target(hostname: str, port: int, challenge_id: Any) -> list[str] | None:
    """Resolve and validate *hostname*, returning every safe pinned IP.

    Returns the full validated address list from the DNS reply on
    success so the send path can try each in turn (closes the reliability
    regression where a hostname with multiple A/AAAA records would fail
    when only its first record was temporarily unreachable). Returns
    None and logs on any failure (blocked address, lookup failure,
    empty reply).
    """
    try:
        addr = ipaddress.ip_address(hostname)
    except ValueError:
        pass
    else:
        if _is_blocked_address(addr):
            logger.error(
                "HTTP validator URL blocked (literal address) for challenge %s",
                safe_log(challenge_id),
            )
            return None
        return [hostname]

    if hostname in _BLOCKED_HOSTNAMES:
        logger.error(
            "HTTP validator URL blocked (metadata hostname) for challenge %s",
            safe_log(challenge_id),
        )
        return None

    try:
        addresses = _resolve_and_validate(hostname, port)
    except _BlockedDestinationError:
        logger.error(
            "HTTP validator URL blocked (DNS answer in restricted range) for challenge %s",
            safe_log(challenge_id),
        )
        return None
    except (socket.gaierror, OSError):
        logger.warning(
            "HTTP validator hostname resolution failed for challenge %s",
            safe_log(challenge_id),
        )
        return None

    return addresses


def _coerce_timeout(value: Any) -> int:
    if not isinstance(value, (int, float)) or value < 1:
        value = DEFAULT_HTTP_TIMEOUT
    return min(int(value), MAX_HTTP_TIMEOUT)


def _coerce_method(value: Any) -> str:
    method = str(value).upper() if value is not None else "POST"
    return method if method in ("GET", "POST") else "POST"


# Transport-managed headers MUST NOT be settable from validator_config:
# `Host` would let an organizer redirect cert/Host semantics away from the
# validated hostname (breaking the DNS-pinning contract); `Content-Length`
# and `Transfer-Encoding` would collide with the body framing
# `_build_request` generates; `Connection` is owned by `http.client`.
_RESERVED_HEADERS = frozenset(
    {
        "host",
        "content-length",
        "transfer-encoding",
        "connection",
    }
)


def _coerce_headers(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {str(k): str(v) for k, v in value.items() if str(k).strip().lower() not in _RESERVED_HEADERS}


def _has_header_ci(headers: dict[str, str], name: str) -> bool:
    """Return True if *headers* already contains *name* case-insensitively."""
    target = name.strip().lower()
    return any(k.strip().lower() == target for k in headers)


def _request_target(parsed) -> str:
    """Build the HTTP request-target from *parsed*.

    Preserves every component http.client needs to relay: ``path``,
    RFC 3986 path parameters (``;tenant=a``), and the existing query
    string. The fragment is intentionally omitted — it is client-side
    metadata and must never reach the wire.
    """
    path = parsed.path or "/"
    params = f";{parsed.params}" if parsed.params else ""
    query = f"?{parsed.query}" if parsed.query else ""
    return f"{path}{params}{query}"


def _build_request(
    parsed,
    method: str,
    payload: dict[str, Any],
    headers: dict[str, str],
) -> tuple[str, bytes | None, dict[str, str]]:
    """Return ``(request_path, body, headers)`` for the chosen method.

    Both methods preserve any path parameters and existing query string
    from the configured URL — validator endpoints often use the query
    or path params for routing, tenant selection, or a shared secret.
    GET appends the submitted payload as additional query parameters;
    POST sends the payload as a JSON body and sets Content-Type/Length.
    """
    base_target = _request_target(parsed)

    if method == "GET":
        qs = urlencode(payload)
        separator = "&" if parsed.query else "?"
        return f"{base_target}{separator}{qs}", None, headers

    body = json.dumps(payload).encode("utf-8")
    if not _has_header_ci(headers, "Content-Type"):
        headers["Content-Type"] = "application/json"
    headers["Content-Length"] = str(len(body))
    return base_target, body, headers


def _parse_response(resp: Any, challenge_id: Any) -> bool:
    """Decode the validator response. True iff HTTP 200 + ``{"valid": true}``."""
    status = getattr(resp, "status", None)
    if status != 200:
        logger.warning(
            "HTTP validator returned status %s for challenge %s",
            safe_log(status),
            safe_log(challenge_id),
        )
        return False

    # http.client does NOT follow Location: by default, so an attacker
    # cannot bounce the validation request to a private address via 3xx.
    raw = resp.read(_MAX_RESPONSE_BYTES + 1)
    if len(raw) > _MAX_RESPONSE_BYTES:
        logger.warning(
            "HTTP validator response oversized for challenge %s",
            safe_log(challenge_id),
        )
        return False

    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        logger.warning(
            "HTTP validator response not JSON for challenge %s",
            safe_log(challenge_id),
        )
        return False

    if not isinstance(data, dict):
        return False
    return bool(data.get("valid", False))


def _try_one_address(
    *,
    hostname: str,
    pinned_ip: str,
    port: int,
    timeout: int,
    method: str,
    request_path: str,
    body: bytes | None,
    headers: dict[str, str],
    challenge_id: Any,
) -> tuple[bool, bool]:
    """Attempt one pinned-address request.

    Returns ``(got_response, verdict)``:

    * ``(True, bool)`` — the server returned a response. The verdict is
      the parsed True/False outcome; the caller stops iterating.
    * ``(False, False)`` — the transport, TLS, or HTTP layer failed
      before a response landed. The caller may try the next pinned
      address.
    """
    conn: http.client.HTTPSConnection | None = None
    try:
        context = ssl.create_default_context()
        conn = _build_https_connection(
            hostname=hostname,
            pinned_ip=pinned_ip,
            port=port,
            timeout=timeout,
            context=context,
        )
        if body is None:
            conn.request(method, request_path, headers=headers)
        else:
            conn.request(method, request_path, body=body, headers=headers)
        resp = conn.getresponse()
        return True, _parse_response(resp, challenge_id)
    except TimeoutError:
        logger.warning(
            "HTTP validator timed out after %ds for challenge %s",
            timeout,
            safe_log(challenge_id),
        )
        return False, False
    except ssl.SSLError:
        logger.warning(
            "HTTP validator TLS error for challenge %s",
            safe_log(challenge_id),
        )
        return False, False
    except (OSError, http.client.HTTPException):
        logger.warning(
            "HTTP validator transport error for challenge %s",
            safe_log(challenge_id),
        )
        return False, False
    finally:
        if conn is not None:
            with contextlib.suppress(Exception):
                conn.close()


def _send_validation_request(
    *,
    hostname: str,
    pinned_ips: list[str],
    port: int,
    timeout: int,
    method: str,
    request_path: str,
    body: bytes | None,
    headers: dict[str, str],
    challenge_id: Any,
) -> bool:
    """Try each pre-validated pinned IP in order until one returns a response.

    Iteration order matches DNS reply order. Transport-layer failures
    (timeout, TLS handshake, connection refused, HTTP framing) fall
    through to the next address. The first HTTP response — regardless
    of status — terminates the loop and is decoded by ``_parse_response``.
    Returns False if every pinned address failed at the transport layer.
    """
    for pinned_ip in pinned_ips:
        got_response, verdict = _try_one_address(
            hostname=hostname,
            pinned_ip=pinned_ip,
            port=port,
            timeout=timeout,
            method=method,
            request_path=request_path,
            body=body,
            headers=headers,
            challenge_id=challenge_id,
        )
        if got_response:
            return verdict
    return False


def validate_http(
    submitted_flag: str,
    config: dict[str, Any],
    challenge_id: Any,
) -> bool:
    """Validate a flag submission via an external HTTPS endpoint.

    Sends ``{"flag": submitted_flag, "challenge_id": str(challenge_id)}``
    (POST as JSON, or GET as query string) to ``config["url"]`` over a
    TLS socket whose TCP destination is pinned to a pre-validated address
    from the same DNS reply that passed SSRF policy. This closes the
    resolution TOCTOU between policy check and connect that an attacker
    could otherwise exploit via DNS rebinding to reach loopback, private,
    link-local, or metadata addresses.

    Returns True only on HTTP 200 + ``{"valid": true}``. Fails closed on
    every other path (non-HTTPS URL, blocked destination, DNS failure,
    timeout, TLS error, transport error, non-JSON or oversized body,
    invalid JSON).
    """
    url = config.get("url")
    if not url:
        logger.error("HTTP validator missing 'url' in config")
        return False

    if not isinstance(url, str) or not url.startswith("https://"):
        logger.error(
            "HTTP validator URL must use HTTPS for challenge %s",
            safe_log(challenge_id),
        )
        return False

    parsed_tuple = _safe_parse_url(url)
    if parsed_tuple is None:
        logger.error(
            "HTTP validator URL is malformed for challenge %s",
            safe_log(challenge_id),
        )
        return False
    parsed, hostname, port = parsed_tuple

    pinned_ips = _resolve_target(hostname, port, challenge_id)
    if not pinned_ips:
        return False

    timeout = _coerce_timeout(config.get("timeout", DEFAULT_HTTP_TIMEOUT))
    method = _coerce_method(config.get("method", "POST"))
    headers = _coerce_headers(config.get("headers", {}))
    payload = {"flag": submitted_flag, "challenge_id": str(challenge_id)}
    request_path, body, headers = _build_request(parsed, method, payload, headers)

    return _send_validation_request(
        hostname=hostname,
        pinned_ips=pinned_ips,
        port=port,
        timeout=timeout,
        method=method,
        request_path=request_path,
        body=body,
        headers=headers,
        challenge_id=challenge_id,
    )


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
