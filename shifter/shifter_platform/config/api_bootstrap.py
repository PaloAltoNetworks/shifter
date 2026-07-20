"""Session bootstrap endpoint for the SPA (#1300 / #1302 / #1369).

A client-rendered SPA cannot read Django context processors, so it loads the
authenticated principal, effective permission flags, feature flags, and UX mode
eligibility once from this endpoint after authentication (replacing
``config.context_processors.user_permissions`` for the browser client).

This is cross-domain composition (it needs the risk-register access policy), so
it lives at the ``config`` composition root and consumes the public
``risk_register.services`` facade rather than importing the risk-register domain
directly (ADR-001, #1523). It was moved here from ``shared`` so the contracts
layer no longer imports a feature domain.

The permission flags and mode eligibility are **advisory UI state only**. Every
mutation and read still passes the authoritative DRF permission classes on the
resource endpoints; a wrong or stale flag here never widens access. Mode is a
UX frame, not an authorization fact. The payload contains no secrets, tokens,
cookies, or user-entered content.

Active range/event summaries are cross-app composition and live in the
composition-root dashboard summary read (``config.api_dashboard``) rather than
here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.conf import settings
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.authentication import SessionAuthentication
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from risk_register.services import principal_has_risk_register_access
from shared.api.permissions import IsAuthenticatedSessionOrApiToken
from shared.api_tokens.authentication import ApiTokenAuthentication
from shared.api_tokens.models import ApiToken
from shared.auth import (
    can_edit_cms_authoring,
    is_ctf_organizer,
    is_ctf_participant,
    is_ctf_participant_only,
)

if TYPE_CHECKING:
    from django.contrib.auth.models import User


class BootstrapPrincipalSerializer(serializers.Serializer):
    """Authenticated principal summary for the SPA shell."""

    id = serializers.IntegerField(allow_null=True)
    username = serializers.CharField(allow_blank=True)
    display_name = serializers.CharField(allow_blank=True)
    is_authenticated = serializers.BooleanField()
    is_staff = serializers.BooleanField()
    is_superuser = serializers.BooleanField()


class BootstrapPermissionsSerializer(serializers.Serializer):
    """Advisory authorization flags mirroring the template context processors."""

    can_access_risk_register = serializers.BooleanField()
    can_access_threat_research = serializers.BooleanField()
    is_ctf_organizer = serializers.BooleanField()
    is_ctf_participant = serializers.BooleanField()
    # Administer user-administration advisory capabilities (#1373). Mirror the
    # Django model permissions the Administer API enforces; rendering hints only,
    # the endpoints repeat the authoritative check. Always False for token
    # principals (management endpoints are session-only).
    can_view_users = serializers.BooleanField()
    can_change_users = serializers.BooleanField()
    can_delete_users = serializers.BooleanField()


class BootstrapModesSerializer(serializers.Serializer):
    """UX mode eligibility (participant/operator). Not an authorization fact."""

    participant = serializers.BooleanField()
    operator = serializers.BooleanField()
    default = serializers.ChoiceField(choices=["participant", "operator"])


class BootstrapFeatureFlagsSerializer(serializers.Serializer):
    """Server-owned feature flags surfaced to the SPA (no secret values)."""

    risk_register_spa = serializers.BooleanField()
    platform_spa = serializers.BooleanField()
    mission_control_spa = serializers.BooleanField()
    scenario_editor_spa = serializers.BooleanField()
    # CTF workspace SPA (#1372): gates the in-SPA CTF participant workspace nav
    # entries. Mirrors CTF_WORKSPACE_SPA_ENABLED (advisory only; the /api/v1/ctf/
    # endpoints remain the authority).
    ctf_workspace_spa = serializers.BooleanField()
    # ACES native provisioning (#1566): gates the in-SPA ACES image registry
    # management surface. Mirrors SHIFTER_ACES_NATIVE_PROVISIONING, so the nav
    # entry only shows when the whole native path is enabled (advisory only;
    # the /api/v1/cms/aces-image-mappings/ endpoints remain the authority).
    aces_native_provisioning = serializers.BooleanField()
    # Administer workspace SPA rollout (#1373): gates the in-SPA Administer nav
    # entries and route visibility. Mirrors ADMINISTER_SPA_ENABLED; advisory
    # only, the /api/v1/administer/ endpoints remain the authority.
    administer_spa = serializers.BooleanField()


class BootstrapSerializer(serializers.Serializer):
    """Top-level SPA bootstrap payload."""

    principal = BootstrapPrincipalSerializer()
    permissions = BootstrapPermissionsSerializer()
    modes = BootstrapModesSerializer()
    feature_flags = BootstrapFeatureFlagsSerializer()


def _principal_from_token(token: ApiToken) -> tuple[dict[str, object], bool]:
    """Build the principal block and CMS-authoring flag for a token request."""
    owner = getattr(token, "created_by", None)
    if owner is None:
        return (
            {
                "id": None,
                "username": token.name,
                "display_name": token.name,
                "is_authenticated": True,
                "is_staff": False,
                "is_superuser": False,
            },
            False,
        )
    return (
        {
            "id": owner.id,
            "username": owner.get_username(),
            "display_name": owner.get_full_name() or owner.email or owner.get_username(),
            "is_authenticated": True,
            "is_staff": bool(owner.is_staff),
            "is_superuser": bool(owner.is_superuser),
        },
        can_edit_cms_authoring(owner),
    )


def _principal_from_session(user: User) -> tuple[dict[str, object], bool]:
    """Build the principal block and CMS-authoring flag for a session request."""
    return (
        {
            "id": user.id,
            "username": user.get_username(),
            "display_name": user.get_full_name() or user.email or user.get_username(),
            "is_authenticated": True,
            "is_staff": bool(user.is_staff),
            "is_superuser": bool(user.is_superuser),
        },
        can_edit_cms_authoring(user),
    )


def _modes_for_user(user: User | None) -> dict[str, object]:
    """Compute UX mode eligibility for a session user (advisory, not authz).

    Participant mode is available to CTF participants; operator mode to anyone
    who is not a CTF-participant-only account (organizers, staff, threat
    research, and risk-register operators). The default is operator unless the
    principal is participant-only. Token principals are programmatic and default
    to operator with no participant frame.
    """
    if user is None:
        return {"participant": False, "operator": True, "default": "operator"}
    participant = is_ctf_participant(user)
    operator = not is_ctf_participant_only(user)
    return {
        "participant": participant,
        "operator": operator,
        "default": "operator" if operator else "participant",
    }


class BootstrapView(APIView):
    """Return the SPA session bootstrap payload for the current principal."""

    authentication_classes = [ApiTokenAuthentication, SessionAuthentication]
    permission_classes = [IsAuthenticatedSessionOrApiToken]

    @extend_schema(responses=BootstrapSerializer, operation_id="api_v1_bootstrap_retrieve")
    def get(self, request: Request) -> Response:
        auth = getattr(request, "auth", None)
        if isinstance(auth, ApiToken):
            principal, can_threat = _principal_from_token(auth)
            session_user = None
        else:
            session_user = request.user
            principal, can_threat = _principal_from_session(session_user)

        payload = {
            "principal": principal,
            "permissions": {
                "can_access_risk_register": principal_has_risk_register_access(request),
                "can_access_threat_research": can_threat,
                "is_ctf_organizer": bool(session_user is not None and is_ctf_organizer(session_user)),
                "is_ctf_participant": bool(session_user is not None and is_ctf_participant(session_user)),
                "can_view_users": bool(session_user is not None and session_user.has_perm("auth.view_user")),
                "can_change_users": bool(session_user is not None and session_user.has_perm("auth.change_user")),
                "can_delete_users": bool(session_user is not None and session_user.has_perm("auth.delete_user")),
            },
            "modes": _modes_for_user(session_user),
            "feature_flags": {
                "risk_register_spa": bool(getattr(settings, "RISK_REGISTER_SPA_ENABLED", False)),
                "platform_spa": bool(getattr(settings, "PLATFORM_SPA_ENABLED", False)),
                "mission_control_spa": bool(getattr(settings, "MISSION_CONTROL_SPA_ENABLED", False)),
                "scenario_editor_spa": bool(getattr(settings, "SCENARIO_EDITOR_SPA_ENABLED", False)),
                "ctf_workspace_spa": bool(getattr(settings, "CTF_WORKSPACE_SPA_ENABLED", False)),
                "aces_native_provisioning": bool(getattr(settings, "ACES_NATIVE_PROVISIONING_ENABLED", False)),
                "administer_spa": bool(getattr(settings, "ADMINISTER_SPA_ENABLED", False)),
            },
        }
        return Response(BootstrapSerializer(payload).data)
