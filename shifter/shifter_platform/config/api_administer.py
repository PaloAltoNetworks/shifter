"""Composition-root Administer endpoints that span domains (#1373).

The one Administer operation that needs authority beyond the ``management``
domain — the local CTF-Organizer grant, which lives in
``config.organizer_authority`` — is served here rather than in ``management.api``
so no feature app imports the composition root (ADR-001). Single-domain user
operations live in ``management.api``; this view is registered by
``config.api_urls`` at a sibling ``/api/v1/administer/`` path, ahead of the
``management.api`` include so its specific route matches first.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.authentication import SessionAuthentication
from rest_framework.response import Response
from rest_framework.views import APIView

from config.organizer_authority import grant_local_organizer
from management.services import get_admin_user, safe_user_profile
from shared.api.errors import api_error_response
from shared.api.permissions import IsStaffSession, require_model_permission
from shared.api_tokens.authentication import ApiTokenAuthentication
from shared.auth import is_ctf_organizer

if TYPE_CHECKING:
    from rest_framework.request import Request

# Recorded as the audit ``source`` so a local grant made through the Administer
# API is distinguishable from provider reconciliation and dev-login grants.
_LOCAL_ORGANIZER_SOURCE = "administer_api"


class OrganizerGrantResultSerializer(serializers.Serializer):
    """Minimal confirmation payload for a local-organizer grant."""

    id = serializers.IntegerField()
    is_ctf_organizer = serializers.BooleanField()
    organizer_grant_source = serializers.CharField(allow_blank=True)


class AdministerGrantOrganizerView(APIView):
    """Grant local CTF Organizer to a user (grant-only). Requires ``auth.change_user``.

    Additive and audited with ``local`` provenance by
    ``config.organizer_authority`` (its own strict ROLE_SYNC audit), so provider
    reconciliation never auto-revokes it. Local revocation has no complete
    service contract and is intentionally not offered here.
    """

    # Bearer-first, fail-closed chain (ADR-029 / #1373 preflight): a valid platform
    # token reaches IsStaffSession and is rejected; an invalid or revoked bearer
    # raises before session fallback and never falls through to the session.
    authentication_classes = [ApiTokenAuthentication, SessionAuthentication]
    permission_classes = [IsStaffSession, require_model_permission("auth.change_user")]

    @extend_schema(
        request=None,
        responses=OrganizerGrantResultSerializer,
        operation_id="api_v1_administer_users_grant_organizer",
    )
    def post(self, request: Request, pk: int) -> Response:
        user = get_admin_user(pk)
        if user is None:
            return api_error_response(code="not_found", message="User not found.", status_code=404, request=request)

        grant_local_organizer(user, source=_LOCAL_ORGANIZER_SOURCE, request=request._request)

        # Re-resolve so the response reflects committed group membership without a
        # stale per-instance group-name memo (see shared.auth.get_user_group_names).
        refreshed = get_admin_user(pk)
        profile = safe_user_profile(refreshed) if refreshed is not None else None
        payload = {
            "id": pk,
            "is_ctf_organizer": bool(refreshed is not None and is_ctf_organizer(refreshed)),
            "organizer_grant_source": profile.organizer_grant_source if profile else "",
        }
        return Response(OrganizerGrantResultSerializer(payload).data)
