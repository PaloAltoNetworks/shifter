"""Tenant model-policy administration of existing ranges, with explicit CAS."""

from uuid import UUID

from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from cms.api.preparation_adapters import PreparationSerializer
from cms.services import change_range_model_sources, get_range_model_sources, revoke_range_model_sources
from shared.api.errors import api_error_response
from shared.api.model_access import ModelAccessAPIView
from shared.api.model_sources import ModelSourceRevisionField, ModelSourceSelectionField, ModelSourceSelectionSerializer
from shared.api.permissions import IsAuthenticatedSession, IsAuthenticatedSessionOrApiToken
from shared.api.strict_json import ClosedJSONParser
from shared.api_tokens.permissions import require_scope
from shared.api_tokens.scopes import MODEL_ACCESS_RANGE_WRITE
from shared.model_access import ContractError
from workspaces.services import OrganizationAuthorizationError, WorkspaceAuthorizationError


class RangeModelSourcesWriteSerializer(PreparationSerializer):
    """Revision-fenced source selection for an existing range."""

    expected_revision = ModelSourceRevisionField(min_value=0)
    selection = ModelSourceSelectionField()


class ModelAssignmentSerializer(serializers.Serializer):
    """Effective provider assignment for a workload alias."""

    workload = serializers.CharField()
    logical_alias = serializers.CharField()
    provider = serializers.CharField()
    model = serializers.CharField()
    region = serializers.CharField()


class ModelPolicyRuntimeSerializer(serializers.Serializer):
    """Runtime availability and effective model assignments."""

    state = serializers.ChoiceField(choices=["active", "refresh_pending", "unavailable"])
    assignments = ModelAssignmentSerializer(many=True)


class RangeModelSourcesSerializer(serializers.Serializer):
    """Range source policy and its current runtime status."""

    request_id = serializers.UUIDField()
    workspace = serializers.UUIDField()
    scenario = serializers.CharField()
    revision = serializers.IntegerField()
    selection = ModelSourceSelectionSerializer()
    error = serializers.CharField()
    runtime = ModelPolicyRuntimeSerializer()


def source_policy_error(
    request: Request, exc: ContractError | OrganizationAuthorizationError | WorkspaceAuthorizationError
) -> Response:
    """Report stale revisions separately from unavailable range authority."""
    conflict = isinstance(exc, ContractError) and exc.code == "source.revision_conflict"
    return api_error_response(
        code="source_revision_conflict" if conflict else "range_model_sources_unavailable",
        message="Model sources changed. Reload this range before saving."
        if conflict
        else "Range model sources are unavailable.",
        status_code=409 if conflict else 403,
        request=request,
    )


class RangeModelSourcesView(APIView):
    """Read or replace model sources under range administration authority."""

    permission_classes = [IsAuthenticatedSession]
    parser_classes = [ClosedJSONParser]

    @extend_schema(responses=RangeModelSourcesSerializer)
    def get(self, request: Request, request_id: UUID) -> Response:
        try:
            return Response(get_range_model_sources(request.user, request_id=request_id))
        except (WorkspaceAuthorizationError, OrganizationAuthorizationError, ContractError) as exc:
            return source_policy_error(request, exc)

    @extend_schema(
        request=RangeModelSourcesWriteSerializer,
        responses={200: RangeModelSourcesSerializer, 202: RangeModelSourcesSerializer},
    )
    def put(self, request: Request, request_id: UUID) -> Response:
        serializer = RangeModelSourcesWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            result = change_range_model_sources(request.user, request_id=request_id, **serializer.validated_data)
            return Response(result, status=202 if result["error"] else 200)
        except (WorkspaceAuthorizationError, OrganizationAuthorizationError, ContractError) as exc:
            return source_policy_error(request, exc)


class ModelRangeSummarySerializer(serializers.Serializer):
    """Range identity and source policy status for tenant administration."""

    request_id = serializers.UUIDField()
    scenario = serializers.CharField()
    status = serializers.CharField()
    revision = serializers.IntegerField()
    error = serializers.CharField()


class ModelRangePageSerializer(serializers.Serializer):
    """Paged tenant ranges with source policy metadata."""

    count = serializers.IntegerField()
    page = serializers.IntegerField()
    has_next = serializers.BooleanField()
    results = ModelRangeSummarySerializer(many=True)


class ModelRangePageQuerySerializer(PreparationSerializer):
    """Bounded page selector for tenant ranges."""

    page = serializers.IntegerField(min_value=1, max_value=1000000, default=1)


class OrganizationModelRangesView(APIView):
    """List model-enabled ranges in administrable tenant workspaces."""

    permission_classes = [IsAuthenticatedSession]

    @extend_schema(parameters=[ModelRangePageQuerySerializer], responses=ModelRangePageSerializer)
    def get(self, request: Request, organization_uuid: UUID) -> Response:
        from cms.services import list_organization_model_ranges

        query = ModelRangePageQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        try:
            return Response(
                list_organization_model_ranges(
                    request.user, organization_uuid=organization_uuid, **query.validated_data
                )
            )
        except (OrganizationAuthorizationError, WorkspaceAuthorizationError) as exc:
            return source_policy_error(request, exc)


class RangeModelSourcesRevokeView(ModelAccessAPIView):
    """Revoke a range's model grants under range-administration authority (M09, #2126).

    Session/CSRF or a ``model-access:range:write`` scoped token; the service
    re-checks workspace authority and fences the current generation's grants and
    dispatch leases with real-actor audit. Revocation never proves provider
    cancellation, refunds spend or releases outstanding liabilities.
    """

    permission_classes = [
        IsAuthenticatedSessionOrApiToken,
        require_scope(MODEL_ACCESS_RANGE_WRITE, MODEL_ACCESS_RANGE_WRITE),
    ]

    @extend_schema(request=None, responses=RangeModelSourcesSerializer)
    def post(self, request: Request, request_id: UUID) -> Response:
        actor = self.actor(request)
        if actor is None:
            return api_error_response(code="permission_denied", message="Forbidden", status_code=403, request=request)
        try:
            return Response(revoke_range_model_sources(actor, request_id=request_id))
        except (WorkspaceAuthorizationError, OrganizationAuthorizationError, ContractError) as exc:
            return source_policy_error(request, exc)
