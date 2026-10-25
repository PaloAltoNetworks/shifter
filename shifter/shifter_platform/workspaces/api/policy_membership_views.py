"""Principal membership, ownership and invitation adapters prepared for S8."""

from uuid import UUID

from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.request import Request
from rest_framework.response import Response

from shared.api.closed_serializer import ClosedSerializer
from shared.api.principals import authenticated_credential
from shared.audit import request_audit
from shared.authorization import configured_authorization_provider
from shared.principal_port import resolve_principal_uuid
from workspaces import services
from workspaces.api.account_admin_views import (
    AccountMemberPageSerializer,
    AccountMemberViewSerializer,
    AccountPageQuerySerializer,
    EmptyAccountCommandSerializer,
    _AccountAPIView,
)
from workspaces.api.serializers import WorkspaceInvitationSerializer


class ScopeMemberCommandSerializer(ClosedSerializer):
    """A public principal identity; membership never accepts an implicit role grant."""

    principal_uuid = serializers.UUIDField()


class PolicyScopeMemberCollectionView(_AccountAPIView):
    """Authorize the exact parent for both principal kinds and direct roster operations."""

    @extend_schema(parameters=[AccountPageQuerySerializer], responses=AccountMemberPageSerializer)
    def get(self, request: Request, target_type: str, target_uuid: UUID) -> Response:
        query = AccountPageQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        result = services.admin_list_scope_members(
            authenticated_credential(request),
            configured_authorization_provider(),
            target_type,
            target_uuid,
            **query.validated_data,
        )
        return Response(AccountMemberPageSerializer(result).data)

    @extend_schema(request=ScopeMemberCommandSerializer, responses={204: None})
    def post(self, request: Request, target_type: str, target_uuid: UUID) -> Response:
        command = ScopeMemberCommandSerializer(data=request.data)
        command.is_valid(raise_exception=True)
        actor = authenticated_credential(request)
        services.admin_add_scope_member(
            actor,
            configured_authorization_provider(),
            target_type,
            target_uuid,
            resolve_principal_uuid(command.validated_data["principal_uuid"]),
            audit=request_audit(request, credential=actor),
        )
        return Response(status=204)


class PolicyScopeMemberDetailView(_AccountAPIView):
    """Remove a membership fact, preserving independently recorded ownership."""

    @extend_schema(responses={204: None})
    def delete(self, request: Request, target_type: str, target_uuid: UUID, principal_uuid: UUID) -> Response:
        actor = authenticated_credential(request)
        services.admin_remove_scope_member(
            actor,
            configured_authorization_provider(),
            target_type,
            target_uuid,
            principal_uuid,
            audit=request_audit(request, credential=actor),
        )
        return Response(status=204)


class PrincipalOwnershipCommandSerializer(ClosedSerializer):
    """Expected source and eligible destination are public principal UUIDs."""

    source_principal_uuid = serializers.UUIDField(allow_null=True)
    destination_principal_uuid = serializers.UUIDField()


class PolicyWorkspaceOwnershipView(_AccountAPIView):
    """Transfer a resource fact without changing membership or policy."""

    @extend_schema(request=PrincipalOwnershipCommandSerializer, responses={204: None})
    def post(self, request: Request, workspace_uuid: UUID) -> Response:
        command = PrincipalOwnershipCommandSerializer(data=request.data)
        command.is_valid(raise_exception=True)
        actor = authenticated_credential(request)
        services.admin_transfer_workspace_principal(
            actor,
            configured_authorization_provider(),
            workspace_uuid,
            **command.validated_data,
            audit=request_audit(request, credential=actor),
        )
        return Response(status=204)


class PolicyWorkspaceOwnerCollectionView(_AccountAPIView):
    """Grant a resource ownership fact, without assigning policy or membership."""

    @extend_schema(request=ScopeMemberCommandSerializer, responses={204: None})
    def post(self, request: Request, workspace_uuid: UUID) -> Response:
        command = ScopeMemberCommandSerializer(data=request.data)
        command.is_valid(raise_exception=True)
        actor = authenticated_credential(request)
        services.admin_add_workspace_owner(
            actor,
            configured_authorization_provider(),
            workspace_uuid,
            command.validated_data["principal_uuid"],
            audit=request_audit(request, credential=actor),
        )
        return Response(status=204)


class PolicyWorkspaceOwnerDetailView(_AccountAPIView):
    """Remove a resource owner while preserving the last-owner invariant."""

    @extend_schema(responses={204: None})
    def delete(self, request: Request, workspace_uuid: UUID, principal_uuid: UUID) -> Response:
        actor = authenticated_credential(request)
        services.admin_remove_workspace_owner(
            actor,
            configured_authorization_provider(),
            workspace_uuid,
            principal_uuid,
            audit=request_audit(request, credential=actor),
        )
        return Response(status=204)


class PolicyInvitationCommandSerializer(ClosedSerializer):
    """Invite a human recipient; explicit policy assignment is a separate operation."""

    email = serializers.EmailField(max_length=254)


class PolicyWorkspaceInvitationSerializer(WorkspaceInvitationSerializer):
    """A membership invitation exposes no legacy role or implicit authority grant."""

    role = None


class PolicyInvitationPageSerializer(serializers.Serializer):
    """A bounded, parent-authorized invitation page."""

    count = serializers.IntegerField(read_only=True)
    results = PolicyWorkspaceInvitationSerializer(many=True, read_only=True)


class PolicyInvitationCollectionView(_AccountAPIView):
    """List/issue through the existing signed-token and delivery seam."""

    @extend_schema(parameters=[AccountPageQuerySerializer], responses=PolicyInvitationPageSerializer)
    def get(self, request: Request, workspace_uuid: UUID) -> Response:
        query = AccountPageQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        count, results = services.admin_list_workspace_invitations(
            authenticated_credential(request),
            configured_authorization_provider(),
            workspace_uuid,
            **query.validated_data,
        )
        return Response(PolicyInvitationPageSerializer({"count": count, "results": results}).data)

    @extend_schema(request=PolicyInvitationCommandSerializer, responses={201: PolicyWorkspaceInvitationSerializer})
    def post(self, request: Request, workspace_uuid: UUID) -> Response:
        command = PolicyInvitationCommandSerializer(data=request.data)
        command.is_valid(raise_exception=True)
        actor = authenticated_credential(request)
        result = services.admin_issue_workspace_invitation(
            actor,
            configured_authorization_provider(),
            workspace_uuid,
            command.validated_data["email"],
            audit=request_audit(request, credential=actor),
        )
        return Response(PolicyWorkspaceInvitationSerializer(result).data, status=201)


class PolicyInvitationMutationView(_AccountAPIView):
    """Revoke/resend retain generation and strict-audit invariants."""

    @extend_schema(request=EmptyAccountCommandSerializer, responses=PolicyWorkspaceInvitationSerializer)
    def post(self, request: Request, workspace_uuid: UUID, invitation_uuid: UUID, operation: str) -> Response:
        command = EmptyAccountCommandSerializer(data=request.data)
        command.is_valid(raise_exception=True)
        actor = authenticated_credential(request)
        method = (
            services.admin_revoke_workspace_invitation
            if operation == "revoke"
            else services.admin_resend_workspace_invitation
        )
        result = method(
            actor,
            configured_authorization_provider(),
            workspace_uuid,
            invitation_uuid,
            audit=request_audit(request, credential=actor),
        )
        return Response(PolicyWorkspaceInvitationSerializer(result).data)


class PolicySelfWorkspaceMembershipView(_AccountAPIView):
    """Only the admitted principal's own membership fact."""

    @extend_schema(responses=AccountMemberViewSerializer)
    def get(self, request: Request, workspace_uuid: UUID) -> Response:
        result = services.policy_self_workspace_membership(
            authenticated_credential(request), configured_authorization_provider(), workspace_uuid
        )
        return Response(AccountMemberViewSerializer(result).data)


class PolicyLeaveWorkspaceView(_AccountAPIView):
    """Self leave retains the last-owner invariant and never changes policy tuples."""

    @extend_schema(request=EmptyAccountCommandSerializer, responses={204: None})
    def post(self, request: Request, workspace_uuid: UUID) -> Response:
        command = EmptyAccountCommandSerializer(data=request.data)
        command.is_valid(raise_exception=True)
        actor = authenticated_credential(request)
        services.policy_leave_workspace(
            actor, configured_authorization_provider(), workspace_uuid, audit=request_audit(request, credential=actor)
        )
        return Response(status=204)
