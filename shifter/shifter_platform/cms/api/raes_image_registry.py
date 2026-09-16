"""CMS API for the tenant-facing RAES image registry management surface (#1566).

Registers, lists, and disables :class:`engine.models.RaesImageMapping` rows -- the
ADR-032-R2 realization seam -- through the single validated write path in
``engine.services`` (``upsert_raes_image_mapping`` / ``disable_raes_image_mapping``
/ ``list_raes_image_mappings``). These views own only HTTP shape, the CMS
authoring permission gate, and the allowlisted projection the SPA renders; all
domain validation (provider, natural key, disk size, soft disable) stays in the
service. The provisioner resolves these rows read-only at realization and is not
touched here (CQRS: the platform writes, the provisioner reads).

The surface is always available to authorized CMS readers/authors because RAES
is the platform's only provisioning authority.
"""

from __future__ import annotations

import logging

from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from cms.api.permissions import CMS_READ_PERMISSIONS, CMS_WRITE_PERMISSIONS
from engine.services import (
    RaesImageMappingError,
    RaesImageMappingOptions,
    disable_raes_image_mapping,
    list_raes_image_mappings,
    upsert_raes_image_mapping,
)
from shared.api.errors import api_error_response
from shared.log_sanitize import safe_log_value

logger = logging.getLogger(__name__)


class RaesImageMappingViewSerializer(serializers.Serializer):
    """Allowlisted read projection shared by the register, list, and disable responses.

    Field-for-field with ``engine.services.RaesImageMappingView`` so it renders
    either that DTO (list/disable) or the model instance the upsert returns.
    """

    id = serializers.IntegerField(read_only=True)
    provider = serializers.CharField(read_only=True)
    source_name = serializers.CharField(read_only=True)
    source_version = serializers.CharField(read_only=True, allow_blank=True)
    image_ref = serializers.CharField(read_only=True)
    machine_type = serializers.CharField(read_only=True, allow_blank=True)
    disk_size_gb = serializers.IntegerField(read_only=True, allow_null=True)
    disk_type = serializers.CharField(read_only=True, allow_blank=True)
    enabled = serializers.BooleanField(read_only=True)
    notes = serializers.CharField(read_only=True, allow_blank=True)
    artifact_id = serializers.CharField(read_only=True, allow_blank=True)
    artifact_version = serializers.CharField(read_only=True, allow_blank=True)
    artifact_digest = serializers.CharField(read_only=True, allow_blank=True)
    media_type = serializers.CharField(read_only=True, allow_blank=True)
    integrity_ref = serializers.CharField(read_only=True, allow_blank=True)
    provenance_ref = serializers.CharField(read_only=True, allow_blank=True)
    created_at = serializers.DateTimeField(read_only=True)
    updated_at = serializers.DateTimeField(read_only=True)


class RaesImageMappingRegisterSerializer(serializers.Serializer):
    """Shape validation for a register/upsert request; the service is final validator.

    Provider-choice validity, natural-key rules, and soft-disable semantics stay
    in ``engine.services`` so the API and management command cannot drift; this
    serializer only enforces HTTP shape (required fields, max lengths, positive
    disk size, boolean).
    """

    provider = serializers.CharField(max_length=16)
    source_name = serializers.CharField(max_length=200)
    image_ref = serializers.CharField(max_length=500)
    source_version = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")
    machine_type = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")
    disk_size_gb = serializers.IntegerField(min_value=1, required=False, allow_null=True, default=None)
    disk_type = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")
    enabled = serializers.BooleanField(required=False, default=True)
    notes = serializers.CharField(required=False, allow_blank=True, default="")
    # Portable RAES artifact identity + admission evidence (#1580); supply all five
    # for a portable mapping or none for a legacy alias-only mapping (service validates).
    artifact_id = serializers.CharField(max_length=256, required=False, allow_blank=True, default="")
    artifact_version = serializers.CharField(max_length=256, required=False, allow_blank=True, default="")
    artifact_digest = serializers.CharField(max_length=71, required=False, allow_blank=True, default="")
    media_type = serializers.CharField(max_length=256, required=False, allow_blank=True, default="")
    integrity_ref = serializers.CharField(max_length=256, required=False, allow_blank=True, default="")
    provenance_ref = serializers.CharField(max_length=256, required=False, allow_blank=True, default="")


class RaesImageMappingDisableSerializer(serializers.Serializer):
    """Shape validation for a disable request (natural key only)."""

    provider = serializers.CharField(max_length=16)
    source_name = serializers.CharField(max_length=200)
    source_version = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")


class RaesImageMappingListQuerySerializer(serializers.Serializer):
    """Shape validation for list query parameters."""

    provider = serializers.CharField(max_length=16, required=False)
    include_disabled = serializers.BooleanField(required=False, default=True)


def _domain_error(request: Request, exc: RaesImageMappingError) -> Response:
    """Render an RAES registry domain-validation error as the shared 400 envelope."""
    return api_error_response(
        code="invalid",
        message=str(exc),
        status_code=status.HTTP_400_BAD_REQUEST,
        request=request,
    )


class RaesImageMappingListCreateView(APIView):
    """List registry mappings, or register/upsert one, for CMS authoring actors."""

    permission_classes = CMS_READ_PERMISSIONS

    def get_permissions(self) -> list[BasePermission]:
        """Require write scope for register (POST); read scope for list (GET)."""
        if self.request.method == "POST":
            return [permission() for permission in CMS_WRITE_PERMISSIONS]
        return super().get_permissions()

    @extend_schema(
        parameters=[RaesImageMappingListQuerySerializer],
        responses=RaesImageMappingViewSerializer(many=True),
    )
    def get(self, request: Request) -> Response:
        """Return registry rows as allowlisted DTOs (disabled rows included by default)."""
        query = RaesImageMappingListQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        try:
            rows = list_raes_image_mappings(
                provider=query.validated_data.get("provider"),
                include_disabled=query.validated_data["include_disabled"],
            )
        except RaesImageMappingError as exc:
            return _domain_error(request, exc)
        return Response(RaesImageMappingViewSerializer(rows, many=True).data)

    @extend_schema(request=RaesImageMappingRegisterSerializer, responses=RaesImageMappingViewSerializer)
    def post(self, request: Request) -> Response:
        """Register (create or update) a mapping through the single validated write path."""
        body = RaesImageMappingRegisterSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = body.validated_data
        try:
            mapping = upsert_raes_image_mapping(
                provider=data["provider"],
                source_name=data["source_name"],
                image_ref=data["image_ref"],
                options=RaesImageMappingOptions(
                    source_version=data["source_version"],
                    machine_type=data["machine_type"],
                    disk_size_gb=data["disk_size_gb"],
                    disk_type=data["disk_type"],
                    enabled=data["enabled"],
                    notes=data["notes"],
                    artifact_id=data["artifact_id"],
                    artifact_version=data["artifact_version"],
                    artifact_digest=data["artifact_digest"],
                    media_type=data["media_type"],
                    integrity_ref=data["integrity_ref"],
                    provenance_ref=data["provenance_ref"],
                ),
            )
        except RaesImageMappingError as exc:
            return _domain_error(request, exc)
        logger.info(
            "raes image mapping registered provider=%s source=%s enabled=%s",
            safe_log_value(mapping.provider),
            safe_log_value(mapping.source_name),
            mapping.enabled,
        )
        return Response(RaesImageMappingViewSerializer(mapping).data)


class RaesImageMappingDisableView(APIView):
    """Soft-disable a registry mapping (``enabled=False``) by natural key."""

    permission_classes = CMS_WRITE_PERMISSIONS

    @extend_schema(request=RaesImageMappingDisableSerializer, responses=RaesImageMappingViewSerializer)
    def post(self, request: Request) -> Response:
        """Disable an existing mapping without deleting it (preserves audit)."""
        body = RaesImageMappingDisableSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = body.validated_data
        try:
            view = disable_raes_image_mapping(
                provider=data["provider"],
                source_name=data["source_name"],
                source_version=data["source_version"],
            )
        except RaesImageMappingError as exc:
            return _domain_error(request, exc)
        logger.info(
            "raes image mapping disabled provider=%s source=%s",
            safe_log_value(view.provider),
            safe_log_value(view.source_name),
        )
        return Response(RaesImageMappingViewSerializer(view).data)
