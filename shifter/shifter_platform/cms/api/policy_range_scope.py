"""Prepared principal-aware adapters retain the incumbent range-scope contract."""

from uuid import UUID

from django.db.models import QuerySet
from drf_spectacular.utils import extend_schema
from rest_framework.authentication import SessionAuthentication
from rest_framework.exceptions import NotFound
from rest_framework.request import Request
from rest_framework.response import Response

from cms import services
from cms.api.range_scope import (
    _SCOPE_ERROR_MESSAGES,
    _SCOPE_ERROR_STATUS,
    RangeWorkspaceRebindRequestSerializer,
    RangeWorkspaceRebindResultSerializer,
    RangeWorkspaceRebindView,
    WorkspaceRangeScopeListView,
)
from cms.exceptions import RangeScopeAdminError
from cms.models import RangeInstance
from shared.api.closed_serializer import ClosedSerializer
from shared.api.errors import api_error_response
from shared.api.permissions import IsAuthenticatedSessionOrApiToken
from shared.api.principals import authenticated_credential
from shared.api.strict_json import ClosedJSONParser
from shared.api_tokens.authentication import ApiTokenAuthentication
from shared.audit import request_audit
from shared.authorization import configured_authorization_provider


class PolicyRangeWorkspaceCommandSerializer(RangeWorkspaceRebindRequestSerializer, ClosedSerializer):
    """The target UUID is the only client-controlled scope datum."""


class PolicyWorkspaceRangeScopeListView(WorkspaceRangeScopeListView):
    """Replace admission and the query gate; keep pagination and aggregate hints."""

    authentication_classes = [ApiTokenAuthentication, SessionAuthentication]
    permission_classes = [IsAuthenticatedSessionOrApiToken]

    def get_queryset(self) -> QuerySet[RangeInstance]:
        try:
            return services.policy_list_range_scope_bindings(
                authenticated_credential(self.request),
                configured_authorization_provider(),
                workspace_uuid=self.kwargs["workspace_uuid"],
            )
        except RangeScopeAdminError as exc:
            raise NotFound("Workspace unavailable") from exc


class PolicyRangeWorkspaceRebindView(RangeWorkspaceRebindView):
    """Owning service authorizes source and destination, never a staff fallback."""

    authentication_classes = [ApiTokenAuthentication, SessionAuthentication]
    permission_classes = [IsAuthenticatedSessionOrApiToken]
    parser_classes = [ClosedJSONParser]

    @extend_schema(
        request=PolicyRangeWorkspaceCommandSerializer,
        responses=RangeWorkspaceRebindResultSerializer,
        operation_id="api_v1_policy_range_workspace_rebind",
    )
    def post(self, request: Request, request_id: UUID) -> Response:
        command = PolicyRangeWorkspaceCommandSerializer(data=request.data)
        command.is_valid(raise_exception=True)
        actor = authenticated_credential(request)
        try:
            result = services.policy_rebind_range_workspace(
                actor,
                configured_authorization_provider(),
                request_id=request_id,
                target_workspace_uuid=command.validated_data["target_workspace_uuid"],
                audit=request_audit(request, credential=actor),
            )
        except RangeScopeAdminError as exc:
            return api_error_response(
                code=exc.kind.value,
                message=_SCOPE_ERROR_MESSAGES[exc.kind],
                status_code=_SCOPE_ERROR_STATUS[exc.kind],
                request=request,
            )
        return Response(RangeWorkspaceRebindResultSerializer(result).data)
