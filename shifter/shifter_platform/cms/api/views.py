"""DRF views for the canonical CMS API."""

from __future__ import annotations

import logging

from django.contrib.auth.models import User
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from cms.api.permissions import CMS_READ_PERMISSIONS, CMS_WRITE_PERMISSIONS, cms_actor_user
from cms.api.serializers import CatalogEntrySerializer, YAMLContentSerializer
from cms.scenario_editor import services as scenario_services
from cms.scenarios import catalog_presentation
from shared.api.errors import api_error_response

logger = logging.getLogger(__name__)


def _actor_user(request: Request) -> User:
    """Return the CMS actor after permissions have admitted the request."""
    user = cms_actor_user(request)
    if user is None:
        raise AssertionError("CMS actor unavailable after permission check")
    return user


class CatalogListView(APIView):
    """List catalog entries as read-only metadata (staff-review projection).

    Returns every catalog entry (YAML defaults, DB customs, and ACES
    package-backed entries) with allowlisted read-only fields. This is the
    unfiltered staff-review projection — like the scenario-editor list — so a
    CMS authoring actor can inspect disabled / staff-only entries. User-facing
    and launch surfaces apply access/launchability filtering in the registry.
    """

    permission_classes = CMS_READ_PERMISSIONS

    def get(self, request: Request) -> Response:
        """Return all catalog entries as read-only presentation DTOs."""
        entries = catalog_presentation.list_catalog_presentations()
        return Response(CatalogEntrySerializer(entries, many=True).data)


class CatalogDetailView(APIView):
    """Return a single catalog entry's read-only metadata, or 404."""

    permission_classes = CMS_READ_PERMISSIONS

    def get(self, request: Request, scenario_id: str) -> Response:
        """Return one catalog entry's read-only presentation DTO."""
        entry = catalog_presentation.get_catalog_presentation(scenario_id)
        if entry is None:
            return api_error_response(
                code="not_found",
                message="Catalog entry not found",
                status_code=status.HTTP_404_NOT_FOUND,
                request=request,
            )
        return Response(CatalogEntrySerializer(entry).data)


class YAMLValidateView(APIView):
    """Validate scenario YAML without saving it."""

    permission_classes = CMS_READ_PERMISSIONS

    def post(self, request: Request) -> Response:
        """Return a domain validation result for YAML editor callers."""
        serializer = YAMLContentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        parsed, errors = scenario_services.validate_yaml(serializer.validated_data["yaml_content"])
        if errors:
            return Response({"valid": False, "errors": errors, "definition": None})
        return Response({"valid": True, "errors": [], "definition": parsed})


class YAMLScenarioCreateView(APIView):
    """Create a custom scenario from YAML content."""

    permission_classes = CMS_WRITE_PERMISSIONS

    def post(self, request: Request) -> Response:
        """Create a custom scenario through the scenario-editor service layer."""
        serializer = YAMLContentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = _actor_user(request)
        fields, errors = scenario_services.create_scenario_from_yaml_post(
            user, serializer.validated_data["yaml_content"]
        )
        if errors or fields is None:
            return api_error_response(
                code="invalid",
                message="Invalid scenario YAML",
                status_code=status.HTTP_400_BAD_REQUEST,
                details={"errors": errors},
                request=request,
            )
        return Response({"scenario_id": fields.scenario_id, "name": fields.name}, status=status.HTTP_201_CREATED)
