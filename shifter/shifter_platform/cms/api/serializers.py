"""Serializers for the CMS DRF API."""

from __future__ import annotations

from rest_framework import serializers


class YAMLContentSerializer(serializers.Serializer):
    """Validate a YAML-content request body."""

    yaml_content = serializers.CharField(allow_blank=True, trim_whitespace=False)


class AcesCatalogFieldsSerializer(serializers.Serializer):
    """Read-only, allowlisted ACES package-source presentation fields.

    Every field is bounded provenance/identity metadata. This serializer never
    exposes raw ACES SDL, imported module bodies, generated content, flags,
    credentials, presigned URLs, provider payloads, or runtime config.
    """

    source_kind = serializers.CharField(read_only=True)
    contract_kind = serializers.CharField(read_only=True)
    contract_profile = serializers.CharField(read_only=True)
    package_ref = serializers.CharField(read_only=True)
    package_version = serializers.CharField(read_only=True)
    package_digest = serializers.CharField(read_only=True)
    lock_ref = serializers.CharField(read_only=True, allow_blank=True)
    lock_digest = serializers.CharField(read_only=True, allow_blank=True)
    conformance_status = serializers.CharField(read_only=True)
    conformance_report_ref = serializers.CharField(read_only=True, allow_blank=True)
    provenance_summary = serializers.DictField(read_only=True)


class CatalogEntrySerializer(serializers.Serializer):
    """Read-only catalog entry projection for the CMS catalog API.

    Serializes the presentation DTO from ``cms.scenarios.catalog_presentation``.
    ``aces`` is present only for ACES package-backed entries; legacy YAML/DB
    entries serialize it as ``null``.
    """

    id = serializers.CharField(read_only=True)
    name = serializers.CharField(read_only=True)
    scenario_type = serializers.CharField(read_only=True)
    is_default = serializers.BooleanField(read_only=True)
    enabled = serializers.BooleanField(read_only=True)
    staff_only = serializers.BooleanField(read_only=True)
    launchable = serializers.BooleanField(read_only=True)
    aces = AcesCatalogFieldsSerializer(read_only=True, allow_null=True)
