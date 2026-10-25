"""Serializers for the CMS DRF API."""

from __future__ import annotations

from typing import Any

from rest_framework import serializers


class PackRegistrationSerializer(serializers.Serializer):
    """Validate the shape of a uniform pack-registration request body (#1578).

    This is a thin boundary check: it rejects missing/oversized/wrong-typed
    fields so the service and the reference-record validator receive a
    well-formed request. Domain validation (source-kind allowlist, digest shape,
    bounded provenance, pack conformance, no-shadow) remains authoritative in the
    service and model — this serializer does not restate it.
    """

    scenario_id = serializers.SlugField(max_length=100)
    source_kind = serializers.CharField(max_length=16)
    contract_kind = serializers.CharField(max_length=32)
    contract_profile = serializers.CharField(max_length=128)
    package_ref = serializers.CharField(max_length=512)
    package_version = serializers.CharField(max_length=128)
    package_digest = serializers.CharField(max_length=71)
    # Optional: an empty string means "no expected digest to check against"
    # (the field is allow_blank/default=""), otherwise a sha256 digest. The
    # pattern permits both so the published default ("") satisfies its own
    # schema and the OpenAPI document validates (#2212).
    expected_package_digest = serializers.RegexField(
        r"^(sha256:[a-f0-9]{64})?$", max_length=71, required=False, allow_blank=True, default=""
    )
    lock_ref = serializers.CharField(max_length=512, required=False, allow_blank=True, default="")
    lock_digest = serializers.CharField(max_length=71, required=False, allow_blank=True, default="")
    provenance = serializers.DictField(required=False, default=dict)
    # conformance_status is intentionally NOT accepted: a caller cannot assert a
    # pack has passed conformance. Registration always lands non-passed and a
    # trusted conformance process promotes it (see cms.services.register_pack).


class PackRegistrationResultSerializer(serializers.Serializer):
    """Bounded 201 summary returned after a pack is registered (#1578)."""

    scenario_id = serializers.CharField(read_only=True)
    source_kind = serializers.CharField(read_only=True)
    conformance_status = serializers.CharField(read_only=True)


class RaesCatalogFieldsSerializer(serializers.Serializer):
    """Read-only, allowlisted RAES package-source presentation fields.

    Every field is bounded provenance/identity metadata. This serializer never
    exposes raw RAES SDL, imported module bodies, generated content, flags,
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
    Every emitted entry is backed by a RAES package source.
    """

    id = serializers.CharField(read_only=True)
    name = serializers.CharField(read_only=True)
    scenario_type = serializers.CharField(read_only=True)
    source = serializers.CharField(read_only=True)
    is_default = serializers.BooleanField(read_only=True)
    enabled = serializers.BooleanField(read_only=True)
    staff_only = serializers.BooleanField(read_only=True)
    launchable = serializers.BooleanField(read_only=True)
    raes = RaesCatalogFieldsSerializer(read_only=True, allow_null=True)


class ScenarioDetailSerializer(serializers.Serializer):
    """Read-only RAES package identity and availability for the SPA."""

    id = serializers.CharField(read_only=True)
    name = serializers.CharField(read_only=True)
    scenario_type = serializers.CharField(read_only=True)
    source = serializers.CharField(read_only=True)
    enabled = serializers.BooleanField(read_only=True)
    staff_only = serializers.BooleanField(read_only=True)
    launchable = serializers.BooleanField(read_only=True)
    raes = RaesCatalogFieldsSerializer(read_only=True, allow_null=True)


class ScenarioMetadataUpdateSerializer(serializers.Serializer):
    """Metadata (availability/audience) update; both fields optional for PATCH."""

    enabled = serializers.BooleanField(required=False)
    staff_only = serializers.BooleanField(required=False)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        """Require at least one metadata field to change."""
        if "enabled" not in attrs and "staff_only" not in attrs:
            raise serializers.ValidationError("Provide at least one of 'enabled' or 'staff_only'.")
        return attrs


class ScenarioMetadataStateSerializer(serializers.Serializer):
    """Response for a metadata update: the resolved overlay state."""

    scenario_id = serializers.CharField(read_only=True)
    enabled = serializers.BooleanField(read_only=True)
    staff_only = serializers.BooleanField(read_only=True)


class RealizabilityGapSerializer(serializers.Serializer):
    """One bounded reason the backend cannot realize a scenario (ADR-034-R3).

    ``code`` is the stable identifier clients switch on; ``message`` is prose for
    the author and must never be parsed. Nothing here carries authored payloads,
    parameter or account values, provider detail, or filesystem paths.
    """

    code = serializers.CharField(read_only=True)
    address = serializers.CharField(read_only=True)
    category = serializers.CharField(read_only=True)
    message = serializers.CharField(read_only=True)


class ScenarioRealizabilitySerializer(serializers.Serializer):
    """Backend realizability assessment for one catalog entry (ADR-034-R3).

    Serializes the projection from ``cms.scenarios.realizability``. A negative
    assessment is a successful response with ``outcome`` set and ``gaps``
    populated -- non-realizability is a domain answer, not an HTTP error.
    ``indeterminate`` means the assessment could not be completed and must never
    be rendered as realizable.
    """

    scenario_id = serializers.CharField(read_only=True)
    target_id = serializers.CharField(read_only=True, allow_blank=True)
    outcome = serializers.CharField(read_only=True)
    gaps = RealizabilityGapSerializer(many=True, read_only=True)
