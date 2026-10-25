"""Tenant administration and explicitly authorized model-source discovery."""

from dataclasses import asdict
from uuid import UUID

from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from cms.services import list_usable_model_sources
from engine.services import (
    create_model_source,
    list_model_sources,
    retire_unused_model_source_credentials,
    update_model_source,
)
from shared.api.errors import api_error_response
from shared.api.model_sources import ModelSourceRevisionField
from shared.api.permissions import IsAuthenticatedSession
from shared.api.strict_json import ClosedJSONParser
from shared.model_access import ContractError
from workspaces.services import OrganizationAuthorizationError

from .preparation_adapters import PreparationSerializer


class ModelSourceConfigurationSerializer(PreparationSerializer):
    """Editable metadata; the service validates provider-specific combinations."""

    def to_internal_value(self, data: object) -> dict[str, object]:
        from shared.model_access.sources import ModelSourceConfiguration

        try:
            ModelSourceConfiguration.model_validate(data)
        except ValueError:
            raise serializers.ValidationError("Invalid model-source configuration.") from None
        return super().to_internal_value(data)

    name = serializers.CharField(max_length=100)
    provider = serializers.ChoiceField(
        choices=["vertex-v1", "bedrock-v1", "anthropic-v1", "openai-v1", "openrouter-v1"]
    )
    authentication = serializers.ChoiceField(choices=["workload-identity", "stored-credential"])
    model = serializers.CharField(max_length=256)
    region = serializers.CharField(max_length=64)
    project = serializers.CharField(max_length=30, allow_blank=True, required=False, default="")
    principal = serializers.CharField(max_length=256, allow_blank=True, required=False, default="")
    count_region = serializers.CharField(max_length=64, allow_blank=True, required=False, default="")
    quota_identity = serializers.CharField(max_length=256)
    context_window_tokens = serializers.IntegerField(min_value=1, max_value=2_000_000)
    tokens_per_minute = serializers.IntegerField(min_value=1, max_value=2**53 - 1)
    input_price_per_million = serializers.IntegerField(min_value=0)
    output_price_per_million = serializers.IntegerField(min_value=0)
    currency = serializers.ChoiceField(choices=["AUD", "CAD", "CHF", "EUR", "GBP", "JPY", "USD"], default="USD")
    price_valid_until = serializers.DateTimeField()
    allow_organization_members = serializers.BooleanField(default=False)
    allowed_user_ids = serializers.ListField(child=serializers.IntegerField(min_value=1), max_length=256, default=list)
    upstream_provider = serializers.CharField(max_length=100, allow_blank=True, required=False, default="")


class ModelSourceWriteSerializer(PreparationSerializer):
    """Source configuration and an optional transient credential."""

    configuration = ModelSourceConfigurationSerializer()
    credential = serializers.JSONField(required=False, write_only=True)


class ModelSourceUpdateSerializer(ModelSourceWriteSerializer):
    """Revision-fenced replacement of source configuration and status."""

    expected_revision = ModelSourceRevisionField(min_value=0)
    enabled = serializers.BooleanField(default=True)


class ModelSourceViewSerializer(serializers.Serializer):
    """Public source metadata with credential presence only."""

    id = serializers.UUIDField()
    organization_uuid = serializers.UUIDField()
    revision = serializers.IntegerField()
    enabled = serializers.BooleanField()
    state = serializers.ChoiceField(choices=["pending", "ready", "failed", "retired", "disabled"])
    configuration = ModelSourceConfigurationSerializer()
    has_credential = serializers.BooleanField()


class ModelSourcePageSerializer(serializers.Serializer):
    """Collection of authorized source metadata."""

    results = ModelSourceViewSerializer(many=True)


def _error(request: Request, exc: OrganizationAuthorizationError | ContractError) -> Response:
    """Map service failures to opaque, actionable management API errors."""
    if isinstance(exc, OrganizationAuthorizationError):
        code, status, message = "source_access_denied", 403, "Organization access denied"
    else:
        code = exc.code.replace(".", "_")
        status = 409 if exc.code == "source.revision_conflict" else 400
        message = {
            "source.revision_conflict": "This source changed. Reload it before saving again.",
            "source.credential_unavailable": "The credential could not be stored. Retry with a new revision.",
            "source.credential_required": "Provide a credential for this source.",
            "source.limit_reached": "The organization has reached its model-source limit.",
            "source.credential_cleanup_pending": "Credential cleanup is pending. Retry this action to finish it.",
        }.get(exc.code, "The model source is unavailable or its configuration is invalid.")
    return api_error_response(code=code, message=message, status_code=status, request=request)


class ModelSourceListCreateView(APIView):
    """List and create sources for an administrable organization."""

    permission_classes = [IsAuthenticatedSession]
    parser_classes = [ClosedJSONParser]

    @extend_schema(responses=ModelSourcePageSerializer)
    def get(self, request: Request, organization_uuid: UUID) -> Response:
        try:
            return Response({"results": [asdict(row) for row in list_model_sources(request.user, organization_uuid)]})
        except OrganizationAuthorizationError as exc:
            return _error(request, exc)

    @extend_schema(request=ModelSourceWriteSerializer, responses={201: ModelSourceViewSerializer})
    def post(self, request: Request, organization_uuid: UUID) -> Response:
        body = ModelSourceWriteSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        try:
            return Response(
                asdict(create_model_source(request.user, organization_uuid, **body.validated_data)), status=201
            )
        except (OrganizationAuthorizationError, ContractError) as exc:
            return _error(request, exc)


class ModelSourceDetailView(APIView):
    """Replace a source only at its expected revision."""

    permission_classes = [IsAuthenticatedSession]
    parser_classes = [ClosedJSONParser]

    @extend_schema(request=ModelSourceUpdateSerializer, responses=ModelSourceViewSerializer)
    def put(self, request: Request, organization_uuid: UUID, source_id: UUID) -> Response:
        body = ModelSourceUpdateSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        try:
            return Response(
                asdict(update_model_source(request.user, organization_uuid, source_id, **body.validated_data))
            )
        except (OrganizationAuthorizationError, ContractError) as exc:
            return _error(request, exc)


class UsableModelSourceListView(APIView):
    """List sources explicitly available to the current actor."""

    permission_classes = [IsAuthenticatedSession]

    @extend_schema(responses=ModelSourcePageSerializer)
    def get(self, request: Request, organization_uuid: UUID) -> Response:
        try:
            return Response(
                {"results": [asdict(row) for row in list_usable_model_sources(request.user, organization_uuid)]}
            )
        except OrganizationAuthorizationError as exc:
            return _error(request, exc)


class CredentialRetirementSerializer(serializers.Serializer):
    """Number of obsolete credential versions retired."""

    retired = serializers.IntegerField(min_value=0)


class ModelSourceCredentialRetirementView(APIView):
    """Retire obsolete credentials after checking live references."""

    permission_classes = [IsAuthenticatedSession]
    parser_classes = [ClosedJSONParser]

    @extend_schema(request=PreparationSerializer, responses=CredentialRetirementSerializer)
    def post(self, request: Request, organization_uuid: UUID, source_id: UUID) -> Response:
        body = PreparationSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        try:
            return Response(
                {"retired": retire_unused_model_source_credentials(request.user, organization_uuid, source_id)}
            )
        except (OrganizationAuthorizationError, ContractError) as exc:
            return _error(request, exc)


class ModelSourceUserSerializer(serializers.Serializer):
    """Tenant directory identity for an explicit source-use grant."""

    id = serializers.IntegerField()
    name = serializers.CharField()
    username = serializers.CharField()


class ModelSourceUserPageSerializer(serializers.Serializer):
    """Bounded directory results and continuation indicator."""

    has_next = serializers.BooleanField()
    results = ModelSourceUserSerializer(many=True)


class ModelSourceUserQuerySerializer(PreparationSerializer):
    """Search and paging inputs for the tenant directory."""

    search = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")
    page = serializers.IntegerField(min_value=1, max_value=1000000, default=1)


class ModelSourceUsersView(APIView):
    """Search tenant members eligible for explicit source-use grants."""

    permission_classes = [IsAuthenticatedSession]

    @extend_schema(parameters=[ModelSourceUserQuerySerializer], responses=ModelSourceUserPageSerializer)
    def get(self, request: Request, organization_uuid: UUID) -> Response:
        from workspaces.services import list_model_source_users

        query = ModelSourceUserQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        try:
            return Response(list_model_source_users(request.user, organization_uuid, **query.validated_data))
        except OrganizationAuthorizationError as exc:
            return _error(request, exc)
