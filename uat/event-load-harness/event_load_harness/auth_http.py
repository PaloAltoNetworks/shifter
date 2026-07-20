"""Live authenticator: turn an Actor into an authenticated httpx client.

Two paths, both replaying the app's *real* session flow (no test-only bypass):

* ``session_cookie`` actors: the operator supplies an already-valid session
  cookie (e.g. captured from a real login); we attach it to the client jar.
* ``dev-login`` / password actors: drive the documented ``/dev-login/`` endpoint
  (GET for the CSRF cookie, then POST email + user_type), valid only where
  dev-login is enabled on a deployed dev target.

Failures raise ``AuthError`` labelled with ``actor.label`` only - never the
email, password, or cookie.
"""

from __future__ import annotations

from urllib.parse import urlparse

import httpx

from event_load_harness.auth import Actor, AuthError


def make_authenticator(*, timeout: float = 30.0, dev_login_path: str = "/dev-login/"):
    """Return an async ``(base_url, actor) -> httpx.AsyncClient`` authenticator."""

    async def authenticate(base_url: str, actor: Actor) -> httpx.AsyncClient:
        client = build_client(base_url, timeout)
        try:
            if actor.session_cookie:
                _attach_cookies(client, actor.session_cookie, base_url)
                return client
            await _dev_login(client, actor, dev_login_path)
            return client
        except AuthError:
            await client.aclose()
            raise
        except Exception as exc:
            await client.aclose()
            raise AuthError(f"authentication error for {actor.label}") from exc

    return authenticate


def build_client(base_url: str, timeout: float) -> httpx.AsyncClient:
    """Construct the authenticated client.

    ``follow_redirects=False`` so an authenticated request never silently chases
    an off-origin redirect (e.g. an expired-session OIDC bounce) and replays the
    session there; the harness measures the real response at the configured origin.
    """
    return httpx.AsyncClient(base_url=base_url, timeout=timeout, follow_redirects=False)


def _attach_cookies(client: httpx.AsyncClient, cookie_str: str, base_url: str) -> None:
    """Attach operator-supplied cookies, scoped to the target host and path '/'.

    Host-scoping prevents a Shifter session cookie from being forwarded to a
    different host if any request is redirected off-origin.
    """
    host = urlparse(base_url).hostname or ""
    for part in cookie_str.split(";"):
        part = part.strip()
        if "=" in part:
            name, value = part.split("=", 1)
            client.cookies.set(name.strip(), value.strip(), domain=host, path="/")


async def _dev_login(client: httpx.AsyncClient, actor: Actor, dev_login_path: str) -> None:
    # Prime the CSRF cookie, then post the dev-login form.
    await client.get(dev_login_path)
    csrf = client.cookies.get("csrftoken")
    headers = {"X-CSRFToken": csrf} if csrf else {}
    data = {"email": actor.email, "user_type": actor.user_type}
    if actor.password:
        data["password"] = actor.password
    resp = await client.post(dev_login_path, data=data, headers=headers)
    if resp.status_code >= 400:
        raise AuthError(f"dev-login failed for {actor.label}: HTTP {resp.status_code}")
