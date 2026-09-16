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

from cms.services import (
    TRANSFERABLE_RESOURCE_KINDS,
    OffboardingAuditContext,
    OwnershipTransferSummary,
    transfer_user_ownership,
)
from config.organizer_authority import grant_local_organizer
from management.services import get_admin_user, safe_user_profile
from shared.api.errors import api_error_response
from shared.api.permissions import IsStaffSession, require_model_permission
from shared.api_tokens.authentication import ApiTokenAuthentication
from shared.audit import (
    AuditAction,
    AuditEntityType,
    AuditEvent,
    audit_log,
    get_actor_from_request,
    get_client_ip,
    get_request_id,
)
from shared.auth import is_ctf_organizer

if TYPE_CHECKING:
    from django.contrib.auth.models import User
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


class TransferOwnershipRequestSerializer(serializers.Serializer):
    """Explicit request body for an offboarding ownership transfer.

    ``resource_kinds`` is a closed allowlist; there is no wildcard or
    "all resources" interpretation (PLAT-236, #1943).
    """

    replacement_user_id = serializers.IntegerField(min_value=1)
    resource_kinds = serializers.ListField(
        child=serializers.ChoiceField(choices=list(TRANSFERABLE_RESOURCE_KINDS)),
        allow_empty=False,
    )


class TransferOwnershipResultSerializer(serializers.Serializer):
    """Bounded, secret-free summary of an offboarding ownership transfer."""

    source_user_id = serializers.IntegerField()
    replacement_user_id = serializers.IntegerField()
    ranges_reassigned = serializers.IntegerField()
    ranges_blocked = serializers.IntegerField()
    workspaces_transferred = serializers.IntegerField()
    workspaces_already_owned = serializers.IntegerField()
    workspaces_blocked_no_membership = serializers.IntegerField()


class _TransferValidationError(Exception):
    """A rejected transfer request carrying a stable code, message, and status."""

    def __init__(self, code: str, message: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def _resolve_transfer_targets(request: Request, pk: int, replacement_id: int) -> tuple[User, User]:
    """Resolve and authorize the source + replacement, or raise _TransferValidationError.

    Offboarding ownership transfer is a root-level action; it requires a superuser
    session so a non-superuser holding ``auth.change_user`` cannot seize ranges or
    workspaces (issue #1943 review F5).
    """
    if not request.user.is_superuser:
        raise _TransferValidationError("superuser_required", "Ownership transfer requires a superuser account.", 403)
    source = get_admin_user(pk)
    if source is None:
        raise _TransferValidationError("not_found", "User not found.", 404)
    if replacement_id == source.pk:
        raise _TransferValidationError(
            "same_user", "The replacement account must differ from the departing account.", 400
        )
    replacement = get_admin_user(replacement_id)
    if replacement is None:
        raise _TransferValidationError("replacement_not_found", "Replacement account not found.", 400)
    replacement_profile = safe_user_profile(replacement)
    if not replacement.is_active or (replacement_profile and replacement_profile.deleted_at is not None):
        raise _TransferValidationError(
            "replacement_inactive", "The replacement account must be active to receive ownership.", 400
        )
    return source, replacement


class AdministerTransferOwnershipView(APIView):
    """Transfer a departing user's owned resources to a replacement. Superuser-only.

    A single bounded composition-root command (never sequential SPA calls): it
    resolves and authorizes both accounts, then delegates to
    ``cms.services.transfer_user_ownership`` (the only layer permitted to reach
    both the range and workspace domains). Both transfer kinds are the
    ADR-046-R13 platform-administrator offboarding override.

    This command requires a **superuser** session, not merely ``auth.change_user``
    (issue #1943 review F5): a superuser already holds cross-tenant/root authority,
    so transferring ranges and workspaces during offboarding is not an escalation.
    Gating on ``auth.change_user`` alone would let a staff user who is merely a
    member of another tenant's workspace acquire ranges they could not otherwise
    administer. Range reassignment reuses the existing CMS/Engine authority and
    refuses live-VPN ranges; workspace transfer requires the replacement to be an
    existing member. It never removes memberships, transfers credentials/agents,
    or rewrites provenance.
    """

    authentication_classes = [ApiTokenAuthentication, SessionAuthentication]
    permission_classes = [IsStaffSession, require_model_permission("auth.change_user")]

    @extend_schema(
        request=TransferOwnershipRequestSerializer,
        responses=TransferOwnershipResultSerializer,
        operation_id="api_v1_administer_users_transfer_ownership",
    )
    def post(self, request: Request, pk: int) -> Response:
        serializer = TransferOwnershipRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            source, replacement = _resolve_transfer_targets(
                request, pk, serializer.validated_data["replacement_user_id"]
            )
        except _TransferValidationError as exc:
            return api_error_response(code=exc.code, message=exc.message, status_code=exc.status_code, request=request)

        kinds = serializer.validated_data["resource_kinds"]
        actor_type, actor_id = get_actor_from_request(request)
        audit = OffboardingAuditContext(
            actor_type=actor_type,
            actor_id=actor_id,
            request_id=get_request_id(request),
            source_ip=get_client_ip(request),
            user_agent=request.META.get("HTTP_USER_AGENT", "")[:255],
        )

        summary: OwnershipTransferSummary = transfer_user_ownership(source, replacement, kinds=kinds, audit=audit)

        # Per-workspace and per-range transitions are strict-audited in their
        # domains; this bounded, secret-free summary records the administrator's
        # offboarding action itself (non-strict: the transfers already committed).
        audit_log(
            AuditEvent(
                entity_type=AuditEntityType.USER,
                entity_id=source.pk,
                action=AuditAction.UPDATE,
                actor_type=actor_type,
                actor_id=actor_id,
                new_state={
                    "replacement_user_id": replacement.pk,
                    "resource_kinds": list(kinds),
                    "ranges_reassigned": summary.ranges_reassigned,
                    "ranges_blocked": summary.ranges_blocked,
                    "workspaces_transferred": summary.workspaces_transferred,
                    "workspaces_blocked_no_membership": summary.workspaces_blocked_no_membership,
                },
                context="user offboarding ownership transfer",
                request_id=audit.request_id,
                source_ip=audit.source_ip,
                user_agent=audit.user_agent,
            ),
        )

        payload = {
            "source_user_id": source.pk,
            "replacement_user_id": replacement.pk,
            "ranges_reassigned": summary.ranges_reassigned,
            "ranges_blocked": summary.ranges_blocked,
            "workspaces_transferred": summary.workspaces_transferred,
            "workspaces_already_owned": summary.workspaces_already_owned,
            "workspaces_blocked_no_membership": summary.workspaces_blocked_no_membership,
        }
        return Response(TransferOwnershipResultSerializer(payload).data)
