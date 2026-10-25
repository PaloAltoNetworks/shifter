"""Provider credentials exist in the broker only, scoped to approved identities."""

import threading
import time
from collections.abc import Callable, Mapping
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import partial
from urllib.parse import urlsplit

from shared.model_access import ContractError
from shared.model_access.provider_runtime import ProviderTarget
from shared.model_access.source_credentials import (
    APIKeyCredential,
    AWSKeyCredential,
    GoogleKeyCredential,
    parse_source_credential,
)
from shared.model_access.work import BoundedWork

from .egress import provider_proxy

JSON_MEDIA_TYPE = "application/json"
_CREDENTIAL_WORK = BoundedWork(8, name="broker-provider")


@dataclass
class _CachedToken:
    """One approved target's short-lived access token and its early-expiry deadline."""

    token: str
    expires_at: float


class _AccessTokenCache:
    """In-memory, single-flight access-token reuse with early expiry.

    An availability optimization only: tokens live in broker memory keyed by the
    complete approved identity/authentication target, never cross the process, and
    never enter logs, exceptions, responses or accounting. It caches no grant
    authority or provider result, and a stored-credential revision change keys a
    new entry rather than reusing a fenced token.
    """

    def __init__(self, *, early_expiry_seconds: float = 60.0) -> None:
        self._early = early_expiry_seconds
        self._guard = threading.Lock()
        self._entries: dict[tuple[str, ...], _CachedToken] = {}
        self._flights: dict[tuple[str, ...], threading.Lock] = {}

    def token(self, key: tuple[str, ...], mint: Callable[[], tuple[str, float]]) -> str:
        """Return a live cached token or mint one under a per-key single-flight lock."""
        fresh = self._fresh(key)
        if fresh is not None:
            return fresh
        with self._flight(key):
            # Re-check inside the single-flight lock so only one caller mints per key.
            fresh = self._fresh(key)
            if fresh is not None:
                return fresh
            token, lifetime = mint()
            with self._guard:
                self._entries[key] = _CachedToken(token=token, expires_at=time.monotonic() + max(0.0, lifetime))
            return token

    def _fresh(self, key: tuple[str, ...]) -> str | None:
        with self._guard:
            entry = self._entries.get(key)
        if entry is not None and entry.expires_at - self._early > time.monotonic():
            return entry.token
        return None

    def _flight(self, key: tuple[str, ...]) -> threading.Lock:
        with self._guard:
            return self._flights.setdefault(key, threading.Lock())


_VERTEX_TOKENS = _AccessTokenCache()


class ProviderCredentials:
    """Short-lived impersonation/assumption, with no guest or request-selected role."""

    def __init__(self, *, credential: object = None) -> None:
        self.credential = credential

    async def headers(self, target: ProviderTarget, *, url: str, body: bytes) -> dict[str, str]:
        operation = self._stored_headers if target.authentication == "stored-credential" else self._headers
        return await _CREDENTIAL_WORK.run(partial(operation, target, url=url, body=body))

    def _stored_headers(self, target: ProviderTarget, *, url: str, body: bytes) -> dict[str, str]:
        credential = parse_source_credential(target.provider, self.credential)
        if isinstance(credential, APIKeyCredential):
            origin = {
                "anthropic-v1": "api.anthropic.com",
                "openai-v1": "api.openai.com",
                "openrouter-v1": "openrouter.ai",
            }[target.provider]
            parsed = urlsplit(url)
            if parsed.scheme != "https" or parsed.netloc != origin:
                raise ContractError("provider.target_mismatch")
            key = credential.api_key.get_secret_value()
            return {
                "content-type": JSON_MEDIA_TYPE,
                "accept-encoding": "identity",
                **(
                    {"x-api-key": key, "anthropic-version": "2023-06-01"}
                    if target.provider == "anthropic-v1"
                    else {"authorization": f"Bearer {key}"}
                ),
            }
        if isinstance(credential, GoogleKeyCredential):
            return _vertex_headers(target, stored=credential)
        return _bedrock_headers(target, url=url, body=body, stored=credential)

    @staticmethod
    def _headers(target: ProviderTarget, *, url: str, body: bytes) -> dict[str, str]:
        if target.provider == "vertex-v1":
            return _vertex_headers(target)
        if target.provider == "bedrock-v1":
            return _bedrock_headers(target, url=url, body=body)
        raise ContractError("provider.credential_unavailable")


def _vertex_headers(target: ProviderTarget, *, stored: GoogleKeyCredential | None = None) -> dict[str, str]:
    """Impersonate the approved service account, reusing a bounded cached token."""
    if stored is not None and (stored.client_email != target.principal or stored.project_id != target.project):
        raise ContractError("provider.target_mismatch")
    key = ("vertex", target.authentication, target.principal, target.project, target.credential_reference)
    token = _VERTEX_TOKENS.token(key, partial(_mint_vertex_token, target, stored))
    return {
        "authorization": f"Bearer {token}",
        "content-type": JSON_MEDIA_TYPE,
        "accept-encoding": "identity",
    }


def _mint_vertex_token(target: ProviderTarget, stored: GoogleKeyCredential | None) -> tuple[str, float]:
    """Mint one short-lived Vertex access token through a bounded private session."""
    import requests
    from google.auth import compute_engine, impersonated_credentials
    from google.auth.transport.requests import Request

    with requests.Session() as session:
        session.trust_env = False
        proxy = provider_proxy()
        if proxy:
            session.proxies = {"https": proxy}
        request = Request(session=session)

        def bounded(
            url: str,
            method: str = "GET",
            body: bytes | None = None,
            headers: Mapping[str, str] | None = None,
            **kwargs: object,
        ) -> object:
            """Bound every credential refresh HTTP call to two seconds."""
            kwargs["timeout"] = 2
            return request(url, method=method, body=body, headers=headers, **kwargs)

        if stored is None:
            credentials = impersonated_credentials.Credentials(
                source_credentials=compute_engine.Credentials(),
                target_principal=target.principal,
                target_scopes=["https://www.googleapis.com/auth/cloud-platform"],
                lifetime=300,
            )
        else:
            from google.oauth2 import service_account

            value = stored.model_dump(mode="json")
            value["private_key"] = stored.private_key.get_secret_value()
            credentials = service_account.Credentials.from_service_account_info(
                value, scopes=["https://www.googleapis.com/auth/cloud-platform"]
            )
        credentials.refresh(bounded)
    return credentials.token, _seconds_until(credentials.expiry)


def _seconds_until(expiry: datetime | None) -> float:
    """Remaining lifetime of a minted token; unknown expiry is treated as immediate."""
    if expiry is None:
        return 0.0
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=UTC)
    return (expiry - datetime.now(UTC)).total_seconds()


def _bedrock_headers(
    target: ProviderTarget, *, url: str, body: bytes, stored: AWSKeyCredential | None = None
) -> dict[str, str]:
    """Sign the exact request with a short-lived session for the approved role."""
    from botocore.auth import SigV4Auth
    from botocore.awsrequest import AWSRequest
    from botocore.credentials import Credentials

    from shared.model_access.aws_session import bounded_aws_session

    client_credentials = {}
    if stored is not None:
        client_credentials = {
            "aws_access_key_id": stored.access_key_id,
            "aws_secret_access_key": stored.secret_access_key.get_secret_value(),
            "aws_session_token": stored.session_token.get_secret_value() if stored.session_token else None,
        }
    with closing(
        bounded_aws_session(target.region, proxy=provider_proxy()).client("sts", **client_credentials)
    ) as client:
        result = client.assume_role(RoleArn=target.principal, RoleSessionName="model-broker", DurationSeconds=900)
    value = result["Credentials"]
    credentials = Credentials(value["AccessKeyId"], value["SecretAccessKey"], value["SessionToken"])
    request = AWSRequest(
        method="POST",
        url=url,
        data=body,
        headers={"content-type": JSON_MEDIA_TYPE, "accept-encoding": "identity"},
    )
    SigV4Auth(credentials, "bedrock", target.region).add_auth(request)
    return dict(request.headers.items())
