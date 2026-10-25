"""Session-only, tenant-scoped model choices for range and event forms."""

from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from cms.api.model_sources import ModelSourceViewSerializer
from cms.api.preparation_adapters import PreparationSerializer
from cms.services import model_source_alias_options
from shared.api.errors import api_error_response
from shared.api.permissions import IsAuthenticatedSession
from shared.model_access import ContractError
from workspaces.services import (
    OrganizationAuthorizationError,
    WorkspaceAuthorizationError,
    WorkspaceOperation,
    authorize_workspace,
    list_actor_workspace_contexts,
)


class SourceOptionsQuerySerializer(PreparationSerializer):
    """Workspace, scenario, and purpose filters for available source choices."""

    scenario = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    workspace = serializers.UUIDField(required=False)
    purpose = serializers.ChoiceField(choices=["range", "ctf", "admin"], default="range")


class SourceWorkspaceSerializer(serializers.Serializer):
    """Workspace identity displayed alongside tenant source options."""

    uuid = serializers.UUIDField()
    name = serializers.CharField()
    organization_name = serializers.CharField()
    is_personal = serializers.BooleanField()


class AliasSourceOptionsSerializer(serializers.Serializer):
    """Compatible sources and mixing policy for one logical alias."""

    logical_alias = serializers.CharField()
    multiple_allowed = serializers.BooleanField()
    sources = ModelSourceViewSerializer(many=True)


class SourceOptionsSerializer(serializers.Serializer):
    """Authorized workspaces and scenario-specific source choices."""

    workspaces = SourceWorkspaceSerializer(many=True)
    workspace = serializers.UUIDField(allow_null=True)
    aliases = AliasSourceOptionsSerializer(many=True)
    available = serializers.BooleanField()


class ModelSourceOptionsView(APIView):
    """Discover source choices under the current session authority."""

    permission_classes = [IsAuthenticatedSession]

    @extend_schema(parameters=[SourceOptionsQuerySerializer], responses=SourceOptionsSerializer)
    def get(self, request: Request) -> Response:
        query = SourceOptionsQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        values = query.validated_data
        operation = (
            WorkspaceOperation.USE_CTF_COMMUNICATIONS if values["purpose"] == "ctf" else WorkspaceOperation.LAUNCH_RANGE
        )
        contexts = [item for item in list_actor_workspace_contexts(request.user) if operation in item.capabilities]
        selected = values.get("workspace") or next((item.workspace_uuid for item in contexts if item.is_personal), None)
        aliases: list[dict[str, object]] = []
        available = False
        try:
            if selected:
                if values["purpose"] == "admin":
                    from workspaces.services import authorize_model_source_workspace

                    authority = authorize_model_source_workspace(request.user, workspace_uuid=selected)
                else:
                    authority = authorize_workspace(request.user, selected, operation)
                aliases, available = model_source_alias_options(
                    request.user, authority.organization_uuid, values["scenario"]
                )
        except (OrganizationAuthorizationError, WorkspaceAuthorizationError, ContractError, ValueError):
            return api_error_response(
                code="source_options_unavailable",
                message="Model sources are unavailable for this workspace and scenario.",
                status_code=403,
                request=request,
            )
        return Response(
            {
                "workspaces": [
                    {
                        "uuid": item.workspace_uuid,
                        "name": item.workspace_name,
                        "organization_name": item.organization.name,
                        "is_personal": item.is_personal,
                    }
                    for item in contexts
                ],
                "workspace": selected,
                "aliases": aliases,
                "available": available,
            }
        )
