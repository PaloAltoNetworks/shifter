"""Session-authorized workspace lifecycle views (#1940, PLAT-233).

Split out of :mod:`workspaces.api.views` to keep each module within the
file-size budget (Sonar S104). These views share the service-to-HTTP error
mapping (`_WorkspaceAPIError` / `_raise_as_response`) with the membership views
in :mod:`workspaces.api.views`; the workspace lifecycle domain authority lives
entirely in :mod:`workspaces.services`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.authentication import SessionAuthentication
from rest_framework.response import Response
from rest_framework.views import APIView

from shared.api.errors import api_error_response
from shared.api.permissions import IsAuthenticatedSession
from shared.api.schema import ApiErrorSerializer
from shared.api_tokens.authentication import ApiTokenAuthentication
from shared.audit import get_actor_from_request, get_client_ip, get_request_id
from workspaces import services
from workspaces.api.schema import SESSION_ONLY_SCHEMA_AUTH
from workspaces.api.serializers import (
    CreateWorkspaceSerializer,
    RenameWorkspaceSerializer,
    SetWorkspaceEgressPolicySerializer,
    TransferWorkspaceOwnershipSerializer,
    WorkspaceQuotaSerializer,
    WorkspaceSerializer,
)
from workspaces.api.views import _raise_as_response, _WorkspaceAPIError

if TYPE_CHECKING:
    from rest_framework.request import Request


def _workspace_lifecycle_audit(request: Request) -> services.WorkspaceAuditContext:
    """Build trusted workspace-lifecycle audit attribution from the request."""
    actor_type, actor_id = get_actor_from_request(request)
    return services.WorkspaceAuditContext(
        actor_type=actor_type,
        actor_id=actor_id,
        source_ip=get_client_ip(request),
        user_agent=request.META.get("HTTP_USER_AGENT", "")[:500],
        request_id=get_request_id(request),
    )


def _query_flag(request: Request, name: str) -> bool:
    """Interpret a boolean-ish query parameter (absent or falsey -> False)."""
    value = request.query_params.get(name)
    return value is not None and value.strip().lower() in {"1", "true", "yes", "on"}


#: Cookie-only OpenAPI auth for the session-only workspace lifecycle surface. The
#: bearer-first chain admits an ``shf_`` token as an ApiToken principal only so
#: ``IsAuthenticatedSession`` can refuse it, but drf-spectacular derives the
#: published auth alternatives from ``authentication_classes`` and would otherwise
#: advertise token access the runtime rejects. Every operation applies this
#: override so the generated contract matches the runtime authority model, mirroring
#: the audit endpoint (``shared.api.audit``). drf-spectacular's ``auth`` argument is
#: loosely typed, hence the ignore at each call site.
class _WorkspaceLifecycleAPIView(APIView):
    """Base view for the session-authorized workspace lifecycle surface (#1940).

    Session-only, like the organization profile endpoints (ADR-048, PLAT-232):
    the bearer-first, fail-closed chain authenticates an ``shf_`` token as an
    ApiToken principal, which ``IsAuthenticatedSession`` then refuses. Domain
    authority is enforced inside ``workspaces.services`` -- organization-admin
    membership for create/list, and the workspace role seam for read/mutate --
    so a valid session alone never grants workspace authority. The SPA
    ``/administer`` console remains staff-gated at the route level for
    defense-in-depth.
    """

    authentication_classes = [ApiTokenAuthentication, SessionAuthentication]
    permission_classes = [IsAuthenticatedSession]

    def handle_exception(self, exc: Exception) -> Response:
        if isinstance(exc, _WorkspaceAPIError):
            return exc.to_response()
        return super().handle_exception(exc)


class WorkspaceCollectionView(_WorkspaceLifecycleAPIView):
    """List an organization's workspaces or create a new one (org-admin authority)."""

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "organization",
                OpenApiTypes.UUID,
                OpenApiParameter.QUERY,
                required=True,
                description="Public UUID of the organization to scope the list to.",
            ),
            OpenApiParameter(
                "include_archived",
                OpenApiTypes.BOOL,
                OpenApiParameter.QUERY,
                required=False,
                description="Include archived workspaces (default false: active only).",
            ),
            OpenApiParameter(
                "search",
                OpenApiTypes.STR,
                OpenApiParameter.QUERY,
                required=False,
                description="Case-insensitive workspace-name substring filter.",
            ),
        ],
        responses={200: WorkspaceSerializer(many=True), 400: ApiErrorSerializer, 403: ApiErrorSerializer},
        operation_id="api_v1_workspaces_list",
        auth=SESSION_ONLY_SCHEMA_AUTH,  # type: ignore[arg-type]
    )
    def get(self, request: Request) -> Response:
        organization_uuid = request.query_params.get("organization")
        if not organization_uuid:
            return api_error_response(
                code="organization_required",
                message="An 'organization' UUID query parameter is required",
                status_code=400,
                request=request,
            )
        try:
            workspaces = services.list_workspaces(
                request.user,
                organization_uuid,
                include_archived=_query_flag(request, "include_archived"),
                search=request.query_params.get("search"),
            )
        except services.OrganizationAuthorizationError as exc:
            _raise_as_response(exc, request)
        return Response(WorkspaceSerializer(workspaces, many=True).data)

    @extend_schema(
        request=CreateWorkspaceSerializer,
        responses={
            201: WorkspaceSerializer,
            400: ApiErrorSerializer,
            403: ApiErrorSerializer,
            409: ApiErrorSerializer,
        },
        operation_id="api_v1_workspaces_create",
        auth=SESSION_ONLY_SCHEMA_AUTH,  # type: ignore[arg-type]
    )
    def post(self, request: Request) -> Response:
        command = CreateWorkspaceSerializer(data=request.data)
        command.is_valid(raise_exception=True)
        try:
            workspace = services.create_workspace(
                request.user,
                command.validated_data["organization_uuid"],
                command.validated_data["name"],
                audit=_workspace_lifecycle_audit(request),
            )
        except (services.OrganizationAuthorizationError, services.WorkspaceLifecycleError) as exc:
            _raise_as_response(exc, request)
        return Response(WorkspaceSerializer(workspace).data, status=status.HTTP_201_CREATED)


class WorkspaceDetailView(_WorkspaceLifecycleAPIView):
    """Read a workspace's administrative detail or rename it (workspace role seam)."""

    @extend_schema(
        responses={200: WorkspaceSerializer, 403: ApiErrorSerializer},
        operation_id="api_v1_workspace_detail",
        auth=SESSION_ONLY_SCHEMA_AUTH,  # type: ignore[arg-type]
    )
    def get(self, request: Request, workspace_uuid: UUID) -> Response:
        try:
            workspace = services.get_workspace(request.user, workspace_uuid)
        except services.WorkspaceAuthorizationError as exc:
            _raise_as_response(exc, request)
        return Response(WorkspaceSerializer(workspace).data)

    @extend_schema(
        request=RenameWorkspaceSerializer,
        responses={
            200: WorkspaceSerializer,
            400: ApiErrorSerializer,
            403: ApiErrorSerializer,
            409: ApiErrorSerializer,
        },
        operation_id="api_v1_workspace_rename",
        auth=SESSION_ONLY_SCHEMA_AUTH,  # type: ignore[arg-type]
    )
    def patch(self, request: Request, workspace_uuid: UUID) -> Response:
        command = RenameWorkspaceSerializer(data=request.data)
        command.is_valid(raise_exception=True)
        try:
            workspace = services.rename_workspace(
                request.user,
                workspace_uuid,
                command.validated_data["name"],
                audit=_workspace_lifecycle_audit(request),
            )
        except (services.WorkspaceAuthorizationError, services.WorkspaceLifecycleError) as exc:
            _raise_as_response(exc, request)
        return Response(WorkspaceSerializer(workspace).data)


class WorkspaceArchiveView(_WorkspaceLifecycleAPIView):
    """Archive a workspace (reversible soft-state marker)."""

    @extend_schema(
        request=None,
        responses={200: WorkspaceSerializer, 403: ApiErrorSerializer, 409: ApiErrorSerializer},
        operation_id="api_v1_workspace_archive",
        auth=SESSION_ONLY_SCHEMA_AUTH,  # type: ignore[arg-type]
    )
    def post(self, request: Request, workspace_uuid: UUID) -> Response:
        try:
            workspace = services.archive_workspace(
                request.user,
                workspace_uuid,
                audit=_workspace_lifecycle_audit(request),
            )
        except (services.WorkspaceAuthorizationError, services.WorkspaceLifecycleError) as exc:
            _raise_as_response(exc, request)
        return Response(WorkspaceSerializer(workspace).data)


class WorkspaceRestoreView(_WorkspaceLifecycleAPIView):
    """Restore an archived workspace."""

    @extend_schema(
        request=None,
        responses={200: WorkspaceSerializer, 403: ApiErrorSerializer, 409: ApiErrorSerializer},
        operation_id="api_v1_workspace_restore",
        auth=SESSION_ONLY_SCHEMA_AUTH,  # type: ignore[arg-type]
    )
    def post(self, request: Request, workspace_uuid: UUID) -> Response:
        try:
            workspace = services.restore_workspace(
                request.user,
                workspace_uuid,
                audit=_workspace_lifecycle_audit(request),
            )
        except (services.WorkspaceAuthorizationError, services.WorkspaceLifecycleError) as exc:
            _raise_as_response(exc, request)
        return Response(WorkspaceSerializer(workspace).data)


class WorkspaceEgressPolicyView(_WorkspaceLifecycleAPIView):
    """Set the network egress policy of a workspace (owner/admin, PLAT-238, #1945)."""

    @extend_schema(
        request=SetWorkspaceEgressPolicySerializer,
        responses={
            200: WorkspaceSerializer,
            400: ApiErrorSerializer,
            403: ApiErrorSerializer,
        },
        operation_id="api_v1_workspace_set_egress_policy",
        # Session-only: the bearer-first chain admits a platform token as an
        # ApiToken principal only for IsAuthenticatedSession to refuse it, so the
        # published contract must advertise cookie auth alone and not imply token
        # access (mirrors the audit endpoint's canonical override).
        auth=SESSION_ONLY_SCHEMA_AUTH,  # type: ignore[arg-type]
    )
    def put(self, request: Request, workspace_uuid: UUID) -> Response:
        command = SetWorkspaceEgressPolicySerializer(data=request.data)
        command.is_valid(raise_exception=True)
        try:
            workspace = services.set_workspace_egress_policy(
                request.user,
                workspace_uuid,
                command.validated_data["egress_policy"],
                audit=_workspace_lifecycle_audit(request),
            )
        except (services.WorkspaceAuthorizationError, services.WorkspaceLifecycleError) as exc:
            _raise_as_response(exc, request)
        return Response(WorkspaceSerializer(workspace).data)


class WorkspaceQuotaView(_WorkspaceLifecycleAPIView):
    """Read a workspace's resource quota usage and recent decisions (owner/admin, PLAT-239).

    Read-only. Usage against configured limits and the recent quota decisions let
    an administrator see when and why a cap applied. Quota *policy* is authored
    only through the superuser-only Django-admin escape hatch, never here.
    """

    @extend_schema(
        responses={200: WorkspaceQuotaSerializer, 403: ApiErrorSerializer},
        operation_id="api_v1_workspace_quota",
        auth=SESSION_ONLY_SCHEMA_AUTH,  # type: ignore[arg-type]
    )
    def get(self, request: Request, workspace_uuid: UUID) -> Response:
        try:
            quota = services.workspace_quota_usage(request.user, workspace_uuid)
        except services.WorkspaceAuthorizationError as exc:
            _raise_as_response(exc, request)
        return Response(WorkspaceQuotaSerializer(quota).data)


class WorkspaceTransferOwnershipView(_WorkspaceLifecycleAPIView):
    """Transfer workspace ownership to an existing member (owner-only)."""

    @extend_schema(
        request=TransferWorkspaceOwnershipSerializer,
        responses={
            200: WorkspaceSerializer,
            400: ApiErrorSerializer,
            403: ApiErrorSerializer,
            404: ApiErrorSerializer,
        },
        operation_id="api_v1_workspace_transfer_ownership",
        auth=SESSION_ONLY_SCHEMA_AUTH,  # type: ignore[arg-type]
    )
    def post(self, request: Request, workspace_uuid: UUID) -> Response:
        command = TransferWorkspaceOwnershipSerializer(data=request.data)
        command.is_valid(raise_exception=True)
        try:
            workspace = services.transfer_workspace_ownership(
                request.user,
                workspace_uuid,
                command.validated_data["user_id"],
                audit=_workspace_lifecycle_audit(request),
            )
        except (services.WorkspaceAuthorizationError, services.WorkspaceLifecycleError) as exc:
            _raise_as_response(exc, request)
        return Response(WorkspaceSerializer(workspace).data)
