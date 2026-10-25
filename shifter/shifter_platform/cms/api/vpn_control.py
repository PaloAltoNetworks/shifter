"""Private control transport for the shared OpenVPN server pool (#2480).

Only the pool's own service account may call these endpoints. The controller
presents a Google-signed identity token for the configured audience; the email
and immutable numeric subject must both match the configured pool identity. A
logged-in user, an API token, or any other workload is refused.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import partial

from django.conf import settings
from drf_spectacular.utils import extend_schema
from rest_framework.authentication import BaseAuthentication, get_authorization_header
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from engine.services import (
    VPN_SESSION_HEARTBEAT_SECONDS,
    VPN_SESSION_LEASE_SECONDS,
    VpnSessionDenied,
    authorize_vpn_session,
    end_vpn_session,
    renew_vpn_sessions,
)

_AUTHENTICATION_FAILED = "VPN controller authentication failed"
_MAX_ASSERTION_BYTES = 16_384


@dataclass(frozen=True)
class VpnControllerPrincipal:
    """The pool identity; it has no platform user, scopes, or ambient privileges."""

    is_authenticated: bool = True


@dataclass(frozen=True)
class VpnControllerCredential:
    """Keep the identity token out of object representations and diagnostics."""

    assertion: str = field(repr=False)


def _verify(assertion: str) -> None:
    """Verify the Google identity token against the configured pool identity, or raise."""
    from google.auth.transport.requests import Request as GoogleTransport

    from shared.model_access.control_identity import verify_google_control_assertion

    audience = str(getattr(settings, "VPN_CONTROL_AUDIENCE", "") or "")
    email = str(getattr(settings, "VPN_CONTROLLER_SERVICE_ACCOUNT_EMAIL", "") or "")
    subject_id = str(getattr(settings, "VPN_CONTROLLER_SERVICE_ACCOUNT_ID", "") or "")
    if not (audience and email and subject_id):
        raise AuthenticationFailed(_AUTHENTICATION_FAILED)
    verify_google_control_assertion(
        assertion,
        audience=audience,
        expected_subject=email,
        expected_subject_id=subject_id,
        request=partial(GoogleTransport(), timeout=5),
    )


class VpnControllerAuthentication(BaseAuthentication):
    """Admit only the configured pool service account."""

    def authenticate(self, request: Request) -> tuple[VpnControllerPrincipal, VpnControllerCredential]:
        from shared.model_access import ContractError

        header = get_authorization_header(request)
        if not header or len(header) > _MAX_ASSERTION_BYTES:
            raise AuthenticationFailed(_AUTHENTICATION_FAILED)
        try:
            assertion = header.decode("ascii")
            _verify(assertion)
        except (UnicodeError, ContractError) as exc:
            raise AuthenticationFailed(_AUTHENTICATION_FAILED) from exc
        return VpnControllerPrincipal(), VpnControllerCredential(assertion)

    def authenticate_header(self, request: Request) -> str:
        """Advertise this endpoint's independently scoped bearer challenge."""
        return 'Bearer realm="vpn-control"'


class IsVpnController(BasePermission):
    """A logged-in platform administrator is still not the pool controller."""

    def has_permission(self, request: Request, view: APIView) -> bool:
        return isinstance(request.user, VpnControllerPrincipal) and isinstance(request.auth, VpnControllerCredential)


def _denied(exc: VpnSessionDenied) -> Response:
    """Return the closed refusal code; nothing else about the range is disclosed."""
    status = 400 if exc.code == "vpn.invalid_request" else 403
    return Response({"error": exc.code}, status=status)


def _body(request: Request) -> dict[str, object]:
    """Return the JSON object body or an empty mapping."""
    return request.data if isinstance(request.data, dict) else {}


class _VpnControlView(APIView):
    """Base for the pool controller endpoints: Google identity of the pool SA only."""

    authentication_classes = [VpnControllerAuthentication]
    permission_classes = [IsVpnController]


class VpnSessionAuthorizeView(_VpnControlView):
    """Authorize one connection whose certificate OpenVPN already verified."""

    @extend_schema(exclude=True)
    def post(self, request: Request) -> Response:
        body = _body(request)
        try:
            grant = authorize_vpn_session(
                common_name=body.get("common_name"),
                server=body.get("server"),
                client_id=body.get("client_id"),
                client_address=body.get("client_address", ""),
            )
        except VpnSessionDenied as exc:
            return _denied(exc)
        return Response(
            {
                "session": str(grant.session_id),
                "target": grant.target_ip,
                "ports": list(grant.ports),
                "heartbeat_seconds": VPN_SESSION_HEARTBEAT_SECONDS,
                "lease_seconds": VPN_SESSION_LEASE_SECONDS,
            },
            status=201,
        )


class VpnSessionHeartbeatView(_VpnControlView):
    """Renew a server's live sessions and return the ones it must disconnect."""

    @extend_schema(exclude=True)
    def post(self, request: Request) -> Response:
        body = _body(request)
        try:
            disconnect = renew_vpn_sessions(server=body.get("server"), session_ids=body.get("sessions"))
        except VpnSessionDenied as exc:
            return _denied(exc)
        return Response(
            {"disconnect": [str(value) for value in disconnect], "heartbeat_seconds": VPN_SESSION_HEARTBEAT_SECONDS}
        )


class VpnSessionEndView(_VpnControlView):
    """Record that one of the server's clients disconnected."""

    @extend_schema(exclude=True)
    def post(self, request: Request) -> Response:
        body = _body(request)
        try:
            end_vpn_session(server=body.get("server"), session_id=body.get("session"))
        except VpnSessionDenied as exc:
            return _denied(exc)
        return Response(status=204)
