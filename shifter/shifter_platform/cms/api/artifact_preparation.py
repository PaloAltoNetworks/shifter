"""Explicit asynchronous preparation, separate from range creation."""

from __future__ import annotations

from dataclasses import asdict
from uuid import UUID

from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from cms.api.preparation_adapters import (
    PreparationSerializer,
    preparation_actor,
    preparation_error,
    preparation_request_audit,
)
from cms.scenarios.preparation import prepare_registered_artifact
from engine.services import cancel_artifact_preparation, get_artifact_preparation, retry_artifact_preparation
from shared.api.permissions import IsAuthenticatedSessionOrApiToken
from shared.api.principals import active_actor_user
from shared.api_tokens import scopes
from shared.api_tokens.permissions import require_scope
from shared.exceptions import ValidationError


class HasPreparationPermission(BasePermission):
    """An API token scope does not replace its owner's current role."""

    def has_permission(self, request: Request, view: APIView) -> bool:
        actor = active_actor_user(request)
        return bool(actor and actor.has_perm("engine.prepare_artifacts"))


class PreparationRequestSerializer(PreparationSerializer):
    """Identify authored intent, never cloud configuration or executable overrides."""

    scenario_id = serializers.SlugField(max_length=100)
    requirement_address = serializers.CharField(max_length=1024)
    adapter_id = serializers.UUIDField()
    specification_id = serializers.CharField(max_length=256)


class PreparationViewSerializer(serializers.Serializer):
    """Bounded progress without private recipe or worker evidence payloads."""

    id = serializers.UUIDField(allow_null=True)
    state = serializers.CharField()
    failure_code = serializers.CharField()
    cleanup_pending = serializers.BooleanField()
    reused = serializers.BooleanField()


class PreparationRequestView(APIView):
    """Request preparation before attempting ordinary launch."""

    permission_classes = [
        IsAuthenticatedSessionOrApiToken,
        HasPreparationPermission,
        require_scope(scopes.CMS_PREPARATION_READ, scopes.CMS_PREPARATION_WRITE),
    ]

    @extend_schema(request=PreparationRequestSerializer, responses={202: PreparationViewSerializer})
    def post(self, request: Request) -> Response:
        """The CMS loads the selected private pack and the engine owns the job."""
        body = PreparationRequestSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        try:
            result = prepare_registered_artifact(
                preparation_actor(request),
                **body.validated_data,
                audit=preparation_request_audit(request),
            )
        except ValidationError as exc:
            return preparation_error(request, exc)
        return Response(asdict(result), status=202)


class PreparationDetailView(APIView):
    """Inspect only the requester's preparation or explicit administrator scope."""

    permission_classes = PreparationRequestView.permission_classes

    @extend_schema(responses=PreparationViewSerializer)
    def get(self, request: Request, operation_id: UUID) -> Response:
        """Status does not expose worker credentials or private manifests."""
        try:
            result = get_artifact_preparation(preparation_actor(request), operation_id)
        except ValidationError as exc:
            return preparation_error(request, exc)
        return Response(asdict(result))


class PreparationCancelView(APIView):
    """Fence admission synchronously while cleanup continues independently."""

    permission_classes = PreparationRequestView.permission_classes

    @extend_schema(request=PreparationSerializer, responses=PreparationViewSerializer)
    def post(self, request: Request, operation_id: UUID) -> Response:
        """Cancellation cannot supply resource names or deletion instructions."""
        body = PreparationSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        try:
            result = cancel_artifact_preparation(
                preparation_actor(request),
                operation_id,
                audit=preparation_request_audit(request),
            )
        except ValidationError as exc:
            return preparation_error(request, exc)
        return Response(asdict(result))


class PreparationRetryView(APIView):
    """Restart cleaned terminal work using its original private immutable input."""

    permission_classes = PreparationRequestView.permission_classes

    @extend_schema(request=PreparationSerializer, responses={202: PreparationViewSerializer})
    def post(self, request: Request, operation_id: UUID) -> Response:
        """A retry supplies no new code, cloud grant, identities or resource names."""
        body = PreparationSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        try:
            result = retry_artifact_preparation(
                preparation_actor(request), operation_id, audit=preparation_request_audit(request)
            )
        except ValidationError as exc:
            return preparation_error(request, exc)
        return Response(asdict(result), status=202)
