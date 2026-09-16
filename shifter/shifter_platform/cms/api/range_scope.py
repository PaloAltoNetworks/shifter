"""Range-to-workspace scope administration API (PLAT-237, #1944).

Staff-session-only administrative surface: list the ranges scoped to a workspace
and reassign a range's workspace scope. Authority is the conjunction of a staff
browser session (``IsStaffSession``) and the workspace-level operation enforced
downstream by ``cms.services`` / ``workspaces.services``; platform API tokens are
rejected by the bearer-first chain. Ranges and workspaces are addressed by public
UUIDs only, and every serializer is explicit so no internal id, range spec, or
range detail crosses the boundary.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import serializers
from rest_framework.authentication import SessionAuthentication
from rest_framework.exceptions import NotFound
from rest_framework.generics import ListAPIView
from rest_framework.response import Response
from rest_framework.views import APIView

from cms.exceptions import RangeScopeAdminError
from cms.models import RangeInstance
from cms.services import (
    RangeScopeAuditContext,
    list_range_scope_bindings,
    rebind_range_workspace,
)
from shared.api.errors import api_error_response
from shared.api.permissions import IsStaffSession
from shared.api_tokens.authentication import ApiTokenAuthentication
from shared.audit import get_actor_from_request, get_client_ip, get_request_id
from shared.range_workspace_aggregate import range_instance_ids_in_domain_aggregates

if TYPE_CHECKING:
    import uuid

    from django.db.models import QuerySet
    from rest_framework.request import Request

# Bearer-first, fail-closed chain: an invalid ``shf_`` bearer is rejected before
# the session fallback, and a valid platform token authenticates as an ApiToken
# principal that ``IsStaffSession`` then rejects (this surface is session-only).
_ADMIN_AUTHENTICATION = [ApiTokenAuthentication, SessionAuthentication]

# Classified scope-error -> bounded HTTP status. Every non-not-found outcome is an
# opaque 409 so a caller cannot distinguish an authority, archive, membership,
# drift, or aggregate-lock failure from one another.
_SCOPE_ERROR_STATUS = {
    RangeScopeAdminError.Kind.NOT_FOUND: 404,
    RangeScopeAdminError.Kind.TARGET_DENIED: 409,
    RangeScopeAdminError.Kind.CONFLICT: 409,
    RangeScopeAdminError.Kind.NOT_REASSIGNABLE: 409,
}

# Authored per-kind user-facing messages, selected by the classified kind. The
# response message is one of this fixed set of literals rather than ``str(exc)``,
# so exception text never flows into the response body (CodeQL py/stack-trace-exposure).
_SCOPE_ERROR_MESSAGES = {
    RangeScopeAdminError.Kind.NOT_FOUND: "Range not found",
    RangeScopeAdminError.Kind.TARGET_DENIED: "Target workspace is not eligible for this move",
    RangeScopeAdminError.Kind.CONFLICT: "The range's workspace scope changed; refresh and try again",
    RangeScopeAdminError.Kind.NOT_REASSIGNABLE: "This range's workspace scope cannot be reassigned",
}


class RangeScopeBindingSerializer(serializers.Serializer):
    """Bounded, read-only projection of a range scoped to a workspace.

    Explicit fields only (never a ``ModelSerializer``): no internal workspace or
    range id, range spec, instance/IP/access detail, credential, or ORM object is
    exposed.
    """

    request_id = serializers.SerializerMethodField()
    owner_id = serializers.IntegerField(source="user_id")
    range_source = serializers.CharField()
    status = serializers.CharField()
    scenario_id = serializers.CharField()
    created_at = serializers.DateTimeField()
    updated_at = serializers.DateTimeField()
    expires_at = serializers.DateTimeField(allow_null=True)
    is_reassignable = serializers.SerializerMethodField()

    def get_request_id(self, obj: RangeInstance) -> str | None:
        """Return the durable request correlation UUID, or null for a legacy request-less row."""
        return str(obj.request.request_id) if obj.request else None

    def get_is_reassignable(self, obj: RangeInstance) -> bool:
        """Whether this range's scope may be reassigned here.

        Authoritative, never provenance-based: a range is reassignable when it is
        addressable by a request correlation and not owned by a domain aggregate
        (the set of aggregate-bound ids is resolved once per page and passed in
        via ``aggregate_bound_ids``). Advisory only; the server reauthorizes.
        """
        if obj.request is None:
            return False
        bound: set[int] = self.context.get("aggregate_bound_ids", set())
        return obj.pk not in bound


@extend_schema_view(
    get=extend_schema(
        responses=RangeScopeBindingSerializer(many=True),
        operation_id="api_v1_cms_workspace_range_scope_list",
    )
)
class WorkspaceRangeScopeListView(ListAPIView):
    """Paginated ranges scoped to a workspace by its public UUID. Staff + list op."""

    authentication_classes = _ADMIN_AUTHENTICATION
    permission_classes = [IsStaffSession]
    serializer_class = RangeScopeBindingSerializer

    def get_queryset(self) -> QuerySet[RangeInstance]:
        try:
            return list_range_scope_bindings(self.request.user, workspace_uuid=self.kwargs["workspace_uuid"])
        except RangeScopeAdminError as exc:
            # Unknown or unauthorized workspace share one opaque not-found.
            raise NotFound("Workspace not found.") from exc

    def list(self, request: Request, *args, **kwargs) -> Response:
        """Paginate, resolve aggregate membership once for the page, then serialize.

        Computing the aggregate-bound id set for exactly the page's rows keeps the
        authoritative ``is_reassignable`` flag out of an N+1 per-row query.
        """
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        rows = page if page is not None else list(queryset)
        bound = range_instance_ids_in_domain_aggregates(
            [(row.request.request_id, row.pk) for row in rows if row.request is not None]
        )
        serializer = self.get_serializer(
            rows, many=True, context={**self.get_serializer_context(), "aggregate_bound_ids": bound}
        )
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)


class RangeWorkspaceRebindRequestSerializer(serializers.Serializer):
    """Closed request body for a scope reassignment: a target workspace UUID only."""

    target_workspace_uuid = serializers.UUIDField()


class RangeWorkspaceRebindResultSerializer(serializers.Serializer):
    """Bounded result: whether the binding changed (``false`` = idempotent no-op)."""

    changed = serializers.BooleanField()


class RangeWorkspaceRebindView(APIView):
    """Reassign a range's workspace scope. Staff + rebind op in both scopes."""

    authentication_classes = _ADMIN_AUTHENTICATION
    permission_classes = [IsStaffSession]

    @extend_schema(
        request=RangeWorkspaceRebindRequestSerializer,
        responses=RangeWorkspaceRebindResultSerializer,
        operation_id="api_v1_cms_range_workspace_rebind",
    )
    def post(self, request: Request, request_id: uuid.UUID) -> Response:
        serializer = RangeWorkspaceRebindRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        actor_type, actor_id = get_actor_from_request(request)
        audit = RangeScopeAuditContext(
            actor_type=actor_type,
            actor_id=actor_id,
            request_id=get_request_id(request),
            source_ip=get_client_ip(request),
            user_agent=request.META.get("HTTP_USER_AGENT", "")[:255],
        )

        try:
            result = rebind_range_workspace(
                request.user,
                request_id=request_id,
                target_workspace_uuid=serializer.validated_data["target_workspace_uuid"],
                audit=audit,
            )
        except RangeScopeAdminError as exc:
            return api_error_response(
                code=exc.kind.value,
                message=_SCOPE_ERROR_MESSAGES[exc.kind],
                status_code=_SCOPE_ERROR_STATUS[exc.kind],
                request=request,
            )
        return Response(RangeWorkspaceRebindResultSerializer({"changed": result.changed}).data)
