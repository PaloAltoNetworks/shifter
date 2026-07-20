"""Named-operation views for the Administer user-administration API (#1373).

Reads use read-only generic views with explicit read serializers; each command
is its own endpoint with an explicit request shape, its own model permission,
and a strict, request-attributed audit written inside the service's atomic
boundary. There is no ``ModelViewSet`` and no writable model serializer.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework.authentication import SessionAuthentication
from rest_framework.exceptions import NotFound
from rest_framework.generics import ListAPIView, RetrieveAPIView
from rest_framework.response import Response
from rest_framework.views import APIView

from management import admin_services, services
from management.api.serializers import (
    AdminUserDetailSerializer,
    AdminUserListItemSerializer,
    AdminUserListQuerySerializer,
    SetActiveRequestSerializer,
)
from shared.api.errors import api_error_response
from shared.api.permissions import IsStaffSession, require_model_permission
from shared.api_tokens.authentication import ApiTokenAuthentication
from shared.audit import get_actor_from_request, get_client_ip, get_request_id

# Bearer-first, fail-closed authentication chain (ADR-029 / #1373 preflight).
# ApiTokenAuthentication runs first so an invalid or revoked ``shf_`` bearer
# credential is rejected outright and never falls through to the session; a valid
# platform token authenticates as an ApiToken principal, which IsStaffSession then
# rejects (management endpoints are session-only).
_ADMINISTER_AUTHENTICATION = [ApiTokenAuthentication, SessionAuthentication]

if TYPE_CHECKING:
    from django.contrib.auth.models import User
    from django.db.models import QuerySet
    from rest_framework.request import Request


def _audit_context(request: Request) -> services.AuditContext:
    """Build request-attributed audit context to hand to the domain service."""
    actor_type, actor_id = get_actor_from_request(request)
    return services.AuditContext(
        actor_type=actor_type,
        actor_id=actor_id,
        request_id=get_request_id(request),
        source_ip=get_client_ip(request),
        user_agent=request.META.get("HTTP_USER_AGENT", "")[:255],
    )


def _require_user(pk: int) -> User:
    """Resolve the target user for an Administer command, or raise a 404."""
    user = services.get_admin_user(pk)
    if user is None:
        raise NotFound("User not found.")
    return user


@extend_schema_view(
    get=extend_schema(
        parameters=[AdminUserListQuerySerializer],
        responses=AdminUserListItemSerializer(many=True),
        operation_id="api_v1_administer_users_list",
    )
)
class AdminUserListView(ListAPIView):
    """Paginated, filterable, read-only user list. Requires ``auth.view_user``."""

    authentication_classes = _ADMINISTER_AUTHENTICATION
    permission_classes = [IsStaffSession, require_model_permission("auth.view_user")]
    serializer_class = AdminUserListItemSerializer

    def get_queryset(self) -> QuerySet[User]:
        query = AdminUserListQuerySerializer(data=self.request.query_params)
        query.is_valid(raise_exception=True)
        data = query.validated_data
        return admin_services.list_admin_users(
            search=data.get("search", ""),
            user_type=data.get("user_type", ""),
            is_active=data.get("is_active", None),
            account_origin=data.get("account_origin", ""),
            include_deleted=data.get("include_deleted", False),
        )


@extend_schema_view(
    get=extend_schema(responses=AdminUserDetailSerializer, operation_id="api_v1_administer_users_retrieve")
)
class AdminUserDetailView(RetrieveAPIView):
    """Read-only user detail. Includes soft-deleted accounts. ``auth.view_user``."""

    authentication_classes = _ADMINISTER_AUTHENTICATION
    permission_classes = [IsStaffSession, require_model_permission("auth.view_user")]
    serializer_class = AdminUserDetailSerializer

    def get_queryset(self) -> QuerySet[User]:
        return admin_services.list_admin_users(include_deleted=True)


class AdminUserSetActiveView(APIView):
    """Activate or deactivate a user's login. Requires ``auth.change_user``."""

    authentication_classes = _ADMINISTER_AUTHENTICATION
    permission_classes = [IsStaffSession, require_model_permission("auth.change_user")]

    @extend_schema(
        request=SetActiveRequestSerializer,
        responses=AdminUserDetailSerializer,
        operation_id="api_v1_administer_users_set_active",
    )
    def post(self, request: Request, pk: int) -> Response:
        user = _require_user(pk)

        serializer = SetActiveRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        active = serializer.validated_data["is_active"]

        if user.pk == request.user.pk and not active:
            return api_error_response(
                code="self_deactivation_forbidden",
                message="You cannot deactivate your own account.",
                status_code=400,
                request=request,
            )

        admin_services.set_user_active(user, active=active, audit=_audit_context(request))
        user.refresh_from_db()
        return Response(AdminUserDetailSerializer(user).data)


class AdminUserDeleteView(APIView):
    """Soft-delete (disable) a user account. Requires ``auth.delete_user``.

    Sets the profile ``deleted_at`` marker; it never hard-deletes the row, never
    anonymizes, and never unbinds a provider identity — those are distinct
    lifecycle actions with their own contracts.
    """

    authentication_classes = _ADMINISTER_AUTHENTICATION
    permission_classes = [IsStaffSession, require_model_permission("auth.delete_user")]

    @extend_schema(
        request=None,
        responses=AdminUserDetailSerializer,
        operation_id="api_v1_administer_users_soft_delete",
    )
    def post(self, request: Request, pk: int) -> Response:
        user = _require_user(pk)

        if user.pk == request.user.pk:
            return api_error_response(
                code="self_delete_forbidden",
                message="You cannot delete your own account.",
                status_code=400,
                request=request,
            )

        services.mark_user_deleted(user, audit=_audit_context(request), strict=True)
        user.refresh_from_db()
        return Response(AdminUserDetailSerializer(user).data)
