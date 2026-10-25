"""Prepared cross-domain administration adapters; S8 alone mounts these views."""

from uuid import UUID

from django.conf import settings
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.request import Request
from rest_framework.response import Response

import management.services as identities
from cms.services import CMSError, policy_transfer_user_ownership
from config.api_administer import TransferOwnershipRequestSerializer, TransferOwnershipResultSerializer
from management.api.policy_views import PolicyAdminView
from management.services import require_principal_administration
from shared.api.closed_serializer import ClosedSerializer
from shared.api.errors import api_error_response
from shared.api.principals import authenticated_credential
from shared.audit import request_audit
from shared.authorization import PolicyEffect, RelationshipSubject, TargetRef, configured_authorization_provider
from workspaces.api.serializers import AuthorizationMutationSerializer
from workspaces.services import (
    AccountScopeError,
    AuthorizationMutationConflict,
    PolicyMutationRequest,
    apply_policy_mutation,
    event_placement_scope,
)


class PolicyTransferOwnershipCommand(TransferOwnershipRequestSerializer, ClosedSerializer):
    """Keep the existing closed resource-kind selection, rejecting unknown fields."""


class PolicyTransferOwnershipResult(TransferOwnershipResultSerializer):
    """Prepared summary counts all resource rejections without guessing their cause."""

    workspaces_blocked = serializers.IntegerField(read_only=True)


class PolicyAdministerTransferOwnershipView(PolicyAdminView):
    """Root identity authority composes independently authorized resource effects."""

    @extend_schema(request=PolicyTransferOwnershipCommand, responses=PolicyTransferOwnershipResult)
    def post(self, request: Request, pk: int) -> Response:
        command = PolicyTransferOwnershipCommand(data=request.data)
        command.is_valid(raise_exception=True)
        actor = authenticated_credential(request)
        provider = configured_authorization_provider()
        require_principal_administration(actor, provider)
        source = identities.get_admin_user(pk)
        destination = identities.get_admin_user(command.validated_data["replacement_user_id"])
        if source is None or destination is None:
            raise PermissionError("Ownership transfer denied")
        try:
            result = policy_transfer_user_ownership(
                actor,
                provider,
                source,
                destination,
                kinds=command.validated_data["resource_kinds"],
                audit=request_audit(request, credential=actor),
            )
        except (CMSError, AccountScopeError, identities.PrincipalConflictError, ValueError):
            return api_error_response(
                code="ownership_transfer_denied", message="Ownership transfer denied", status_code=403, request=request
            )
        payload = {
            "source_user_id": pk,
            "replacement_user_id": destination.pk,
            "ranges_reassigned": result.ranges_reassigned,
            "ranges_blocked": result.ranges_blocked,
            "workspaces_transferred": result.workspaces_transferred,
            "workspaces_already_owned": result.workspaces_already_owned,
            "workspaces_blocked_no_membership": result.workspaces_blocked_no_membership,
            "workspaces_blocked": result.workspaces_blocked,
        }
        return Response(PolicyTransferOwnershipResult(payload).data)


class ScopedOrganizerCommand(ClosedSerializer):
    """An organizer receives a scoped create-event policy, never a Django group grant."""

    target_type = serializers.ChoiceField(choices=("account", "organization", "workspace"))
    target_uuid = serializers.UUIDField()
    idempotency_key = serializers.CharField(max_length=100, allow_blank=False)


class PolicyAdministerGrantOrganizerView(PolicyAdminView):
    """Replace global role writes with the existing bounded delegation journal."""

    def handle_exception(self, exc: Exception) -> Response:
        if isinstance(
            exc, (AccountScopeError, AuthorizationMutationConflict, identities.PrincipalConflictError, ValueError)
        ):
            return api_error_response(
                code="administration_denied", message="Administration denied", status_code=403, request=self.request
            )
        return super().handle_exception(exc)

    @extend_schema(request=ScopedOrganizerCommand, responses={202: AuthorizationMutationSerializer})
    def post(self, request: Request, pk: int) -> Response:
        command = ScopedOrganizerCommand(data=request.data)
        command.is_valid(raise_exception=True)
        actor = authenticated_credential(request)
        provider = configured_authorization_provider()
        require_principal_administration(actor, provider)
        user = identities.get_admin_user(pk)
        if user is None:
            raise PermissionError("Administration denied")
        values = command.validated_data
        target_uuid: UUID = values["target_uuid"]
        kind = values["target_type"]
        scope = event_placement_scope(kind, target_uuid)
        target = TargetRef(kind, target_uuid)
        result = apply_policy_mutation(
            PolicyMutationRequest(
                actor=actor.principal,
                credential=actor.ceiling,
                subject=RelationshipSubject("principal", identities.principal_for_user(user).uuid),
                action=f"{kind}.create_event",
                target=target,
                scope=scope,
                effect=PolicyEffect.GRANT,
                idempotency_key=values["idempotency_key"],
                model_id=settings.OPENFGA_MODEL_ID,
                audit=request_audit(request, credential=actor),
            ),
            provider,
        )
        return Response(AuthorizationMutationSerializer(result).data, status=202)
