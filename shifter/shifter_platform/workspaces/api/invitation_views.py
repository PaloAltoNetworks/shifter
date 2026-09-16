"""Staff-session administration endpoints for workspace invitations."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from drf_spectacular.utils import extend_schema
from rest_framework.authentication import SessionAuthentication
from rest_framework.response import Response

from shared.api.permissions import IsStaffSession
from shared.api.schema import ApiErrorSerializer
from shared.api_tokens.authentication import ApiTokenAuthentication
from workspaces import services
from workspaces.api.serializers import IssueWorkspaceInvitationSerializer, WorkspaceInvitationSerializer
from workspaces.api.views import _actor, _audit, _raise_as_response, _WorkspaceAPIView

if TYPE_CHECKING:
    from rest_framework.request import Request


class _WorkspaceInvitationAdminAPIView(_WorkspaceAPIView):
    """Admit staff sessions before live workspace-role authorization."""

    authentication_classes = [ApiTokenAuthentication, SessionAuthentication]
    permission_classes = [IsStaffSession]


# Runtime authentication is bearer-first so invalid credentials cannot fall
# through to a browser session. IsStaffSession rejects every token principal,
# so the published contract lists only the accepted session credential.
_INVITATION_SCHEMA_AUTH: list[dict[str, list[str]]] = [{"cookieAuth": []}]


class WorkspaceInvitationListIssueView(_WorkspaceInvitationAdminAPIView):
    """List invitations or issue one bearer credential by email."""

    @extend_schema(
        auth=_INVITATION_SCHEMA_AUTH,  # type: ignore[arg-type]
        responses={200: WorkspaceInvitationSerializer(many=True), 403: ApiErrorSerializer},
        operation_id="api_v1_workspace_invitations_list",
    )
    def get(self, request: Request, workspace_uuid: UUID) -> Response:
        """List invitation projections visible to the authorized actor."""
        try:
            invitations = services.list_workspace_invitations(_actor(request), workspace_uuid)
        except (services.WorkspaceAuthorizationError, services.WorkspaceInvitationError) as exc:
            _raise_as_response(exc, request)
        return Response(WorkspaceInvitationSerializer(invitations, many=True).data)

    @extend_schema(
        auth=_INVITATION_SCHEMA_AUTH,  # type: ignore[arg-type]
        request=IssueWorkspaceInvitationSerializer,
        responses={
            201: WorkspaceInvitationSerializer,
            400: ApiErrorSerializer,
            403: ApiErrorSerializer,
            409: ApiErrorSerializer,
            429: ApiErrorSerializer,
            503: ApiErrorSerializer,
        },
        operation_id="api_v1_workspace_invitations_issue",
    )
    def post(self, request: Request, workspace_uuid: UUID) -> Response:
        """Issue and deliver one current workspace invitation."""
        command = IssueWorkspaceInvitationSerializer(data=request.data)
        command.is_valid(raise_exception=True)
        try:
            invitation = services.issue_workspace_invitation(
                _actor(request),
                workspace_uuid,
                command.validated_data["email"],
                command.validated_data["role"],
                audit=_audit(request),
            )
        except (
            services.WorkspaceAuthorizationError,
            services.WorkspaceMembershipError,
            services.WorkspaceInvitationError,
        ) as exc:
            _raise_as_response(exc, request)
        return Response(WorkspaceInvitationSerializer(invitation).data, status=201)


class WorkspaceInvitationResendView(_WorkspaceInvitationAdminAPIView):
    """Rotate the credential generation and redeliver an invitation."""

    @extend_schema(
        auth=_INVITATION_SCHEMA_AUTH,  # type: ignore[arg-type]
        request=None,
        responses={200: WorkspaceInvitationSerializer, 403: ApiErrorSerializer, 409: ApiErrorSerializer},
        operation_id="api_v1_workspace_invitations_resend",
    )
    def post(self, request: Request, workspace_uuid: UUID, invitation_uuid: UUID) -> Response:
        """Rotate and resend one authorized current invitation."""
        try:
            invitation = services.resend_workspace_invitation(
                _actor(request), workspace_uuid, invitation_uuid, audit=_audit(request)
            )
        except (
            services.WorkspaceAuthorizationError,
            services.WorkspaceMembershipError,
            services.WorkspaceInvitationError,
        ) as exc:
            _raise_as_response(exc, request)
        return Response(WorkspaceInvitationSerializer(invitation).data)


class WorkspaceInvitationRevokeView(_WorkspaceInvitationAdminAPIView):
    """Revoke an invitation and invalidate every issued token."""

    @extend_schema(
        auth=_INVITATION_SCHEMA_AUTH,  # type: ignore[arg-type]
        request=None,
        responses={200: WorkspaceInvitationSerializer, 403: ApiErrorSerializer, 409: ApiErrorSerializer},
        operation_id="api_v1_workspace_invitations_revoke",
    )
    def post(self, request: Request, workspace_uuid: UUID, invitation_uuid: UUID) -> Response:
        """Revoke one authorized current invitation."""
        try:
            invitation = services.revoke_workspace_invitation(
                _actor(request), workspace_uuid, invitation_uuid, audit=_audit(request)
            )
        except (
            services.WorkspaceAuthorizationError,
            services.WorkspaceMembershipError,
            services.WorkspaceInvitationError,
        ) as exc:
            _raise_as_response(exc, request)
        return Response(WorkspaceInvitationSerializer(invitation).data)
