"""Obtaining a genuine participant session — no bypass, no product change.

The terminal check needs a real Django session: ``AuthMiddlewareStack`` authen-
ticates Channels from the session cookie, and a bearer API token does not
authenticate a websocket. So the session must come from a path the product
already trusts. Two actor sources, both real logins:

``cookie``
    An operator captures a session from a normal browser login and drops it in a
    0600 file. The harness attaches it host-scoped. This is the same seam
    ``uat/event-load-harness`` already uses.

``identity-platform``
    The full front-door flow for a credential the tenant operator provisioned:
    password sign-in, the TOTP second factor, then the product's own
    ``POST /auth/identity/session/`` exchange. ``config.identity_platform``
    independently re-checks ``emailVerified`` and enrolled MFA on that exchange,
    so this is the same admission a human gets — not a shortcut around it.

Explicitly *not* used: ``/dev-login/`` (a dev-only bypass, and disabled outside
``ENVIRONMENT=development`` anyway), an Admin-SDK custom-token mint, a superuser
path, or any smoke-only session endpoint. Credential material is kept off
``repr``, off argv, and out of every log line and report.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import stat
import struct
import time
from dataclasses import dataclass, field

_TOTP_PERIOD = 30
_TOTP_DIGITS = 6
# Password sign-in lives on v1; the multi-factor endpoints live on v2.
_IDENTITY_API_V1 = "https://identitytoolkit.googleapis.com/v1"
_IDENTITY_API_V2 = "https://identitytoolkit.googleapis.com/v2"
#: Product endpoint that turns a verified ID token into a Django session.
SESSION_EXCHANGE_PATH = "/auth/identity/session/"
#: Rendered login page; visiting it primes the CSRF cookie, as the browser does.
LOGIN_PATH = "/login/"


class SessionError(RuntimeError):
    """Raised for an actor-source or login failure. Never carries a credential."""


@dataclass(frozen=True)
class Credential:
    """An Identity Platform login credential. Secret fields stay off ``repr``."""

    email: str = field(repr=False)
    password: str = field(repr=False)
    totp_secret: str = field(repr=False)
    api_key: str = field(repr=False)

    def __post_init__(self) -> None:
        for name in ("email", "password", "totp_secret", "api_key"):
            if not str(getattr(self, name) or "").strip():
                raise SessionError(f"credential is missing {name}")


def load_session_cookie(path: str) -> str:
    """Read an operator-captured session key from a 0600 file.

    The permission check is a refusal, not a warning: the file holds a live
    session that grants the participant's full product access.
    """
    try:
        info = os.stat(path)
    except OSError as exc:
        raise SessionError(f"session file is not readable: {path}") from exc
    if stat.S_IMODE(info.st_mode) & 0o077:
        raise SessionError(
            f"session file {path} is group/world accessible and holds a live session; restrict it with `chmod 600`"
        )
    try:
        with open(path, encoding="utf-8") as handle:
            value = handle.read().strip()
    except OSError as exc:
        raise SessionError(f"could not read session file {path}") from exc
    if not value:
        raise SessionError(f"session file {path} is empty")
    return value


def totp_code(secret_base32: str, *, at_time: float | None = None) -> str:
    """Compute an RFC 6238 TOTP code (SHA-1, 30s period, 6 digits).

    Identity Platform's TOTP factor uses the standard parameters, so the code is
    derived here rather than adding a dependency for nine lines of HMAC.
    """
    normalized = "".join(str(secret_base32).split()).upper()
    normalized += "=" * (-len(normalized) % 8)
    try:
        key = base64.b32decode(normalized, casefold=True)
    except Exception as exc:
        raise SessionError("TOTP secret is not valid base32") from exc

    counter = int((time.time() if at_time is None else at_time) // _TOTP_PERIOD)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    truncated = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(truncated % (10**_TOTP_DIGITS)).zfill(_TOTP_DIGITS)


async def _request(client, method: str, url: str, *, label: str, **kwargs):
    """Perform one HTTP call, normalising transport failures into ``SessionError``.

    Every authentication await goes through here. DNS failure, a refused
    connection, a TLS error, or a read timeout are all *expected* outcomes when
    pointing a harness at a live deployment, but they raise ``httpx`` exceptions
    rather than ``SessionError``. Uncaught, they escape the runner's
    ``except SessionError`` around authentication and abort the whole run with a
    traceback — no ``session_established`` result, no report, no verdict, which
    contradicts the fail-closed contract this harness exists to uphold.

    Normalising at the single boundary (rather than per call site) means a new
    authentication step cannot reintroduce the gap. The message is authored and
    names only the exception type, never a URL, body, or credential.
    """
    try:
        return await client.request(method, url, **kwargs)
    except Exception as exc:
        raise SessionError(f"{label} could not reach the target ({type(exc).__name__})") from exc


def _identity_error(payload: dict) -> str:
    """Extract the stable Identity Platform error code, never the raw body."""
    error = payload.get("error")
    if isinstance(error, dict):
        return str(error.get("message", "")).split(":", 1)[0].strip() or "unknown_error"
    return "unknown_error"


async def identity_platform_id_token(client, credential: Credential, *, timeout: float) -> str:
    """Drive password + TOTP sign-in and return the resulting ID token.

    Handles both shapes the API returns: a direct ``idToken`` when no second
    factor is pending, and the ``mfaPendingCredential`` challenge that an
    MFA-enrolled account gets, which is finalized with a computed TOTP code.
    """
    first = await _request(
        client,
        "POST",
        f"{_IDENTITY_API_V1}/accounts:signInWithPassword?key={credential.api_key}",
        label="password sign-in",
        json={"email": credential.email, "password": credential.password, "returnSecureToken": True},
        timeout=timeout,
    )
    payload = _json_or_error(first, "password sign-in")
    if first.status_code >= 400:
        raise SessionError(f"password sign-in refused ({_identity_error(payload)})")

    if payload.get("idToken"):
        return str(payload["idToken"])

    pending = payload.get("mfaPendingCredential")
    enrollments = payload.get("mfaInfo") or []
    if not pending or not enrollments:
        raise SessionError("sign-in returned neither an ID token nor an MFA challenge")

    enrollment_id = str(enrollments[0].get("mfaEnrollmentId", ""))
    if not enrollment_id:
        raise SessionError("MFA challenge carried no enrollment id")

    # TOTP finalizes directly: ``mfaSignIn:start`` exists to *send* a code, which
    # only applies to SMS. An authenticator code is already in the operator's
    # hands, so starting a challenge here would fail with a missing-phone-info
    # error rather than advancing the flow.
    finalized = await _request(
        client,
        "POST",
        f"{_IDENTITY_API_V2}/accounts/mfaSignIn:finalize?key={credential.api_key}",
        label="MFA finalize",
        json={
            "mfaPendingCredential": pending,
            "mfaEnrollmentId": enrollment_id,
            "totpVerificationInfo": {"verificationCode": totp_code(credential.totp_secret)},
        },
        timeout=timeout,
    )
    final_payload = _json_or_error(finalized, "MFA finalize")
    if finalized.status_code >= 400 or not final_payload.get("idToken"):
        raise SessionError(f"MFA finalize refused ({_identity_error(final_payload)})")
    return str(final_payload["idToken"])


async def exchange_id_token_for_session(client, id_token: str, *, timeout: float) -> None:
    """Exchange a verified ID token for a Django session on the target portal.

    The cookie lands in ``client``'s jar. The product re-verifies the token,
    re-checks ``emailVerified`` and enrolled MFA, and only then calls
    ``django.contrib.auth.login`` — this is the real admission boundary.
    """
    # The exchange is a normal session-authenticated POST, so Django's CSRF
    # protection applies exactly as it does for the browser: the login page sets
    # the token cookie and the client echoes it back. Skipping this step earns an
    # HTML 403 from the CSRF middleware rather than a JSON auth error.
    headers = {"Referer": str(client.base_url).rstrip("/") + "/"}
    if not client.cookies.get("csrftoken"):
        await _request(client, "GET", LOGIN_PATH, label="login page", headers={"Accept": "text/html"}, timeout=timeout)
    csrf = client.cookies.get("csrftoken")
    if csrf:
        headers["X-CSRFToken"] = csrf

    response = await _request(
        client,
        "POST",
        SESSION_EXCHANGE_PATH,
        label="session exchange",
        json={"idToken": id_token},
        headers=headers,
        timeout=timeout,
    )
    if response.status_code >= 400:
        payload = _json_or_error(response, "session exchange")
        raise SessionError(f"session exchange refused: HTTP {response.status_code} ({payload.get('error', 'unknown')})")
    if not client.cookies.get("sessionid"):
        raise SessionError("session exchange succeeded but set no session cookie")


def _json_or_error(response, label: str) -> dict:
    """Parse a JSON body, mapping an unparseable one to an authored failure."""
    try:
        payload = response.json()
    except Exception as exc:
        raise SessionError(f"{label} returned a non-JSON response (HTTP {response.status_code})") from exc
    return payload if isinstance(payload, dict) else {}
