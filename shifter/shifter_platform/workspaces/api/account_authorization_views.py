"""S8 account and organization authorization adapters, not mounted before cutover."""

from __future__ import annotations

from typing import Any, Literal, cast
from uuid import UUID

from django.conf import settings
from drf_spectacular.utils import extend_schema
from rest_framework.request import Request
from rest_framework.response import Response

from shared.api.principals import authenticated_credential
from shared.audit import request_audit
from shared.authorization import (
    AdministrativeRoleChange,
    AuthorizationProvider,
    AuthorizationProviderBindingError,
    GroupMembershipChange,
    PolicyEffect,
    RelationshipSubject,
    RoleAssignmentChange,
    TargetRef,
    configured_authorization_provider,
)
from shared.credentials import CredentialContext
from shared.identity_scope import ResourceScope
from shared.principal_port import PrincipalResolutionError
from workspaces import services
from workspaces.api.authorization_views import AuthorizationAPIError, _AuthorizationAPIView
from workspaces.api.serializers import (
    AuthorizationMetadataSerializer,
    AuthorizationMutationSerializer,
    AuthorizationOperationSerializer,
    ClosedCommandSerializer,
    CreateAuthorizationMetadataSerializer,
    DirectActionAssignmentMutationSerializer,
    NativeMembershipMutationSerializer,
    PolicyActionMutationSerializer,
    PredefinedRoleMutationSerializer,
    RoleAssignmentMutationSerializer,
)


def _target_ref(target_type: str, target_uuid: UUID | None) -> TargetRef:
    """Accept only the two prepared customer authorization scopes."""
    if target_type in {"account", "organization", "workspace"}:
        return TargetRef(cast(Literal["account", "organization", "workspace"], target_type), target_uuid)
    if target_type == "installation" and target_uuid is None:
        return TargetRef("installation")
    raise AuthorizationAPIError("authorization_denied", 403)


def _operation_context(
    request: Request, target_type: str, target_uuid: UUID, account_uuid: UUID | None
) -> tuple[CredentialContext, ResourceScope, AuthorizationProvider]:
    """Standalone recovery derives the parent; operation commands reauthorize its effect."""
    if target_type == "organization" and account_uuid is None:
        try:
            account_uuid = services.hierarchy_target_scope(target_type, target_uuid).account_uuid
        except (ValueError, services.AccountScopeError):
            raise AuthorizationAPIError("authorization_denied", 403) from None
    return _context(request, target_type, target_uuid, account_uuid)


def _context(
    request: Request, target_type: str, target_uuid: UUID, account_uuid: UUID | None
) -> tuple[CredentialContext, ResourceScope, AuthorizationProvider]:
    """Resolve exact SQL ancestry and reject a path naming a different parent."""
    if target_type not in {"installation", "account", "organization", "workspace"}:
        raise AuthorizationAPIError("authorization_denied", 403)
    try:
        credential = authenticated_credential(request)
        scope = (
            ResourceScope("installation")
            if target_type == "installation"
            else services.hierarchy_target_scope(target_type, target_uuid)
        )
        if account_uuid is not None and scope.account_uuid != account_uuid:
            raise AuthorizationAPIError("authorization_denied", 403)
        if target_type == "organization" and account_uuid is None:
            raise AuthorizationAPIError("authorization_denied", 403)
        provider = configured_authorization_provider()
    except (ValueError, PrincipalResolutionError, services.AccountScopeError):
        raise AuthorizationAPIError("authorization_denied", 403) from None
    except AuthorizationProviderBindingError:
        raise AuthorizationAPIError("authorization_unavailable", 503) from None
    return credential, scope, provider


def _native_result(
    request: Request,
    target_type: str,
    target_uuid: UUID,
    account_uuid: UUID | None,
    change: GroupMembershipChange | RoleAssignmentChange | AdministrativeRoleChange,
    key: str,
) -> Response:
    """Journal one native relationship with the resolved scope and caller."""
    credential, scope, provider = _context(request, target_type, target_uuid, account_uuid)
    mutation = services.NativeRelationshipMutationRequest(
        actor=credential.principal,
        credential=credential.ceiling,
        change=change,
        scope=scope,
        idempotency_key=key,
        model_id=settings.OPENFGA_MODEL_ID,
        audit=request_audit(request, credential=credential),
    )
    result = services.apply_native_relationship_mutation(mutation, provider)
    return Response(AuthorizationMutationSerializer(result).data, status=202)


def _action_result(
    request: Request,
    target_type: str,
    target_uuid: UUID,
    account_uuid: UUID | None,
    subject: RelationshipSubject,
    data: dict[str, Any],
) -> Response:
    """Journal one action assignment under exact account ancestry."""
    credential, scope, provider = _context(request, target_type, target_uuid, account_uuid)
    mutation = services.PolicyMutationRequest(
        actor=credential.principal,
        credential=credential.ceiling,
        subject=subject,
        action=data["action"],
        target=_target_ref(target_type, target_uuid),
        scope=scope,
        effect=PolicyEffect(data["effect"]),
        idempotency_key=data["idempotency_key"],
        model_id=settings.OPENFGA_MODEL_ID,
        audit=request_audit(request, credential=credential),
    )
    result = services.apply_policy_mutation(mutation, provider)
    return Response(AuthorizationMutationSerializer(result).data, status=202)


class ScopedAuthorizationGroupCollectionView(_AuthorizationAPIView):
    """List or create display metadata at an exact account or organization."""

    @extend_schema(responses={200: AuthorizationMetadataSerializer(many=True)})
    def get(self, request: Request, target_type: str, target_uuid: UUID, account_uuid: UUID | None = None) -> Response:
        actor, scope, provider = _context(request, target_type, target_uuid, account_uuid)
        items = services.list_authorization_groups(actor.principal, actor.ceiling, scope, provider)
        return Response(AuthorizationMetadataSerializer(items, many=True).data)

    @extend_schema(request=CreateAuthorizationMetadataSerializer, responses={201: AuthorizationMetadataSerializer})
    def post(self, request: Request, target_type: str, target_uuid: UUID, account_uuid: UUID | None = None) -> Response:
        command = CreateAuthorizationMetadataSerializer(data=request.data)
        command.is_valid(raise_exception=True)
        actor, scope, provider = _context(request, target_type, target_uuid, account_uuid)
        item = services.create_authorization_group(
            actor.principal,
            actor.ceiling,
            scope,
            provider,
            audit=request_audit(request, credential=actor),
            **command.validated_data,
        )
        return Response(AuthorizationMetadataSerializer(item).data, status=201)


class ScopedAuthorizationPolicyCollectionView(_AuthorizationAPIView):
    """List or create scoped display-only policy identities."""

    @extend_schema(responses={200: AuthorizationMetadataSerializer(many=True)})
    def get(self, request: Request, target_type: str, target_uuid: UUID, account_uuid: UUID | None = None) -> Response:
        actor, scope, provider = _context(request, target_type, target_uuid, account_uuid)
        items = services.list_authorization_policies(actor.principal, actor.ceiling, scope, provider)
        return Response(AuthorizationMetadataSerializer(items, many=True).data)

    @extend_schema(request=CreateAuthorizationMetadataSerializer, responses={201: AuthorizationMetadataSerializer})
    def post(self, request: Request, target_type: str, target_uuid: UUID, account_uuid: UUID | None = None) -> Response:
        command = CreateAuthorizationMetadataSerializer(data=request.data)
        command.is_valid(raise_exception=True)
        actor, scope, provider = _context(request, target_type, target_uuid, account_uuid)
        item = services.create_authorization_policy(
            actor.principal,
            actor.ceiling,
            scope,
            provider,
            audit=request_audit(request, credential=actor),
            **command.validated_data,
        )
        return Response(AuthorizationMetadataSerializer(item).data, status=201)


class ScopedAuthorizationGroupMembershipView(_AuthorizationAPIView):
    """Apply an exact-principal group membership through the durable journal."""

    @extend_schema(request=NativeMembershipMutationSerializer, responses={202: AuthorizationMutationSerializer})
    def post(
        self, request: Request, target_type: str, target_uuid: UUID, group_uuid: UUID, account_uuid: UUID | None = None
    ) -> Response:
        command = NativeMembershipMutationSerializer(data=request.data)
        command.is_valid(raise_exception=True)
        data = command.validated_data
        change = GroupMembershipChange(group_uuid, data["principal_uuid"], PolicyEffect(data["effect"]))
        return _native_result(request, target_type, target_uuid, account_uuid, change, data["idempotency_key"])


class ScopedAuthorizationPolicyAssignmentView(_AuthorizationAPIView):
    """Apply a scoped custom policy assignment through the durable journal."""

    @extend_schema(request=RoleAssignmentMutationSerializer, responses={202: AuthorizationMutationSerializer})
    def post(
        self, request: Request, target_type: str, target_uuid: UUID, policy_uuid: UUID, account_uuid: UUID | None = None
    ) -> Response:
        command = RoleAssignmentMutationSerializer(data=request.data)
        command.is_valid(raise_exception=True)
        data = command.validated_data
        change = RoleAssignmentChange(
            policy_uuid,
            RelationshipSubject(data["subject_kind"], data["subject_uuid"]),
            PolicyEffect(data["effect"]),
        )
        return _native_result(request, target_type, target_uuid, account_uuid, change, data["idempotency_key"])


class ScopedAuthorizationPredefinedAssignmentView(_AuthorizationAPIView):
    """Apply a catalog administrator policy at its matching scope."""

    @extend_schema(request=PredefinedRoleMutationSerializer, responses={202: AuthorizationMutationSerializer})
    def post(self, request: Request, target_type: str, target_uuid: UUID, account_uuid: UUID | None = None) -> Response:
        command = PredefinedRoleMutationSerializer(data=request.data)
        command.is_valid(raise_exception=True)
        data = command.validated_data
        change = AdministrativeRoleChange(
            RelationshipSubject(data["subject_kind"], data["subject_uuid"]),
            data["policy_code"],
            _target_ref(target_type, target_uuid),
            PolicyEffect(data["effect"]),
        )
        return _native_result(request, target_type, target_uuid, account_uuid, change, data["idempotency_key"])


class ScopedAuthorizationPolicyActionView(_AuthorizationAPIView):
    """Change a custom policy's exact action assignment."""

    @extend_schema(request=PolicyActionMutationSerializer, responses={202: AuthorizationMutationSerializer})
    def post(
        self, request: Request, target_type: str, target_uuid: UUID, policy_uuid: UUID, account_uuid: UUID | None = None
    ) -> Response:
        command = PolicyActionMutationSerializer(data=request.data)
        command.is_valid(raise_exception=True)
        return _action_result(
            request,
            target_type,
            target_uuid,
            account_uuid,
            RelationshipSubject("role", policy_uuid),
            command.validated_data,
        )


class ScopedAuthorizationDirectAssignmentView(_AuthorizationAPIView):
    """Change one direct principal or group action assignment."""

    @extend_schema(request=DirectActionAssignmentMutationSerializer, responses={202: AuthorizationMutationSerializer})
    def post(self, request: Request, target_type: str, target_uuid: UUID, account_uuid: UUID | None = None) -> Response:
        command = DirectActionAssignmentMutationSerializer(data=request.data)
        command.is_valid(raise_exception=True)
        data = command.validated_data
        subject = RelationshipSubject(data["subject_kind"], data["subject_uuid"])
        return _action_result(request, target_type, target_uuid, account_uuid, subject, data)


class ScopedAuthorizationOperationView(_AuthorizationAPIView):
    """Inspect or explicitly reconcile a scoped durable mutation."""

    @extend_schema(responses={200: AuthorizationOperationSerializer})
    def get(
        self,
        request: Request,
        target_type: str,
        target_uuid: UUID,
        operation_uuid: UUID,
        account_uuid: UUID | None = None,
    ) -> Response:
        actor, scope, provider = _operation_context(request, target_type, target_uuid, account_uuid)
        result = services.get_authorization_operation(actor.principal, actor.ceiling, scope, provider, operation_uuid)
        return Response(AuthorizationOperationSerializer(result).data)

    @extend_schema(request=None, responses={200: AuthorizationOperationSerializer})
    def post(
        self,
        request: Request,
        target_type: str,
        target_uuid: UUID,
        operation_uuid: UUID,
        account_uuid: UUID | None = None,
    ) -> Response:
        command = ClosedCommandSerializer(data=request.data)
        command.is_valid(raise_exception=True)
        actor, scope, provider = _operation_context(request, target_type, target_uuid, account_uuid)
        result = services.reconcile_authorization_operation(
            actor.principal, actor.ceiling, scope, provider, operation_uuid
        )
        return Response(AuthorizationOperationSerializer(result).data)
