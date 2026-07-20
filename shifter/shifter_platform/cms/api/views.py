"""DRF views for the canonical CMS API.

The scenario-editor views wrap the already-audited
``cms.scenario_editor.services`` facade so the platform SPA can browse, author,
validate, and save scenarios through ``/api/v1/cms/`` without ever calling the
legacy ``/scenario-editor/`` Django form/action routes. Domain correctness
(schema validation, default-scenario protection, soft delete, audit) lives in
the service layer; these views own only HTTP shape, permission enforcement, and
the source-capability projection the editor renders from.
"""

from __future__ import annotations

import logging
from typing import Any

from django.contrib.auth.models import User
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from cms.api.permissions import CMS_READ_PERMISSIONS, CMS_WRITE_PERMISSIONS, cms_actor_user
from cms.api.serializers import (
    CatalogEntrySerializer,
    PackRegistrationResultSerializer,
    PackRegistrationSerializer,
    ScenarioCloneSerializer,
    ScenarioCreatedSerializer,
    ScenarioCreateSerializer,
    ScenarioDetailSerializer,
    ScenarioExportSerializer,
    ScenarioMetadataStateSerializer,
    ScenarioMetadataUpdateSerializer,
    ScenarioUpdateSerializer,
    YAMLContentSerializer,
    YAMLValidationResultSerializer,
)
from cms.exceptions import CMSError
from cms.scenario_editor import services as scenario_services
from cms.scenario_editor.services import ScenarioEditorError
from cms.scenarios import catalog_presentation
from cms.scenarios.catalog_presentation import scenario_source
from cms.scenarios.registry import get_catalog_entry, get_scenario_detail
from cms.services import PackRegistrationRequest, register_pack
from shared.api.errors import api_error_response
from shared.audit import get_request_id

logger = logging.getLogger(__name__)

_NOT_FOUND = "Scenario not found"


def _actor_user(request: Request) -> User:
    """Return the CMS actor after permissions have admitted the request."""
    user = cms_actor_user(request)
    if user is None:
        raise AssertionError("CMS actor unavailable after permission check")
    return user


def _service_error(request: Request, exc: ScenarioEditorError) -> Response:
    """Render a scenario-editor service error as the shared 400 envelope."""
    return api_error_response(
        code="invalid",
        message=exc.public_message,
        status_code=status.HTTP_400_BAD_REQUEST,
        request=request,
    )


def _not_found(request: Request) -> Response:
    """Render the shared 404 envelope for an unknown scenario id."""
    return api_error_response(
        code="not_found",
        message=_NOT_FOUND,
        status_code=status.HTTP_404_NOT_FOUND,
        request=request,
    )


def _classify(scenario_type: str, is_default: bool) -> tuple[str, bool, bool, bool]:
    """Return (source, editable, deletable, exportable) capability flags.

    Custom demo scenarios are fully editable; built-in YAML defaults are
    code-managed (clone/export/metadata only); ACES and CTF entries are
    read-only in this editor. ``source`` comes from the single server-owned
    classifier (``catalog_presentation.scenario_source``) so the catalog list,
    the detail projection, and the SPA never derive it independently.
    """
    source = scenario_source(scenario_type, is_default)
    editable = source == "custom" and scenario_type == "demo"
    deletable = source == "custom"
    exportable = scenario_type == "demo"
    return source, editable, deletable, exportable


def _structural_detail_payload(detail: dict[str, Any]) -> dict[str, Any]:
    """Build the editor detail payload from a registry structural detail dict."""
    scenario_type = detail.get("scenario_type", "demo")
    is_default = bool(detail.get("is_default", False))
    source, editable, deletable, exportable = _classify(scenario_type, is_default)
    return {
        "id": detail["id"],
        "name": detail["name"],
        "description": detail.get("description", ""),
        "scenario_type": scenario_type,
        "source": source,
        "is_default": is_default,
        "enabled": bool(detail.get("enabled", True)),
        "staff_only": bool(detail.get("staff_only", False)),
        "launchable": bool(detail.get("launchable", True)),
        "editable": editable,
        "deletable": deletable,
        "exportable": exportable,
        "ngfw": bool(detail.get("ngfw", False)),
        "instances": detail.get("instances", []),
        "subnets": detail.get("subnets", []),
        "aces": None,
    }


def _aces_detail_payload(scenario_id: str) -> dict[str, Any] | None:
    """Build a read-only editor detail payload for an ACES catalog entry."""
    entry = catalog_presentation.get_catalog_presentation(scenario_id)
    if entry is None:
        return None
    return {
        "id": entry["id"],
        "name": entry["name"],
        "description": "",
        "scenario_type": entry.get("scenario_type", "aces"),
        "source": "aces",
        "is_default": bool(entry.get("is_default", False)),
        "enabled": bool(entry.get("enabled", True)),
        "staff_only": bool(entry.get("staff_only", False)),
        "launchable": bool(entry.get("launchable", False)),
        "editable": False,
        "deletable": False,
        "exportable": False,
        "ngfw": False,
        "instances": [],
        "subnets": [],
        "aces": entry.get("aces"),
    }


class CatalogListView(APIView):
    """List catalog entries as read-only metadata (staff-review projection).

    Returns every catalog entry (YAML defaults, DB customs, and ACES
    package-backed entries) with allowlisted read-only fields. This is the
    unfiltered staff-review projection — like the scenario-editor list — so a
    CMS authoring actor can inspect disabled / staff-only entries. User-facing
    and launch surfaces apply access/launchability filtering in the registry.
    """

    permission_classes = CMS_READ_PERMISSIONS

    @extend_schema(responses=CatalogEntrySerializer(many=True))
    def get(self, request: Request) -> Response:
        """Return all catalog entries as read-only presentation DTOs."""
        entries = catalog_presentation.list_catalog_presentations()
        return Response(CatalogEntrySerializer(entries, many=True).data)


class CatalogDetailView(APIView):
    """Return a single catalog entry's read-only metadata, or 404."""

    permission_classes = CMS_READ_PERMISSIONS

    @extend_schema(responses=CatalogEntrySerializer)
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

    @extend_schema(request=YAMLContentSerializer, responses=YAMLValidationResultSerializer)
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

    @extend_schema(request=YAMLContentSerializer, responses={201: ScenarioCreatedSerializer})
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


class PackRegisterView(APIView):
    """Register a content pack through the uniform ingestion service (#1578).

    The authenticated operator entrypoint onto ``cms.services.register_pack``. It
    is source-agnostic and entitlement-blind: the WRITE-scope authorization gate
    decides who may register content, and no entitlement/acquisition check is
    added. The pack is validated as foreign input by the service before
    persistence; failures return the shared error envelope.
    """

    permission_classes = CMS_WRITE_PERMISSIONS

    @extend_schema(request=PackRegistrationSerializer, responses={201: PackRegistrationResultSerializer})
    def post(self, request: Request) -> Response:
        """Validate and register a pack, returning a bounded 201 summary."""
        serializer = PackRegistrationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = _actor_user(request)
        data = serializer.validated_data
        registration = PackRegistrationRequest(
            scenario_id=data["scenario_id"],
            source_kind=data["source_kind"],
            contract_kind=data["contract_kind"],
            contract_profile=data["contract_profile"],
            package_ref=data["package_ref"],
            package_version=data["package_version"],
            package_digest=data["package_digest"],
            lock_ref=data["lock_ref"],
            lock_digest=data["lock_digest"],
            provenance=data["provenance"],
        )
        try:
            result = register_pack(
                user=user,
                request=registration,
                request_id=get_request_id(request._request),
            )
        except CMSError as exc:
            return api_error_response(
                code="invalid",
                message=str(exc),
                status_code=status.HTTP_400_BAD_REQUEST,
                request=request,
            )
        return Response(
            {
                "scenario_id": result.scenario_id,
                "source_kind": result.source_kind,
                "conformance_status": result.conformance_status,
            },
            status=status.HTTP_201_CREATED,
        )


class ScenarioCreateView(APIView):
    """Create a custom scenario from a structured (non-YAML) definition."""

    permission_classes = CMS_WRITE_PERMISSIONS

    @extend_schema(request=ScenarioCreateSerializer, responses={201: ScenarioCreatedSerializer})
    def post(self, request: Request) -> Response:
        """Create a custom scenario through the scenario-editor service layer."""
        serializer = ScenarioCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = _actor_user(request)
        try:
            scenario = scenario_services.create_scenario(
                user,
                scenario_id=serializer.validated_data["scenario_id"],
                name=serializer.validated_data["name"],
                description=serializer.validated_data["description"],
                definition=serializer.definition(),
            )
        except ScenarioEditorError as exc:
            return _service_error(request, exc)
        return Response(
            {"scenario_id": scenario.scenario_id, "name": scenario.name},
            status=status.HTTP_201_CREATED,
        )


class ScenarioResourceView(APIView):
    """Retrieve, update, or soft-delete a single scenario.

    ``GET`` needs only the CMS read scope; ``PATCH`` / ``DELETE`` need the write
    scope, so permissions are resolved per method.
    """

    def get_permissions(self) -> list[BasePermission]:
        """Read scope for retrieval; write scope for mutations."""
        classes = CMS_READ_PERMISSIONS if self.request.method == "GET" else CMS_WRITE_PERMISSIONS
        return [permission() for permission in classes]

    @extend_schema(responses=ScenarioDetailSerializer)
    def get(self, request: Request, scenario_id: str) -> Response:
        """Return full structural detail (or a read-only ACES projection)."""
        payload: dict[str, Any] | None
        try:
            payload = _structural_detail_payload(get_scenario_detail(scenario_id))
        except ValueError:
            payload = _aces_detail_payload(scenario_id)
        if payload is None:
            return _not_found(request)
        return Response(ScenarioDetailSerializer(payload).data)

    @extend_schema(request=ScenarioUpdateSerializer, responses=ScenarioDetailSerializer)
    def patch(self, request: Request, scenario_id: str) -> Response:
        """Replace a custom scenario's definition through the service layer."""
        if get_catalog_entry(scenario_id) is None:
            return _not_found(request)
        serializer = ScenarioUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = _actor_user(request)
        try:
            scenario_services.update_scenario(
                user,
                scenario_id,
                name=serializer.validated_data["name"],
                description=serializer.validated_data["description"],
                definition=serializer.definition(),
            )
        except ScenarioEditorError as exc:
            return _service_error(request, exc)
        return Response(ScenarioDetailSerializer(_structural_detail_payload(get_scenario_detail(scenario_id))).data)

    @extend_schema(responses={204: None})
    def delete(self, request: Request, scenario_id: str) -> Response:
        """Soft-delete a custom scenario through the service layer."""
        if get_catalog_entry(scenario_id) is None:
            return _not_found(request)
        user = _actor_user(request)
        try:
            scenario_services.delete_scenario(user, scenario_id)
        except ScenarioEditorError as exc:
            return _service_error(request, exc)
        return Response(status=status.HTTP_204_NO_CONTENT)


class ScenarioCloneView(APIView):
    """Clone an existing scenario into a new custom scenario."""

    permission_classes = CMS_WRITE_PERMISSIONS

    @extend_schema(request=ScenarioCloneSerializer, responses={201: ScenarioCreatedSerializer})
    def post(self, request: Request, scenario_id: str) -> Response:
        """Clone the source scenario through the service layer."""
        serializer = ScenarioCloneSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = _actor_user(request)
        try:
            scenario = scenario_services.clone_scenario(
                user,
                scenario_id,
                new_scenario_id=serializer.validated_data["new_scenario_id"],
                new_name=serializer.validated_data.get("new_name") or None,
            )
        except ScenarioEditorError as exc:
            return _service_error(request, exc)
        return Response(
            {"scenario_id": scenario.scenario_id, "name": scenario.name},
            status=status.HTTP_201_CREATED,
        )


class ScenarioMetadataView(APIView):
    """Update a scenario's availability/audience overlay (enabled/staff_only)."""

    permission_classes = CMS_WRITE_PERMISSIONS

    @extend_schema(request=ScenarioMetadataUpdateSerializer, responses=ScenarioMetadataStateSerializer)
    def patch(self, request: Request, scenario_id: str) -> Response:
        """Apply an explicit desired-state metadata update through the service layer."""
        if get_catalog_entry(scenario_id) is None:
            return _not_found(request)
        serializer = ScenarioMetadataUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = _actor_user(request)
        try:
            metadata = scenario_services.update_metadata(
                user,
                scenario_id,
                enabled=serializer.validated_data.get("enabled"),
                staff_only=serializer.validated_data.get("staff_only"),
            )
        except ScenarioEditorError as exc:
            return _service_error(request, exc)
        return Response(
            {
                "scenario_id": scenario_id,
                "enabled": metadata.enabled,
                "staff_only": metadata.staff_only,
            }
        )


class ScenarioExportView(APIView):
    """Export a scenario as YAML text."""

    permission_classes = CMS_READ_PERMISSIONS

    @extend_schema(responses=ScenarioExportSerializer)
    def get(self, request: Request, scenario_id: str) -> Response:
        """Return the scenario's YAML rendering (metadata overlay stripped)."""
        if get_catalog_entry(scenario_id) is None:
            return _not_found(request)
        try:
            yaml_text = scenario_services.export_scenario_yaml(scenario_id)
        except ScenarioEditorError as exc:
            return _service_error(request, exc)
        return Response({"scenario_id": scenario_id, "yaml": yaml_text})
