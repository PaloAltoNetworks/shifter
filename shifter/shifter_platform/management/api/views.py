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

from management import admin_services, lifecycle, password_reset, services
from management.api.serializers import (
    AdminUserDetailSerializer,
    AdminUserListItemSerializer,
    AdminUserListQuerySerializer,
    LifecycleTransitionRequestSerializer,
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

# Django model permissions gating the Administer command endpoints.
_VIEW_USER_PERM = "auth.view_user"
_CHANGE_USER_PERM = "auth.change_user"
_DELETE_USER_PERM = "auth.delete_user"

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


# Maps a lifecycle transition error code to its HTTP status: forbidden self/
# superuser actions are 4xx authority errors; invalid/last-superuser/deleted are
# 409 conflicts against the account's current state.
_LIFECYCLE_ERROR_STATUS = {
    "self_action_forbidden": 400,
    "superuser_protected": 403,
    "last_superuser_protected": 409,
    "invalid_transition": 409,
    "account_deleted": 409,
}


def _lifecycle_error_response(exc: lifecycle.AccountLifecycleError, request: Request) -> Response:
    """Map an :class:`AccountLifecycleError` to the shared safe error envelope."""
    return api_error_response(
        code=exc.code,
        message=exc.message,
        status_code=_LIFECYCLE_ERROR_STATUS.get(exc.code, 400),
        request=request,
    )


def _detail_response(user: User, request: Request) -> Response:
    """Serialize the user detail with request context (server-derived actions)."""
    user.refresh_from_db()
    return Response(AdminUserDetailSerializer(user, context={"request": request}).data)


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
    permission_classes = [IsStaffSession, require_model_permission(_VIEW_USER_PERM)]
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
    permission_classes = [IsStaffSession, require_model_permission(_VIEW_USER_PERM)]
    serializer_class = AdminUserDetailSerializer

    def get_queryset(self) -> QuerySet[User]:
        return admin_services.list_admin_users(include_deleted=True)


class AdminUserSetActiveView(APIView):
    """Activate or deactivate a user's login. Requires ``auth.change_user``."""

    authentication_classes = _ADMINISTER_AUTHENTICATION
    permission_classes = [IsStaffSession, require_model_permission(_CHANGE_USER_PERM)]

    @extend_schema(
        request=SetActiveRequestSerializer,
        responses=AdminUserDetailSerializer,
        operation_id="api_v1_administer_users_set_active",
    )
    def post(self, request: Request, pk: int) -> Response:
        # v1 compatibility adapter: delegates to the one lifecycle transition
        # service (PLAT-236, #1943) so there is no second account state machine.
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

        action = lifecycle.AccountLifecycleAction.ACTIVATE if active else lifecycle.AccountLifecycleAction.DEACTIVATE
        try:
            lifecycle.transition_account(user, action=action, actor=request.user, audit=_audit_context(request))
        except lifecycle.AccountLifecycleError as exc:
            return _lifecycle_error_response(exc, request)
        return _detail_response(user, request)


class AdminUserDeleteView(APIView):
    """Soft-delete (disable) a user account. Requires ``auth.delete_user``.

    Sets the profile ``deleted_at`` marker; it never hard-deletes the row, never
    anonymizes, and never unbinds a provider identity — those are distinct
    lifecycle actions with their own contracts.
    """

    authentication_classes = _ADMINISTER_AUTHENTICATION
    permission_classes = [IsStaffSession, require_model_permission(_DELETE_USER_PERM)]

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

        # Route through the one lifecycle transition service (PLAT-236, #1943)
        # so soft deletion also disables authentication, revokes live tokens, and
        # honours the superuser / last-active-superuser invariants.
        try:
            lifecycle.transition_account(
                user,
                action=lifecycle.AccountLifecycleAction.DELETE,
                actor=request.user,
                audit=_audit_context(request),
            )
        except lifecycle.AccountLifecycleError as exc:
            return _lifecycle_error_response(exc, request)
        return _detail_response(user, request)


class AdminUserLifecycleView(APIView):
    """Activate, deactivate, or suspend a user account. Requires ``auth.change_user``.

    The one closed desired-state lifecycle command (PLAT-236, #1943). Suspend and
    deactivate both block sign-in and retain assignments; they differ only in the
    suspension discriminator. Soft deletion is the separate ``/delete/`` endpoint
    (``auth.delete_user``).
    """

    authentication_classes = _ADMINISTER_AUTHENTICATION
    permission_classes = [IsStaffSession, require_model_permission(_CHANGE_USER_PERM)]

    @extend_schema(
        request=LifecycleTransitionRequestSerializer,
        responses=AdminUserDetailSerializer,
        operation_id="api_v1_administer_users_lifecycle",
    )
    def post(self, request: Request, pk: int) -> Response:
        user = _require_user(pk)

        serializer = LifecycleTransitionRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        action = lifecycle.AccountLifecycleAction(serializer.validated_data["action"])

        try:
            lifecycle.transition_account(user, action=action, actor=request.user, audit=_audit_context(request))
        except lifecycle.AccountLifecycleError as exc:
            return _lifecycle_error_response(exc, request)
        return _detail_response(user, request)


class AdminUserResetPasswordView(APIView):
    """Trigger a Django password-reset email for an eligible account. ``auth.change_user``.

    Uses Django's proven password-reset machinery for an active local, non-CTF
    account only; a provider-bound account resets at its provider and a temporary
    CTF account keeps its event-scoped credential flow (PLAT-236, #1943). Returns
    a safe accepted/error envelope; no secret is ever returned.
    """

    authentication_classes = _ADMINISTER_AUTHENTICATION
    permission_classes = [IsStaffSession, require_model_permission(_CHANGE_USER_PERM)]

    @extend_schema(
        request=None,
        responses=AdminUserDetailSerializer,
        operation_id="api_v1_administer_users_reset_password",
    )
    def post(self, request: Request, pk: int) -> Response:
        user = _require_user(pk)
        try:
            password_reset.request_password_reset(user, audit=_audit_context(request), request=request._request)
        except password_reset.PasswordResetError as exc:
            status_code = 409 if exc.code == "reset_throttled" else 400
            return api_error_response(code=exc.code, message=exc.message, status_code=status_code, request=request)
        return _detail_response(user, request)
