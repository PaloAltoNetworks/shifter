"""Workload identity for private broker control; no guest credential fallback."""

from __future__ import annotations

import base64
import json
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from botocore.credentials import Credentials, ReadOnlyCredentials
    from google.auth.transport import Response
    from requests import Session

from shared.model_access import ContractError
from shared.model_access.messages import strict_json


class GoogleRequest(Protocol):
    """Bounded HTTP callback consumed by Google's token verification transport."""

    def __call__(
        self,
        url: str,
        method: str = "GET",
        body: bytes | None = None,
        headers: Mapping[str, str] | None = None,
        **kwargs: object,
    ) -> Response: ...


_STS_BODY = "Action=GetCallerIdentity&Version=2011-06-15"
_AUDIENCE_HEADER = "x-shifter-audience"


def aws_control_assertion(*, credentials: Credentials | ReadOnlyCredentials, region: str, audience: str) -> str:
    """Sign a fixed regional STS identity request and bind the control audience."""
    from botocore.auth import SigV4Auth
    from botocore.awsrequest import AWSRequest

    origin = _sts_origin(region)
    request = AWSRequest(
        method="POST",
        url=origin,
        data=_STS_BODY,
        headers={
            "Host": origin.removeprefix("https://"),
            "Content-Type": "application/x-www-form-urlencoded",
            _AUDIENCE_HEADER: audience,
        },
    )
    SigV4Auth(credentials, "sts", region).add_auth(request)
    body = json.dumps({"headers": {key.lower(): value for key, value in request.headers.items()}}).encode()
    return "AWS-STS " + base64.urlsafe_b64encode(body).decode("ascii")


def _sts_origin(region: str) -> str:
    """Resolve only an AWS regional STS endpoint from a bounded region identifier."""
    if not re.fullmatch(r"[a-z]{2}-[a-z]+-\d", region):
        raise ContractError("control.invalid_region")
    return f"https://sts.{region}.amazonaws.com"


def _validated_aws_headers(
    assertion: str,
    region: str,
    audience: str,
    origin: str,
    now: datetime | None,
) -> dict[str, str]:
    """Admit only fresh signed headers bound to this service and regional STS."""
    if not assertion.startswith("AWS-STS ") or len(assertion) > 12_000:
        raise ValueError
    value = strict_json(base64.b64decode(assertion[8:], altchars=b"-_", validate=True), limit=8192)
    headers = value["headers"]
    _validate_assertion_shape(value, headers)
    if headers.get("host") != origin.removeprefix("https://") or headers.get(_AUDIENCE_HEADER) != audience:
        raise ValueError
    if headers.get("content-type") != "application/x-www-form-urlencoded":
        raise ValueError
    _validate_signature_headers(headers, region, now)
    return headers


def _validate_assertion_shape(value: dict[str, object], headers: object) -> None:
    """Reject unknown assertion fields and header injection before signature replay."""
    allowed = {"host", "content-type", "authorization", "x-amz-date", "x-amz-security-token", _AUDIENCE_HEADER}
    if set(value) != {"headers"} or not isinstance(headers, dict) or set(headers) - allowed:
        raise ValueError
    if any(not isinstance(item, str) or "\r" in item or "\n" in item for item in headers.values()):
        raise ValueError


def _validate_signature_headers(headers: dict[str, str], region: str, now: datetime | None) -> None:
    """Require all transmitted headers to be signed and the signing time to be fresh."""
    signed = re.fullmatch(
        r"AWS4-HMAC-SHA256 Credential=[A-Z0-9]+/(\d{8})/([a-z0-9-]+)/sts/aws4_request, "
        r"SignedHeaders=([a-z0-9;-]+), Signature=[0-9a-f]{64}",
        headers["authorization"],
    )
    required = set(headers) - {"authorization"}
    if signed is None or signed.group(2) != region or set(signed.group(3).split(";")) != required:
        raise ValueError
    issued = datetime.strptime(headers["x-amz-date"], "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
    if abs(((now or datetime.now(UTC)) - issued).total_seconds()) > 60:
        raise ValueError


def verify_aws_control_assertion(
    assertion: str,
    *,
    region: str,
    audience: str,
    expected_role: str,
    session: Session,
    now: datetime | None = None,
) -> None:
    """Replay only a fixed, bounded signed STS call; never a caller URL or body."""
    from defusedxml import ElementTree

    try:
        origin = _sts_origin(region)
        headers = _validated_aws_headers(assertion, region, audience, origin, now)
        with session.post(
            origin, data=_STS_BODY, headers=headers, timeout=2, allow_redirects=False, stream=True
        ) as response:
            if response.status_code != 200:
                raise ValueError
            raw = response.raw.read(16_385, decode_content=False)
        if len(raw) > 16_384 or b"<!" in raw:
            raise ValueError
        root = ElementTree.fromstring(raw)
        arn = root.findtext(".//{https://sts.amazonaws.com/doc/2011-06-15/}Arn", default="")
        role = re.fullmatch(
            r"arn:aws:iam::(\d{12}):role/(?:[A-Za-z0-9+=,.@_-]+/)*([A-Za-z0-9+=,.@_-]+)", expected_role, flags=re.ASCII
        )
        if role is None or not re.fullmatch(
            rf"arn:aws:sts::{role.group(1)}:assumed-role/{re.escape(role.group(2))}/[A-Za-z0-9+=,.@_-]+", arn
        ):
            raise ValueError
    except Exception:
        # Never include a signed assertion, credential, upstream body or URL in
        # an auth exception. The caller exposes this closed code only.
        raise ContractError("control.unauthorized") from None


def verify_google_control_assertion(
    assertion: str, *, audience: str, expected_subject: str, expected_subject_id: str, request: GoogleRequest
) -> None:
    """Bind the verified email and immutable Google subject to applied identity."""
    from google.oauth2.id_token import verify_oauth2_token

    try:
        if (
            not assertion.startswith("Bearer ")
            or len(assertion) > 16_384
            or not re.fullmatch(r"\d{10,32}", expected_subject_id, flags=re.ASCII)
        ):
            raise ValueError
        claims = verify_oauth2_token(assertion[7:], request, audience=audience)
        if (
            claims.get("email") != expected_subject
            or claims.get("email_verified") is not True
            or claims.get("sub") != expected_subject_id
        ):
            raise ValueError
    except Exception:
        raise ContractError("control.unauthorized") from None
