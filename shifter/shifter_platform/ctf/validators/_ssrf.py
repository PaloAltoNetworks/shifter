"""SSRF / DNS-pinning policy for programmable and HTTP flag validators.

Owns the blocklist policy (private, loopback, link-local, reserved,
multicast, unspecified addresses plus the metadata/localhost hostname
list), DNS resolution against that policy, and the pinned-IP HTTPS
connection used to close the resolve-then-connect TOCTOU window.
"""

from __future__ import annotations

import http.client
import ipaddress
import socket
import ssl
from typing import Any
from urllib.parse import urlparse

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

    def connect(
        self,
    ) -> None:  # pragma: no cover  # NOSONAR
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


def _hostname_and_port_from_url(url: str) -> tuple[str, int] | None:
    """Return ``(hostname, port)`` for *url*, or None if malformed or directly blocklisted."""
    parsed_tuple = _safe_parse_url(url)
    if parsed_tuple is None:
        return None
    _parsed, hostname, port = parsed_tuple
    if hostname in _BLOCKED_HOSTNAMES:
        return None
    return hostname, port


def _is_blocked_hostname_via_dns(hostname: str, port: int) -> bool:
    """Return True if every address DNS returns for *hostname* is policy-blocked.

    Config-time DNS-lookup failures are tolerated (return False) rather than
    rejecting a legitimate URL whose DNS is briefly unavailable at
    organizer-edit time; the runtime validator re-resolves with pinning and
    fails closed there if the destination is actually unsafe.
    """
    try:
        _resolve_and_validate(hostname, port)
    except _BlockedDestinationError:
        return True
    except OSError:
        # socket.gaierror is a subclass of OSError, so this also covers
        # DNS resolution failure.
        pass
    return False


def is_blocked_url(url: str) -> bool:
    """Return True if *url* targets a blocked or private network address.

    Applied at flag-creation time (``_validate_http_config``) so organizers
    cannot persist an obviously unsafe destination. The runtime validator
    re-resolves with pinning, so config-time DNS-lookup failures here are
    tolerated (return False) rather than rejecting a legitimate URL whose
    DNS is briefly unavailable at organizer-edit time.
    """
    resolved = _hostname_and_port_from_url(url)
    if resolved is None:
        return True
    hostname, port = resolved

    try:
        addr = ipaddress.ip_address(hostname)
    except ValueError:
        return _is_blocked_hostname_via_dns(hostname, port)

    return _is_blocked_address(addr)
