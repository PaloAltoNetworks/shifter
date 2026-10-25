"""Private executable administration, distinct from pack authoring and cloud IAM."""

from __future__ import annotations

from dataclasses import asdict
from typing import TYPE_CHECKING, Any
from uuid import UUID

from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from engine.services import (
    install_preparation_adapter,
    list_preparation_adapter_grants,
    list_preparation_adapters,
    set_preparation_adapter_state,
)
from shared.api.errors import api_error_response
from shared.api.permissions import IsAuthenticatedSessionOrApiToken
from shared.api.principals import active_actor_user
from shared.api_tokens import scopes
from shared.api_tokens.permissions import require_scope
from shared.audit import RequestAudit, get_actor_from_request, get_client_ip, get_request_id
from shared.exceptions import ValidationError

if TYPE_CHECKING:
    from django.contrib.auth.models import User


def preparation_actor(request: Request) -> User:
    """Require an active token or session actor before entering preparation services."""
    actor = active_actor_user(request)
    if actor is None:
        raise ValidationError("Artifact preparation access is not permitted")
    return actor


class HasPreparationAdministration(BasePermission):
    """Staff/content-author privileges never imply executable installation."""

    def has_permission(self, request: Request, view: APIView) -> bool:
        actor = active_actor_user(request)
        return bool(actor and actor.has_perm("engine.manage_preparation_adapters"))


class PreparationSerializer(serializers.Serializer):
    """Reject ignored fields that could disguise attempted authority overrides."""

    def to_internal_value(self, data: Any) -> dict[str, Any]:
        if isinstance(data, dict) and set(data) - set(self.fields):
            raise serializers.ValidationError({"non_field_errors": ["Unknown field."]})
        return super().to_internal_value(data)


class AdapterInstallSerializer(PreparationSerializer):
    """Only an existing grant and the closed versioned manifest enter installation."""

    grant_id = serializers.UUIDField()
    manifest = serializers.JSONField()


class AdapterStateSerializer(PreparationSerializer):
    """Lifecycle changes retain immutable registration and cleanup references."""

    state = serializers.ChoiceField(choices=["enabled", "disabled", "retired"])


class AdapterViewSerializer(serializers.Serializer):
    """Private administrative detail, never a public discovery/catalog response."""

    id = serializers.UUIDField()
    grant_id = serializers.UUIDField()
    scope_digest = serializers.CharField()
    manifest_digest = serializers.CharField()
    manifest = serializers.JSONField()
    state = serializers.CharField()


def preparation_error(request: Request, exc: ValidationError) -> Response:
    """Render only the service's bounded authored error, never nested input data."""
    return api_error_response(code="invalid", message=exc.message, status_code=400, request=request)


def preparation_request_audit(request: Request) -> RequestAudit:
    """Resolve authenticated token/session attribution with the shared policy."""
    actor_type, actor_id = get_actor_from_request(request)
    return RequestAudit(
        actor_type=actor_type,
        actor_id=actor_id,
        request_id=get_request_id(request),
        source_ip=get_client_ip(request),
        user_agent=request.META.get("HTTP_USER_AGENT", "")[:255],
    )


class PreparationAdapterListCreateView(APIView):
    """Install and inspect adapters using explicit scope plus active actor authority."""

    permission_classes = [
        IsAuthenticatedSessionOrApiToken,
        HasPreparationAdministration,
        require_scope(scopes.CMS_PREPARATION_ADAPTERS_READ, scopes.CMS_PREPARATION_ADAPTERS_WRITE),
    ]

    @extend_schema(responses=AdapterViewSerializer(many=True))
    def get(self, request: Request) -> Response:
        """List private registrations only for authorized administrators."""
        try:
            return Response([asdict(row) for row in list_preparation_adapters(preparation_actor(request))])
        except ValidationError as exc:
            return preparation_error(request, exc)

    @extend_schema(request=AdapterInstallSerializer, responses={201: AdapterViewSerializer})
    def post(self, request: Request) -> Response:
        """Register another compatible private image without changing platform code."""
        body = AdapterInstallSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        try:
            result = install_preparation_adapter(
                preparation_actor(request),
                body.validated_data["grant_id"],
                body.validated_data["manifest"],
                audit=preparation_request_audit(request),
            )
        except ValidationError as exc:
            return preparation_error(request, exc)
        return Response(asdict(result), status=201)


class PreparationAdapterStateView(APIView):
    """Disable or retire an installed version while retaining its pinned history."""

    permission_classes = PreparationAdapterListCreateView.permission_classes

    @extend_schema(request=AdapterStateSerializer, responses=AdapterViewSerializer)
    def post(self, request: Request, adapter_id: UUID) -> Response:
        """Lifecycle authority remains independent of cloud-grant administration."""
        body = AdapterStateSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        try:
            result = set_preparation_adapter_state(
                preparation_actor(request),
                adapter_id,
                body.validated_data["state"],
                audit=preparation_request_audit(request),
            )
        except ValidationError as exc:
            return preparation_error(request, exc)
        return Response(asdict(result))


class AdapterGrantViewSerializer(serializers.Serializer):
    """Select existing authority without returning its private cloud configuration."""

    id = serializers.UUIDField()
    active = serializers.BooleanField()
    verified_at = serializers.DateTimeField(allow_null=True)


class PreparationAdapterGrantListView(APIView):
    """Grant selection is read-only; cloud authority is installed separately."""

    permission_classes = PreparationAdapterListCreateView.permission_classes

    @extend_schema(responses=AdapterGrantViewSerializer(many=True))
    def get(self, request: Request) -> Response:
        try:
            rows = list_preparation_adapter_grants(preparation_actor(request))
        except ValidationError as exc:
            return preparation_error(request, exc)
        return Response(AdapterGrantViewSerializer(rows, many=True).data)
