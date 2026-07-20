#!/usr/bin/env python3
"""Real-OIDC login driver for the built-image stack smoke (#988).

Drives the *real* authorization-code login flow against the built portal image
and the local Cognito-shaped provider double (``stub_idp.py``), then hands the
resulting authenticated session to the existing websocket/page probes. This
replaces the #922 direct ``SessionStore`` mint: the session is obtained the way
a browser obtains one, so a regression in OIDC config, the callback, first-login
provisioning, or session establishment fails the smoke.

Behaves like a browser with a cookie jar. It:

* starts at the public ``/login/`` router and follows the redirect chain through
  ``mozilla_django_oidc``'s init view to the provider ``/oauth2/authorize`` (an
  off-portal host), then back to ``/oidc/callback/`` - carrying the portal
  session cookie only to the portal, never to the provider;
* preserves the production security posture across every portal hop: the portal
  is addressed by its logical HTTPS origin (``Host`` + ``X-Forwarded-Proto:
  https``) while the request travels the private-network HTTP transport, so
  ``SECURE_PROXY_SSL_HEADER`` / secure-cookie / redirect-URI semantics stay
  real; only the transport is local;
* proves the resulting session authenticates a protected page (the
  callback-established session, not a minted one).

Only the final session key is written to stdout. Bounded phase diagnostics go
to stderr; no code, state, nonce, token, cookie value, or full URL (which can
carry those in its query string) is ever logged. Stdlib only.
"""

from __future__ import annotations

import argparse
import http.client
import sys
from urllib.parse import urljoin, urlparse

_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})


class LoginError(RuntimeError):
    """A bounded, redaction-safe login-flow failure (phase + short reason)."""


def _redact(url: str) -> str:
    """Return scheme://host/path for a URL, dropping any secret-bearing query."""
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"


class _Browser:
    """Minimal cookie-jar browser with logical-HTTPS -> HTTP transport mapping."""

    def __init__(self, portal_origin: str, portal_transport: str, cookie_name: str, timeout: float) -> None:
        self._portal_netloc = urlparse(portal_origin).netloc
        transport = urlparse(portal_transport)
        self._transport_host = transport.hostname or ""
        self._transport_port = transport.port or (443 if transport.scheme == "https" else 80)
        self._cookie_name = cookie_name
        self._timeout = timeout
        self.session: str | None = None
        self.saw_provider = False

    def is_portal(self, netloc: str) -> bool:
        return netloc == self._portal_netloc

    def _connect(self, netloc: str) -> tuple[http.client.HTTPConnection, dict[str, str]]:
        """Open a connection + base headers for a logical netloc, mapping transport."""
        if self.is_portal(netloc):
            conn = http.client.HTTPConnection(self._transport_host, self._transport_port, timeout=self._timeout)
            headers = {"Host": netloc, "X-Forwarded-Proto": "https", "Accept": "text/html"}
            if self.session:
                headers["Cookie"] = f"{self._cookie_name}={self.session}"
            return conn, headers
        # Provider (stub IdP): genuine HTTP on the private network, no cookies.
        self.saw_provider = True
        host = urlparse(f"//{netloc}").hostname or netloc
        port = urlparse(f"//{netloc}").port or 80
        conn = http.client.HTTPConnection(host, port, timeout=self._timeout)
        return conn, {"Accept": "text/html"}

    def _update_session(self, netloc: str, response: http.client.HTTPResponse) -> None:
        if not self.is_portal(netloc):
            return
        for header in response.msg.get_all("Set-Cookie") or []:
            first = header.split(";", 1)[0].strip()
            name, _, value = first.partition("=")
            if name == self._cookie_name and value:
                self.session = value

    def request(self, url: str, phase: str) -> tuple[int, str | None]:
        """One GET. Returns (status, Location). Never logs query/secret material."""
        parsed = urlparse(url)
        conn, headers = self._connect(parsed.netloc)
        target = parsed.path + (f"?{parsed.query}" if parsed.query else "")
        try:
            conn.request("GET", target, headers=headers)
            response = conn.getresponse()
            location = response.getheader("Location")
            self._update_session(parsed.netloc, response)
            response.read()  # drain; body is never logged
            return response.status, location
        except OSError as exc:
            raise LoginError(f"{phase}: transport error to {_redact(url)} ({type(exc).__name__})") from exc
        finally:
            conn.close()


def _classify_phase(url: str, is_portal: bool) -> str:
    if not is_portal:
        return "authorize"
    if "/callback" in urlparse(url).path:
        return "callback"
    return "login-router"


def _run_chain(browser: _Browser, start_url: str, max_redirects: int) -> None:
    """Follow the login redirect chain from /login/ to a terminal response."""
    url = start_url
    for _ in range(max_redirects):
        is_portal = browser.is_portal(urlparse(url).netloc)
        phase = _classify_phase(url, is_portal)
        status, location = browser.request(url, phase)
        if status in _REDIRECT_STATUSES:
            if not location:
                raise LoginError(f"{phase}: {status} redirect without a Location header")
            url = urljoin(url, location)
            continue
        if status >= 400:
            raise LoginError(f"{phase}: provider/portal returned HTTP {status}")
        return  # terminal non-redirect (chain landed)
    raise LoginError("login-router: exceeded redirect budget (possible redirect loop)")


def _verify_authenticated(browser: _Browser, protected_url: str, max_redirects: int) -> None:
    """Prove the captured session authenticates a protected page (no login bounce)."""
    if not browser.session:
        raise LoginError("authenticated-request: no session cookie was established by the callback")
    url = protected_url
    for _ in range(max_redirects):
        status, location = browser.request(url, "authenticated-request")
        if status == 200:
            return
        if status in _REDIRECT_STATUSES and location:
            nxt = urljoin(url, location)
            path = urlparse(nxt).path
            if "/login" in path or "/authenticate" in path or not browser.is_portal(urlparse(nxt).netloc):
                raise LoginError("authenticated-request: session bounced to login (auth not established)")
            url = nxt
            continue
        raise LoginError(f"authenticated-request: protected page returned HTTP {status}")
    raise LoginError("authenticated-request: exceeded redirect budget on protected page")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--portal-origin", required=True, help="logical HTTPS origin, e.g. https://host:8000")
    parser.add_argument("--portal-transport", required=True, help="actual transport, e.g. http://host:8000")
    parser.add_argument("--login-path", default="/login/")
    parser.add_argument("--protected-path", default="/dashboard/", help="protected page to prove the session")
    parser.add_argument("--cookie-name", default="sessionid")
    parser.add_argument("--max-redirects", type=int, default=12)
    parser.add_argument("--timeout", type=float, default=15.0)
    args = parser.parse_args()

    browser = _Browser(args.portal_origin, args.portal_transport, args.cookie_name, args.timeout)
    try:
        _run_chain(browser, urljoin(args.portal_origin, args.login_path), args.max_redirects)
        if not browser.saw_provider:
            raise LoginError("login-router: flow never reached the provider (login shortcut?)")
        _verify_authenticated(browser, urljoin(args.portal_origin, args.protected_path), args.max_redirects)
    except LoginError as exc:
        print(f"oidc-login: FAILED {exc}", file=sys.stderr)
        return 1

    # Success: the ONLY thing on stdout is the callback-established session key.
    print(browser.session)
    print("oidc-login: OK (real /login -> authorize -> callback -> authenticated session)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
