"""S8 policy-aware identity API, prepared without replacing legacy routes."""

from __future__ import annotations

from typing import Any

from django.contrib.auth.models import User
from django.db.models import QuerySet
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.authentication import SessionAuthentication
from rest_framework.exceptions import NotFound
from rest_framework.generics import ListAPIView, RetrieveAPIView
from rest_framework.request import Request
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
from management.policy import require_principal_administration
from shared.api.closed_serializer import ClosedSerializer
from shared.api.errors import api_error_response
from shared.api.permissions import IsAuthenticatedSessionOrApiToken
from shared.api.principals import authenticated_credential
from shared.api.strict_json import ClosedJSONParser
from shared.api_tokens.authentication import ApiTokenAuthentication
from shared.audit import request_audit
from shared.authorization import AuthorizationProviderBindingError, TargetRef, configured_authorization_provider

_USER_NOT_FOUND = "User not found"


class PolicyAdminUserDetailSerializer(AdminUserDetailSerializer):
    """Prepared identity and valid-operation hints; endpoints still reauthorize."""

    principal_uuid = serializers.SerializerMethodField()
    first_name = serializers.CharField(read_only=True)
    last_name = serializers.CharField(read_only=True)

    def get_principal_uuid(self, user: User) -> str:
        return str(services.principal_identity_for_user(user).uuid)

    def get_available_actions(self, user: User) -> list[str]:
        actions = super().get_available_actions(user)
        actor = self.context.get("policy_actor")
        if (
            actor is not None
            and actor.ceiling.permits("installation.manage_principals", TargetRef("installation"))
            and services.principal_identity_for_user(user) != actor.principal
        ):
            actions.append("transfer_ownership")
        return actions


class PolicyLifecycleCommandSerializer(LifecycleTransitionRequestSerializer, ClosedSerializer):
    """Preserve the lifecycle vocabulary with closed command parsing."""


class PolicySetActiveCommandSerializer(SetActiveRequestSerializer, ClosedSerializer):
    """Closed compatibility command; principal/authority never come from its body."""


class EmptyPolicyCommandSerializer(ClosedSerializer):
    """Explicit empty command for reset and delete operations."""


class PolicyUserMetadataCommandSerializer(ClosedSerializer):
    """Contact/display fields only; provider bindings and authority are immutable here."""

    username = serializers.CharField(required=False, max_length=150)
    email = serializers.EmailField(required=False, allow_blank=True, max_length=254)
    first_name = serializers.CharField(required=False, allow_blank=True, max_length=150)
    last_name = serializers.CharField(required=False, allow_blank=True, max_length=150)


class PolicyAdminView(APIView):
    """Shared admission and bounded policy errors for the prepared S8 views."""

    authentication_classes = [ApiTokenAuthentication, SessionAuthentication]
    permission_classes = [IsAuthenticatedSessionOrApiToken]
    parser_classes = [ClosedJSONParser]

    def handle_exception(self, exc: Exception) -> Response:
        if isinstance(exc, PermissionError):
            code, message, status_code = "administration_denied", "Administration denied", 403
        elif isinstance(exc, AuthorizationProviderBindingError):
            code, message, status_code = "authorization_unavailable", "Authorization unavailable", 503
        elif isinstance(exc, lifecycle.AccountLifecycleError):
            code, message = exc.code, exc.message
            status_code = 403 if exc.code == "authority_denied" else 409
        elif isinstance(exc, password_reset.PasswordResetError):
            code, message = exc.code, exc.message
            status_code = 409 if exc.code == "reset_throttled" else 400
        else:
            return super().handle_exception(exc)
        return api_error_response(code=code, message=message, status_code=status_code, request=self.request)


class PolicyAdminUserListView(PolicyAdminView, ListAPIView):
    """Global identity list; policy is checked before filtering and pagination."""

    serializer_class = AdminUserListItemSerializer

    @extend_schema(parameters=[AdminUserListQuerySerializer], responses=AdminUserListItemSerializer(many=True))
    def get(self, request: Request, *args: object, **kwargs: object) -> Response:
        return super().get(request, *args, **kwargs)

    def get_queryset(self) -> QuerySet[User]:
        query = AdminUserListQuerySerializer(data=self.request.query_params)
        query.is_valid(raise_exception=True)
        return admin_services.list_policy_admin_users(
            authenticated_credential(self.request),
            configured_authorization_provider(),
            **query.validated_data,
        )


class PolicyAdminUserDetailView(PolicyAdminView, RetrieveAPIView):
    """Read one user only after the installation policy check."""

    serializer_class = PolicyAdminUserDetailSerializer

    @extend_schema(responses=PolicyAdminUserDetailSerializer)
    def get(self, request: Request, *args: object, **kwargs: object) -> Response:
        return super().get(request, *args, **kwargs)

    def get_queryset(self) -> QuerySet[User]:
        return admin_services.list_policy_admin_users(
            authenticated_credential(self.request),
            configured_authorization_provider(),
            include_deleted=True,
        )

    def get_serializer_context(self) -> dict[str, Any]:
        return {**super().get_serializer_context(), "policy_actor": authenticated_credential(self.request)}

    @extend_schema(request=PolicyUserMetadataCommandSerializer, responses=PolicyAdminUserDetailSerializer)
    def patch(self, request: Request, pk: int) -> Response:
        command = PolicyUserMetadataCommandSerializer(data=request.data)
        command.is_valid(raise_exception=True)
        actor = authenticated_credential(request)
        try:
            user = admin_services.update_policy_user_metadata(
                actor,
                configured_authorization_provider(),
                pk,
                command.validated_data,
                audit=request_audit(request, credential=actor),
            )
        except User.DoesNotExist as exc:
            raise NotFound(_USER_NOT_FOUND) from exc
        except ValueError:
            return api_error_response(
                code="invalid_user_metadata", message="User metadata unavailable", status_code=400, request=request
            )
        return Response(self.get_serializer(user).data)


class PolicyAdminUserLifecycleView(PolicyAdminView, APIView):
    """Run the one locked lifecycle service for human or service administrators."""

    @extend_schema(request=PolicyLifecycleCommandSerializer, responses=PolicyAdminUserDetailSerializer)
    def post(self, request: Request, pk: int) -> Response:
        command = PolicyLifecycleCommandSerializer(data=request.data)
        command.is_valid(raise_exception=True)
        return _policy_transition(request, pk, lifecycle.AccountLifecycleAction(command.validated_data["action"]))


def _policy_transition(request: Request, pk: int, action: lifecycle.AccountLifecycleAction) -> Response:
    """Use the one locked lifecycle command for every S8 compatibility route."""
    actor = authenticated_credential(request)
    provider = configured_authorization_provider()
    require_principal_administration(actor, provider)
    user = services.get_admin_user(pk)
    if user is None:
        raise NotFound(_USER_NOT_FOUND)
    attribution = request_audit(request, credential=actor)
    lifecycle.transition_account(
        user,
        action=action,
        actor=actor,
        provider=provider,
        audit=services.AuditContext(
            actor_type=attribution.actor_type,
            actor_id=attribution.actor_id,
            request_id=attribution.request_id,
            source_ip=attribution.source_ip,
            user_agent=attribution.user_agent,
        ),
    )
    user.refresh_from_db()
    return Response(PolicyAdminUserDetailSerializer(user, context={"request": request, "policy_actor": actor}).data)


class PolicyAdminUserSetActiveView(PolicyAdminView, APIView):
    """Preserve the v1 set-active command through the policy lifecycle service."""

    @extend_schema(request=PolicySetActiveCommandSerializer, responses=PolicyAdminUserDetailSerializer)
    def post(self, request: Request, pk: int) -> Response:
        command = PolicySetActiveCommandSerializer(data=request.data)
        command.is_valid(raise_exception=True)
        action = (
            lifecycle.AccountLifecycleAction.ACTIVATE
            if command.validated_data["is_active"]
            else lifecycle.AccountLifecycleAction.DEACTIVATE
        )
        return _policy_transition(request, pk, action)


class PolicyAdminUserDeleteView(PolicyAdminView, APIView):
    """Preserve the v1 soft-delete command through the policy lifecycle service."""

    @extend_schema(request=EmptyPolicyCommandSerializer, responses=PolicyAdminUserDetailSerializer)
    def post(self, request: Request, pk: int) -> Response:
        command = EmptyPolicyCommandSerializer(data=request.data)
        command.is_valid(raise_exception=True)
        return _policy_transition(request, pk, lifecycle.AccountLifecycleAction.DELETE)


class PolicyAdminUserResetPasswordView(PolicyAdminView, APIView):
    """Request a local reset through the installation policy and proven delivery service."""

    @extend_schema(request=EmptyPolicyCommandSerializer, responses=PolicyAdminUserDetailSerializer)
    def post(self, request: Request, pk: int) -> Response:
        command = EmptyPolicyCommandSerializer(data=request.data)
        command.is_valid(raise_exception=True)
        actor = authenticated_credential(request)
        provider = configured_authorization_provider()
        require_principal_administration(actor, provider)
        user = services.get_admin_user(pk)
        if user is None:
            raise NotFound(_USER_NOT_FOUND)
        attribution = request_audit(request, credential=actor)
        password_reset.request_password_reset(
            user,
            audit=services.AuditContext(
                actor_type=attribution.actor_type,
                actor_id=attribution.actor_id,
                request_id=attribution.request_id,
                source_ip=attribution.source_ip,
                user_agent=attribution.user_agent,
            ),
            request=request._request,
            actor=actor,
            provider=provider,
        )
        user.refresh_from_db()
        return Response(PolicyAdminUserDetailSerializer(user, context={"request": request, "policy_actor": actor}).data)
