#!/usr/bin/env python3
"""Cognito-shaped OIDC provider double for the built-image stack smoke (#988).

The #922 stack smoke minted a Django session directly and never exercised the
real login flow. This is the local, deterministic identity-provider double that
lets the smoke drive the *real* authorization-code flow end to end:

    /login/ -> mozilla_django_oidc init -> this /oauth2/authorize
    -> /oidc/callback/ -> portal token/JWKS/UserInfo backchannel to this stub
    -> ShifterOIDCBackend verify+provision -> Django session.

Only the identity provider is doubled (the ADR-019 external boundary). The stub
serves the *exact* endpoint shapes ``config._oidc_settings`` derives from the
Cognito contract, keeping the auth-domain and issuer bases distinct even when
both resolve to this one service:

* ``{auth_domain}/oauth2/authorize`` - authorization endpoint (browser hop);
* ``{auth_domain}/oauth2/token``     - token endpoint (portal backchannel);
* ``{auth_domain}/oauth2/userInfo``  - UserInfo endpoint (portal backchannel);
* ``{issuer}/.well-known/jwks.json`` - RS256 public JWKS (token verification).

It is deliberately *fail-closed*, so a real OIDC configuration/callback
regression is caught rather than papered over: it rejects the wrong client id
or secret, a wrong/absent redirect URI, a reused authorization code, a missing
bearer token, and never issues an HS256/unsigned token. The RS256 keypair is
generated fresh at startup (no committed private key), and the ID token is bound
to the per-request ``state``/``nonce`` the real library generated - a recorded
or precomputed response would not pass.

Runs under the built portal image's interpreter (``--entrypoint python3``),
reusing its in-image ``PyJWT`` + ``cryptography`` (the same libraries
mozilla-django-oidc itself depends on). No secret values or request query
strings are logged.
"""

from __future__ import annotations

import argparse
import base64
import json
import secrets
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

# --- One fixed synthetic identity. The app must receive it only through the
#     real authorization response + token/UserInfo calls, never a shortcut. ---
DEFAULT_SUBJECT = "stack-smoke-oidc-subject"
DEFAULT_EMAIL = "stack-smoke-oidc@example.test"

_ACCESS_TOKEN_TTL = 300
_ID_TOKEN_TTL = 300


class _Config:
    """Immutable stub configuration derived from the smoke's OIDC env values."""

    def __init__(self, args: argparse.Namespace) -> None:
        self.client_id: str = args.client_id
        self.client_secret: str = args.client_secret
        self.redirect_uri: str = args.redirect_uri
        self.issuer: str = args.issuer.rstrip("/")
        self.subject: str = args.subject
        self.email: str = args.email
        # Auth-domain and issuer are distinct Cognito bases; model that contract
        # even when both point at this one service. Endpoint *paths* are the
        # fixed Cognito shapes config._oidc_settings concatenates.
        auth_path = urlparse(args.auth_domain).path.rstrip("/")
        issuer_path = urlparse(self.issuer).path.rstrip("/")
        self.authorize_path = f"{auth_path}/oauth2/authorize"
        self.token_path = f"{auth_path}/oauth2/token"
        self.userinfo_path = f"{auth_path}/oauth2/userInfo"
        self.jwks_path = f"{issuer_path}/.well-known/jwks.json"


def _b64url_uint(value: int) -> str:
    raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


class _Keys:
    """Ephemeral RS256 signing keypair + its published JWKS (one ``kid``)."""

    def __init__(self) -> None:
        self._private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.kid = secrets.token_hex(8)
        numbers = self._private.public_key().public_numbers()
        self.jwks = {
            "keys": [
                {
                    "kty": "RSA",
                    "use": "sig",
                    "alg": "RS256",
                    "kid": self.kid,
                    "n": _b64url_uint(numbers.n),
                    "e": _b64url_uint(numbers.e),
                }
            ]
        }

    def sign_id_token(self, claims: dict[str, Any]) -> str:
        return jwt.encode(claims, self._private, algorithm="RS256", headers={"kid": self.kid})


class _State:
    """In-memory, single-use authorization codes and issued access tokens."""

    def __init__(self) -> None:
        self.codes: dict[str, dict[str, str]] = {}
        self.access_tokens: set[str] = set()


class _Handler(BaseHTTPRequestHandler):
    cfg: _Config
    keys: _Keys
    state: _State

    # http.server logs the full request line (with query string) to stderr by
    # default; that would leak code/state/nonce. Emit only method + path (no
    # query) + status, never bodies, headers, or query values.
    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - base signature
        # Method + path only. Never the query string (carries code/state/nonce).
        path = urlparse(self.path).path
        sys.stderr.write(f"[stub-idp] {self.command} {path}\n")

    # --- response helpers ---------------------------------------------------
    def _json(self, status: int, body: dict[str, Any]) -> None:
        payload = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _error(self, status: int, error: str) -> None:
        # OAuth-shaped error; carries no client/redirect echo.
        self._json(status, {"error": error})

    def _redirect(self, location: str) -> None:
        self.send_response(302)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    # --- routing ------------------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        path = urlparse(self.path).path
        if path == self.cfg.jwks_path:
            self._json(200, self.keys.jwks)
        elif path == self.cfg.authorize_path:
            self._handle_authorize()
        elif path == self.cfg.userinfo_path:
            self._handle_userinfo()
        else:
            self._error(404, "not_found")

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        if urlparse(self.path).path == self.cfg.token_path:
            self._handle_token()
        else:
            self._error(404, "not_found")

    # --- endpoints ----------------------------------------------------------
    def _handle_authorize(self) -> None:
        params = {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}
        redirect_uri = params.get("redirect_uri", "")
        # Validate the redirect URI first and NEVER redirect to an unvalidated
        # one: an accept-anything redirector is an open redirect and would hide
        # a callback-URL regression.
        if redirect_uri != self.cfg.redirect_uri:
            self._error(400, "invalid_redirect_uri")
            return
        if params.get("client_id") != self.cfg.client_id:
            self._error(400, "unauthorized_client")
            return
        if params.get("response_type") != "code":
            self._error(400, "unsupported_response_type")
            return
        if "openid" not in params.get("scope", "").split():
            self._error(400, "invalid_scope")
            return
        state = params.get("state", "")
        nonce = params.get("nonce", "")
        if not state or not nonce:
            self._error(400, "invalid_request")
            return
        code = secrets.token_urlsafe(24)
        self.state.codes[code] = {"nonce": nonce, "redirect_uri": redirect_uri}
        sep = "&" if "?" in redirect_uri else "?"
        self._redirect(f"{redirect_uri}{sep}code={code}&state={state}")

    def _read_form(self) -> dict[str, str]:
        length = int(self.headers.get("Content-Length", "0") or "0")
        raw = self.rfile.read(length).decode("utf-8") if length else ""
        return {k: v[0] for k, v in parse_qs(raw).items()}

    def _client_credentials(self, form: dict[str, str]) -> tuple[str, str]:
        # mozilla-django-oidc sends client_id/secret in the body by default;
        # accept HTTP Basic too so the double stays protocol-honest.
        header = self.headers.get("Authorization", "")
        if header.startswith("Basic "):
            try:
                decoded = base64.b64decode(header[6:]).decode("utf-8")
                cid, _, secret = decoded.partition(":")
                return cid, secret
            except (ValueError, UnicodeDecodeError):
                return "", ""
        return form.get("client_id", ""), form.get("client_secret", "")

    def _handle_token(self) -> None:
        form = self._read_form()
        client_id, client_secret = self._client_credentials(form)
        if client_id != self.cfg.client_id or client_secret != self.cfg.client_secret:
            self._error(401, "invalid_client")
            return
        if form.get("grant_type") != "authorization_code":
            self._error(400, "unsupported_grant_type")
            return
        code = form.get("code", "")
        entry = self.state.codes.pop(code, None)  # single use: pop before issuing
        if entry is None:
            self._error(400, "invalid_grant")
            return
        if form.get("redirect_uri") != entry["redirect_uri"]:
            self._error(400, "invalid_grant")
            return
        now = int(time.time())
        id_token = self.keys.sign_id_token(
            {
                "iss": self.cfg.issuer,
                "sub": self.cfg.subject,
                "aud": self.cfg.client_id,
                "azp": self.cfg.client_id,
                "nonce": entry["nonce"],
                "email": self.cfg.email,
                "email_verified": True,
                "token_use": "id",
                "iat": now,
                "exp": now + _ID_TOKEN_TTL,
            }
        )
        access_token = secrets.token_urlsafe(24)
        self.state.access_tokens.add(access_token)
        self._json(
            200,
            {
                "access_token": access_token,
                "id_token": id_token,
                "token_type": "Bearer",
                "expires_in": _ACCESS_TOKEN_TTL,
            },
        )

    def _handle_userinfo(self) -> None:
        header = self.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            self._error(401, "invalid_token")
            return
        if header[7:] not in self.state.access_tokens:
            self._error(401, "invalid_token")
            return
        # UserInfo subject must equal the ID-token subject (the backend enforces
        # parity); email_verified is the literal JSON boolean true.
        self._json(200, {"sub": self.cfg.subject, "email": self.cfg.email, "email_verified": True})


def _build_handler(cfg: _Config, keys: _Keys, state: _State) -> type[_Handler]:
    return type("BoundHandler", (_Handler,), {"cfg": cfg, "keys": keys, "state": state})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="0.0.0.0")  # noqa: S104 - private smoke network
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--issuer", required=True, help="OIDC_ISSUER_URL (iss + JWKS base)")
    parser.add_argument("--auth-domain", required=True, help="OIDC_AUTH_DOMAIN (oauth2 endpoints base)")
    parser.add_argument("--client-id", required=True)
    parser.add_argument("--client-secret", required=True)
    parser.add_argument("--redirect-uri", required=True, help="exact registered callback URI")
    parser.add_argument("--subject", default=DEFAULT_SUBJECT)
    parser.add_argument("--email", default=DEFAULT_EMAIL)
    args = parser.parse_args()

    cfg = _Config(args)
    handler = _build_handler(cfg, _Keys(), _State())
    server = ThreadingHTTPServer((args.host, args.port), handler)
    sys.stderr.write(f"[stub-idp] listening on {args.host}:{args.port}\n")
    sys.stderr.flush()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
