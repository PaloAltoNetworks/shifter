"""HTTP flag validator transport.

Builds and sends the validation request for HTTP flag types against a
pre-validated, DNS-pinned destination (see ``_ssrf.py`` for the pinning
and blocklist policy), and decodes the endpoint's response.

``_build_https_connection`` is resolved through the ``ctf.validators``
package at call time (``from ctf import validators as _v``) rather than
imported directly, so ``unittest.mock.patch`` targets of the form
``patch("ctf.validators._build_https_connection")`` keep working after
the package split -- see the package ``__init__`` docstring for the
full rationale. ``_BLOCKED_HOSTNAMES``, ``_BlockedDestinationError``,
``_is_blocked_address``, ``_resolve_and_validate``, and
``_safe_parse_url`` are never patched at the package path, so they are
imported directly from ``_ssrf``.
"""

from __future__ import annotations

import contextlib
import http.client
import ipaddress
import json
import logging
import ssl
from typing import Any
from urllib.parse import ParseResult, urlencode
from uuid import UUID

from shared.log_sanitize import safe_log

from ._ssrf import (
    _BLOCKED_HOSTNAMES,
    _BlockedDestinationError,
    _is_blocked_address,
    _resolve_and_validate,
    _safe_parse_url,
)

logger = logging.getLogger(__name__)

# Maximum timeout for HTTP validators (seconds)
MAX_HTTP_TIMEOUT = 30
DEFAULT_HTTP_TIMEOUT = 10

# Maximum response body to read from a validator endpoint (bytes).
# Caps memory/CPU exposure to an arbitrary attacker-controlled response.
_MAX_RESPONSE_BYTES = 1 * 1024 * 1024


def _resolve_literal_address(
    hostname: str,
    addr: ipaddress.IPv4Address | ipaddress.IPv6Address,
    challenge_id: UUID,
) -> list[str] | None:
    """Validate *hostname* (already parsed as *addr*) as a literal IP against SSRF policy."""
    if _is_blocked_address(addr):
        logger.error(
            "HTTP validator URL blocked (literal address) for challenge %s",
            safe_log(challenge_id),
        )
        return None
    return [hostname]


def _resolve_hostname_via_dns(hostname: str, port: int, challenge_id: UUID) -> list[str] | None:
    """Resolve *hostname* via DNS, applying SSRF policy to every address in the reply."""
    if hostname in _BLOCKED_HOSTNAMES:
        logger.error(
            "HTTP validator URL blocked (metadata hostname) for challenge %s",
            safe_log(challenge_id),
        )
        return None

    try:
        return _resolve_and_validate(hostname, port)
    except _BlockedDestinationError:
        logger.exception(
            "HTTP validator URL blocked (DNS answer in restricted range) for challenge %s",
            safe_log(challenge_id),
        )
    except OSError:
        # socket.gaierror is a subclass of OSError; this branch covers
        # both DNS lookup failure and any other resolver-layer OSError.
        logger.warning(
            "HTTP validator hostname resolution failed for challenge %s",
            safe_log(challenge_id),
        )
    return None


def _resolve_target(hostname: str, port: int, challenge_id: UUID) -> list[str] | None:
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
        return _resolve_hostname_via_dns(hostname, port, challenge_id)
    return _resolve_literal_address(hostname, addr, challenge_id)


def _coerce_timeout(value: object) -> int:
    """Coerce an organizer-supplied `timeout` config value to a safe bounded int."""
    if not isinstance(value, (int, float)) or value < 1:
        value = DEFAULT_HTTP_TIMEOUT
    return min(int(value), MAX_HTTP_TIMEOUT)


def _coerce_method(value: object) -> str:
    """Coerce an organizer-supplied `method` config value to `GET` or `POST` (default `POST`)."""
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


def _coerce_headers(value: object) -> dict[str, str]:
    """Coerce an organizer-supplied `headers` config value, dropping transport-reserved names."""
    if not isinstance(value, dict):
        return {}
    return {str(k): str(v) for k, v in value.items() if str(k).strip().lower() not in _RESERVED_HEADERS}


def _has_header_ci(headers: dict[str, str], name: str) -> bool:
    """Return True if *headers* already contains *name* case-insensitively."""
    target = name.strip().lower()
    return any(k.strip().lower() == target for k in headers)


def _request_target(parsed: ParseResult) -> str:
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
    parsed: ParseResult,
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


def _read_response_body(resp: http.client.HTTPResponse, challenge_id: UUID) -> dict[str, Any] | None:
    """Read and JSON-decode the validator response body, enforcing the size cap.

    Returns the decoded object only when it is valid JSON, within
    ``_MAX_RESPONSE_BYTES``, and a JSON object; returns None (with a
    warning) otherwise so the caller can fail closed uniformly.
    """
    raw = resp.read(_MAX_RESPONSE_BYTES + 1)
    if len(raw) > _MAX_RESPONSE_BYTES:
        logger.warning(
            "HTTP validator response oversized for challenge %s",
            safe_log(challenge_id),
        )
        return None

    try:
        data = json.loads(raw.decode("utf-8"))
    except ValueError:
        # UnicodeDecodeError is a subclass of ValueError, so this also
        # covers a non-UTF-8 response body.
        logger.warning(
            "HTTP validator response not JSON for challenge %s",
            safe_log(challenge_id),
        )
        return None

    return data if isinstance(data, dict) else None


def _parse_response(resp: http.client.HTTPResponse, challenge_id: UUID) -> bool:
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
    data = _read_response_body(resp, challenge_id)
    if data is None:
        return False
    return bool(data.get("valid", False))


def _try_one_address(
    # Moved private helper; already keyword-only. A parameter-object refactor is
    # out of scope for a behavior-preserving decomposition.
    *,  # NOSONAR
    hostname: str,
    pinned_ip: str,
    port: int,
    timeout: int,
    method: str,
    request_path: str,
    body: bytes | None,
    headers: dict[str, str],
    challenge_id: UUID,
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
        # Explicit floor — Python 3.12's default is already TLS 1.2+,
        # but pin it so a future runtime/distro lowering the default
        # cannot silently weaken validator-egress TLS.
        context.minimum_version = ssl.TLSVersion.TLSv1_2

        from ctf import validators as _v

        conn = _v._build_https_connection(
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
    except ssl.SSLError:
        logger.warning(
            "HTTP validator TLS error for challenge %s",
            safe_log(challenge_id),
        )
    except (OSError, http.client.HTTPException):
        logger.warning(
            "HTTP validator transport error for challenge %s",
            safe_log(challenge_id),
        )
    finally:
        if conn is not None:
            with contextlib.suppress(Exception):
                conn.close()
    return False, False


def _send_validation_request(
    # Moved private helper; already keyword-only. A parameter-object refactor is
    # out of scope for a behavior-preserving decomposition.
    *,  # NOSONAR
    hostname: str,
    pinned_ips: list[str],
    port: int,
    timeout: int,
    method: str,
    request_path: str,
    body: bytes | None,
    headers: dict[str, str],
    challenge_id: UUID,
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


def _validate_and_parse_config_url(config: dict[str, Any], challenge_id: UUID) -> tuple[Any, str, int] | None:
    """Validate `config["url"]` and return its parsed `(parsed, hostname, port)`.

    Fails closed (returns None, logging why) when the URL is missing,
    not HTTPS, or malformed.
    """
    url = config.get("url")
    if not url:
        logger.error("HTTP validator missing 'url' in config")
        return None

    if not isinstance(url, str) or not url.startswith("https://"):
        logger.error(
            "HTTP validator URL must use HTTPS for challenge %s",
            safe_log(challenge_id),
        )
        return None

    parsed_tuple = _safe_parse_url(url)
    if parsed_tuple is None:
        logger.error(
            "HTTP validator URL is malformed for challenge %s",
            safe_log(challenge_id),
        )
    return parsed_tuple


def validate_http(
    submitted_flag: str,
    config: dict[str, Any],
    challenge_id: UUID,
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
    parsed_tuple = _validate_and_parse_config_url(config, challenge_id)
    if parsed_tuple is None:
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
