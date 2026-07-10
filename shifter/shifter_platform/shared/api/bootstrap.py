"""Session bootstrap endpoint for the SPA (#1300 / #1302).

A client-rendered SPA cannot read Django context processors, so it loads the
authenticated principal, effective permission flags, and feature flags once
from this endpoint after authentication (replacing
``shared.context_processors.user_permissions`` for the browser client).

The permission flags are **advisory UI state only**. Every mutation and read
still passes the authoritative DRF permission classes on the resource
endpoints; a wrong or stale flag here never widens access. The payload contains
no secrets, tokens, or cookies.
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

from risk_register.access import principal_has_risk_register_access
from shared.api.permissions import IsAuthenticatedSessionOrApiToken
from shared.api_tokens.authentication import ApiTokenAuthentication
from shared.api_tokens.models import ApiToken
from shared.auth import can_edit_cms_authoring

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
    """Advisory authorization flags mirroring the template context processor."""

    can_access_risk_register = serializers.BooleanField()
    can_access_threat_research = serializers.BooleanField()


class BootstrapFeatureFlagsSerializer(serializers.Serializer):
    """Server-owned feature flags surfaced to the SPA (no secret values)."""

    risk_register_spa = serializers.BooleanField()


class BootstrapSerializer(serializers.Serializer):
    """Top-level SPA bootstrap payload."""

    principal = BootstrapPrincipalSerializer()
    permissions = BootstrapPermissionsSerializer()
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


class BootstrapView(APIView):
    """Return the SPA session bootstrap payload for the current principal."""

    authentication_classes = [ApiTokenAuthentication, SessionAuthentication]
    permission_classes = [IsAuthenticatedSessionOrApiToken]

    @extend_schema(responses=BootstrapSerializer, operation_id="api_v1_bootstrap_retrieve")
    def get(self, request: Request) -> Response:
        auth = getattr(request, "auth", None)
        if isinstance(auth, ApiToken):
            principal, can_threat = _principal_from_token(auth)
        else:
            principal, can_threat = _principal_from_session(request.user)

        payload = {
            "principal": principal,
            "permissions": {
                "can_access_risk_register": principal_has_risk_register_access(request),
                "can_access_threat_research": can_threat,
            },
            "feature_flags": {
                "risk_register_spa": bool(getattr(settings, "RISK_REGISTER_SPA_ENABLED", False)),
            },
        }
        return Response(BootstrapSerializer(payload).data)
