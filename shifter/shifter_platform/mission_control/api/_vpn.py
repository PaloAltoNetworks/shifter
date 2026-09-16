"""Mission Control OpenVPN profile delivery view, split from ranges (python:S104)."""

from __future__ import annotations

from django.contrib.auth.models import User
from django.http import HttpResponse
from django.utils.cache import patch_vary_headers
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response

from cms.services import get_mission_control_openvpn_profile
from mission_control.api._base import MissionControlAPIView, _vpn_profile_read_permission
from mission_control.api.permissions import HasMissionControlActor
from shared.api.permissions import IsAuthenticatedSessionOrApiToken
from shared.api.schema import ApiErrorSerializer
from shared.remote_access import OPENVPN_PROFILE_MEDIA_TYPE, OpenVpnProfile

_VPN_PROFILE_FILENAME = "shifter-range.ovpn"


def _credential_delivery_error(view: MissionControlAPIView, actor: User) -> Response | None:
    """Return a fail-closed delivery response, or None when delivery may proceed."""
    from shared.credential_delivery import credential_delivery_allowed

    try:
        allowed = credential_delivery_allowed(actor.pk)
    except Exception:
        response = view.error_response(
            code="vpn_profile_unavailable",
            message="VPN profile is unavailable.",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    else:
        response = None
        if not allowed:
            response = view.error_response(
                code="throttled",
                message="Too many VPN profile requests. Try again later.",
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            )
            response["Retry-After"] = "3600"
    return response


def _mission_control_profile_result(
    view: MissionControlAPIView,
    actor: User,
) -> tuple[OpenVpnProfile, int] | Response:
    """Resolve a profile or translate the CMS failure into its API response."""
    from cms.services import OpenVpnProfileConflict, OpenVpnProfileNotFound, OpenVpnProfileUnavailable

    result: tuple[OpenVpnProfile, int] | Response
    try:
        result = get_mission_control_openvpn_profile(actor)
    except OpenVpnProfileNotFound:
        result = view.not_found("VPN profile is not available.")
    except OpenVpnProfileConflict:
        result = view.error_response(
            code="vpn_not_ready",
            message="VPN profile is not ready.",
            status_code=status.HTTP_409_CONFLICT,
        )
    except OpenVpnProfileUnavailable:
        result = view.error_response(
            code="vpn_profile_unavailable",
            message="VPN profile is unavailable.",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    return result


def _vpn_profile_download_response(actor: User, profile: OpenVpnProfile, range_instance_id: int) -> HttpResponse:
    """Audit and build the non-cacheable OpenVPN credential response."""
    from shared.credential_delivery import audit_openvpn_profile_download

    audit_openvpn_profile_download(
        actor_id=actor.pk,
        range_instance_id=range_instance_id,
        generation=profile.generation,
        profile_version=profile.profile_version,
        product="mission_control",
    )
    response = HttpResponse(profile.content, content_type=OPENVPN_PROFILE_MEDIA_TYPE)
    response["Content-Disposition"] = f'attachment; filename="{_VPN_PROFILE_FILENAME}"'
    response["Cache-Control"] = "private, no-store"
    response["Content-Length"] = str(len(profile.content))
    patch_vary_headers(response, ("Cookie", "Authorization"))
    return response


class MissionControlVpnProfileView(MissionControlAPIView):
    """Deliver the current Mission Control range's generation-bound OpenVPN profile."""

    permission_classes = [
        IsAuthenticatedSessionOrApiToken,
        HasMissionControlActor,
        _vpn_profile_read_permission(),
    ]

    @extend_schema(
        request=None,
        responses={
            (200, OPENVPN_PROFILE_MEDIA_TYPE): OpenApiTypes.BINARY,
            400: ApiErrorSerializer,
            404: ApiErrorSerializer,
            409: ApiErrorSerializer,
            429: ApiErrorSerializer,
            503: ApiErrorSerializer,
        },
    )
    def post(self, request: Request) -> HttpResponse | Response:
        if request.body or request.query_params:
            response: HttpResponse | Response = self.error_response(
                code="invalid",
                message="VPN profile requests must not include a body or query parameters.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        else:
            actor = self.actor_user()
            delivery_error = _credential_delivery_error(self, actor)
            if delivery_error is not None:
                response = delivery_error
            else:
                profile_result = _mission_control_profile_result(self, actor)
                if isinstance(profile_result, Response):
                    response = profile_result
                else:
                    profile, range_instance_id = profile_result
                    response = _vpn_profile_download_response(actor, profile, range_instance_id)
        return response
