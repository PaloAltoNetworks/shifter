"""Canonical RAES catalog and package-ingestion API views."""

from __future__ import annotations

from typing import Any

from django.contrib.auth.models import User
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from cms.api.permissions import CMS_READ_PERMISSIONS, CMS_WRITE_PERMISSIONS, cms_actor_user
from cms.api.serializers import (
    CatalogEntrySerializer,
    PackRegistrationResultSerializer,
    PackRegistrationSerializer,
    ScenarioDetailSerializer,
    ScenarioMetadataStateSerializer,
    ScenarioMetadataUpdateSerializer,
    ScenarioRealizabilitySerializer,
)
from cms.exceptions import CMSError
from cms.scenario_editor._common import ScenarioEditorError
from cms.scenario_editor._metadata import update_metadata
from cms.scenarios import catalog_presentation
from cms.scenarios import realizability as scenario_realizability
from cms.scenarios.registry import get_catalog_entry
from cms.services import PackRegistrationRequest, register_pack
from shared.api.errors import api_error_response
from shared.audit import get_request_id


def _actor_user(request: Request) -> User:
    """Return the CMS actor after permissions have admitted the request."""
    user = cms_actor_user(request)
    if user is None:
        raise AssertionError("CMS actor unavailable after permission check")
    return user


def _not_found(request: Request, message: str = "Scenario not found") -> Response:
    """Return the shared bounded 404 response for a missing catalog source."""
    return api_error_response(code="not_found", message=message, status_code=status.HTTP_404_NOT_FOUND, request=request)


def _raes_detail_payload(scenario_id: str) -> dict[str, Any] | None:
    """Build the read-only Scenario Catalog projection for one RAES source."""
    entry = catalog_presentation.get_catalog_presentation(scenario_id)
    if entry is None:
        return None
    return {
        "id": entry["id"],
        "name": entry["name"],
        "scenario_type": "raes",
        "source": "raes",
        "enabled": bool(entry.get("enabled", True)),
        "staff_only": bool(entry.get("staff_only", False)),
        "launchable": bool(entry.get("launchable", False)),
        "raes": entry.get("raes"),
    }


class CatalogListView(APIView):
    """List the canonical RAES-backed catalog projection."""

    permission_classes = CMS_READ_PERMISSIONS

    @extend_schema(responses=CatalogEntrySerializer(many=True))
    def get(self, request: Request) -> Response:
        return Response(CatalogEntrySerializer(catalog_presentation.list_catalog_presentations(), many=True).data)


class CatalogDetailView(APIView):
    """Return one canonical RAES-backed catalog projection."""

    permission_classes = CMS_READ_PERMISSIONS

    @extend_schema(responses=CatalogEntrySerializer)
    def get(self, request: Request, scenario_id: str) -> Response:
        entry = catalog_presentation.get_catalog_presentation(scenario_id)
        if entry is None:
            return _not_found(request, "Catalog entry not found")
        return Response(CatalogEntrySerializer(entry).data)


class PackRegisterView(APIView):
    """Register an untrusted pack through the uniform ingestion service."""

    permission_classes = CMS_WRITE_PERMISSIONS

    @extend_schema(request=PackRegistrationSerializer, responses={201: PackRegistrationResultSerializer})
    def post(self, request: Request) -> Response:
        serializer = PackRegistrationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            result = register_pack(
                user=_actor_user(request),
                request=PackRegistrationRequest(
                    scenario_id=data["scenario_id"],
                    source_kind=data["source_kind"],
                    contract_kind=data["contract_kind"],
                    contract_profile=data["contract_profile"],
                    package_ref=data["package_ref"],
                    package_version=data["package_version"],
                    package_digest=data["package_digest"],
                    expected_package_digest=data["expected_package_digest"],
                    lock_ref=data["lock_ref"],
                    lock_digest=data["lock_digest"],
                    provenance=data["provenance"],
                ),
                request_id=get_request_id(request._request),
            )
        except CMSError as exc:
            return api_error_response(
                code="invalid", message=str(exc), status_code=status.HTTP_400_BAD_REQUEST, request=request
            )
        return Response(
            {
                "scenario_id": result.scenario_id,
                "source_kind": result.source_kind,
                "conformance_status": result.conformance_status,
            },
            status=status.HTTP_201_CREATED,
        )


class ScenarioResourceView(APIView):
    """Return a read-only RAES scenario detail projection."""

    permission_classes = CMS_READ_PERMISSIONS

    @extend_schema(responses=ScenarioDetailSerializer)
    def get(self, request: Request, scenario_id: str) -> Response:
        payload = _raes_detail_payload(scenario_id)
        if payload is None:
            return _not_found(request)
        return Response(ScenarioDetailSerializer(payload).data)


class ScenarioRealizabilityView(APIView):
    """Return the backend realizability assessment for one RAES source."""

    permission_classes = CMS_READ_PERMISSIONS

    @extend_schema(responses=ScenarioRealizabilitySerializer)
    def get(self, request: Request, scenario_id: str) -> Response:
        result = scenario_realizability.get_scenario_realizability(scenario_id)
        if result is None:
            return _not_found(request)
        return Response(ScenarioRealizabilitySerializer(result).data)


class ScenarioMetadataView(APIView):
    """Update the availability/audience overlay for a RAES package source."""

    permission_classes = CMS_WRITE_PERMISSIONS

    @extend_schema(request=ScenarioMetadataUpdateSerializer, responses=ScenarioMetadataStateSerializer)
    def patch(self, request: Request, scenario_id: str) -> Response:
        if get_catalog_entry(scenario_id) is None:
            return _not_found(request)
        serializer = ScenarioMetadataUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            metadata = update_metadata(
                _actor_user(request),
                scenario_id,
                enabled=serializer.validated_data.get("enabled"),
                staff_only=serializer.validated_data.get("staff_only"),
            )
        except ScenarioEditorError as exc:
            return api_error_response(
                code="invalid",
                message=exc.public_message,
                status_code=status.HTTP_400_BAD_REQUEST,
                request=request,
            )
        return Response(
            {
                "scenario_id": scenario_id,
                "enabled": metadata.enabled,
                "staff_only": metadata.staff_only,
            }
        )
