"""Live authenticator: turn an Actor into an authenticated httpx client.

Three paths replay the app's real session flow (no test-only bypass):

* Strict-gate actors always perform Identity Platform password/TOTP sign-in and
  product-session exchange; supplied session cookies are rejected.
* Non-strict ``session_cookie`` actors attach an already-valid session cookie.
* Other non-strict actors drive the documented ``/dev-login/`` endpoint, valid
  only where dev-login is enabled on a deployed dev target.

Failures raise ``AuthError`` labelled with ``actor.label`` only - never the
email, password, or cookie.
"""

from __future__ import annotations

from urllib.parse import urlparse

import httpx

from event_load_harness.auth import Actor, AuthError


def make_authenticator(
    *, timeout: float = 30.0, dev_login_path: str = "/dev-login/", require_identity_platform: bool = False
):
    """Return an async ``(base_url, actor) -> httpx.AsyncClient`` authenticator."""

    async def authenticate(base_url: str, actor: Actor) -> httpx.AsyncClient:
        client = build_client(base_url, timeout)
        try:
            if require_identity_platform:
                if actor.session_cookie:
                    raise AuthError(
                        f"strict Identity Platform authentication does not accept session cookies for {actor.label}"
                    )
                await _identity_platform_login(client, actor, timeout)
                return client
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


async def _identity_platform_login(client: httpx.AsyncClient, actor: Actor, timeout: float) -> None:
    """Reuse the range smoke's real password/TOTP/product-session boundary."""
    from range_functional_smoke.session import (
        Credential,
        SessionError,
        exchange_id_token_for_session,
        identity_platform_id_token,
    )

    if not actor.password or not actor.totp_secret or not actor.api_key:
        raise AuthError(
            f"Identity Platform actor {actor.label} requires password, totp_secret, and api_key in the 0600 manifest"
        )
    credential = Credential(
        email=actor.email,
        password=actor.password,
        totp_secret=actor.totp_secret,
        api_key=actor.api_key,
    )
    try:
        token = await identity_platform_id_token(client, credential, timeout=timeout)
        await exchange_id_token_for_session(client, token, timeout=timeout)
    except SessionError as exc:
        raise AuthError(f"Identity Platform authentication failed for {actor.label}") from exc


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
