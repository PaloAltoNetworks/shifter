"""Serializers for the CMS DRF API."""

from __future__ import annotations

from typing import Any

from rest_framework import serializers

# Scenario definition option lists mirror ``cms.scenarios.schema`` exactly.
# The Pydantic ``ScenarioTemplate`` remains the authoritative validator; these
# choices give the SPA typed enums and reject obviously-wrong values early
# without drifting from the schema (the legacy form hardcoded stale lists).
INSTANCE_ROLES = ("attacker", "victim", "dc")
INSTANCE_OS_TYPES = ("kali", "windows", "ubuntu", "from_agent")


class YAMLContentSerializer(serializers.Serializer):
    """Validate a YAML-content request body."""

    yaml_content = serializers.CharField(allow_blank=True, trim_whitespace=False)


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
    source = serializers.CharField(read_only=True)
    is_default = serializers.BooleanField(read_only=True)
    enabled = serializers.BooleanField(read_only=True)
    staff_only = serializers.BooleanField(read_only=True)
    launchable = serializers.BooleanField(read_only=True)
    aces = AcesCatalogFieldsSerializer(read_only=True, allow_null=True)


class DCConfigSerializer(serializers.Serializer):
    """Domain-controller configuration, mirroring ``schema.DCConfig``."""

    domain_name = serializers.CharField()
    netbios_name = serializers.CharField()


class ScenarioInstanceSerializer(serializers.Serializer):
    """A single scenario instance, mirroring ``schema.InstanceConfig``.

    Kept field-complete against the Pydantic schema so a round-trip through the
    editor never silently drops instance fields (the legacy form hardcoded a
    partial list). The service layer re-validates the full definition.
    """

    name = serializers.CharField()
    role = serializers.ChoiceField(choices=INSTANCE_ROLES)
    os_type = serializers.ChoiceField(choices=INSTANCE_OS_TYPES)
    xdr_agent = serializers.BooleanField(required=False, default=False)
    domain_controller = serializers.BooleanField(required=False, default=False)
    join_domain = serializers.BooleanField(required=False, default=False)
    dc_config = DCConfigSerializer(required=False, allow_null=True)
    ami_key = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    instance_type = serializers.CharField(required=False, allow_null=True, allow_blank=True)


class ScenarioSubnetSerializer(serializers.Serializer):
    """A single scenario subnet, mirroring ``schema.SubnetConfig``."""

    name = serializers.CharField()
    instances = serializers.ListField(child=serializers.CharField())
    connected_to = serializers.ListField(child=serializers.CharField(), required=False, default=list)


class ScenarioDetailSerializer(serializers.Serializer):
    """Full scenario detail with source-capability flags for the editor.

    ``source`` classifies the entry (``builtin`` / ``custom`` / ``aces`` /
    ``ctf``) and the capability booleans tell the SPA which actions to offer.
    ``instances`` / ``subnets`` are populated for structural (demo) scenarios;
    ``aces`` carries the read-only provenance block for ACES entries.
    """

    id = serializers.CharField(read_only=True)
    name = serializers.CharField(read_only=True)
    description = serializers.CharField(read_only=True, allow_blank=True)
    scenario_type = serializers.CharField(read_only=True)
    source = serializers.CharField(read_only=True)
    is_default = serializers.BooleanField(read_only=True)
    enabled = serializers.BooleanField(read_only=True)
    staff_only = serializers.BooleanField(read_only=True)
    launchable = serializers.BooleanField(read_only=True)
    editable = serializers.BooleanField(read_only=True)
    deletable = serializers.BooleanField(read_only=True)
    exportable = serializers.BooleanField(read_only=True)
    ngfw = serializers.BooleanField(read_only=True)
    instances = ScenarioInstanceSerializer(many=True, read_only=True)
    subnets = ScenarioSubnetSerializer(many=True, read_only=True)
    aces = AcesCatalogFieldsSerializer(read_only=True, allow_null=True)


class _ScenarioDefinitionSerializer(serializers.Serializer):
    """Shared structural fields for scenario create/update request bodies."""

    name = serializers.CharField()
    description = serializers.CharField()
    ngfw = serializers.BooleanField(required=False, default=False)
    instances = ScenarioInstanceSerializer(many=True)
    subnets = ScenarioSubnetSerializer(many=True, required=False, default=list)

    def definition(self) -> dict[str, Any]:
        """Return the persisted structural definition (instances/subnets/ngfw)."""
        data = self.validated_data
        return {
            "instances": data["instances"],
            "subnets": data.get("subnets", []),
            "ngfw": data.get("ngfw", False),
        }


class ScenarioCreateSerializer(_ScenarioDefinitionSerializer):
    """Structured create request: identity plus definition."""

    scenario_id = serializers.CharField()


class ScenarioUpdateSerializer(_ScenarioDefinitionSerializer):
    """Structured update request: full definition replacement (no identity change)."""


class ScenarioCloneSerializer(serializers.Serializer):
    """Clone request body."""

    new_scenario_id = serializers.CharField()
    new_name = serializers.CharField(required=False, allow_blank=True, default="")


class ScenarioMetadataUpdateSerializer(serializers.Serializer):
    """Metadata (availability/audience) update; both fields optional for PATCH."""

    enabled = serializers.BooleanField(required=False)
    staff_only = serializers.BooleanField(required=False)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        """Require at least one metadata field to change."""
        if "enabled" not in attrs and "staff_only" not in attrs:
            raise serializers.ValidationError("Provide at least one of 'enabled' or 'staff_only'.")
        return attrs


class ScenarioCreatedSerializer(serializers.Serializer):
    """Response for a create/clone: the new scenario's identity."""

    scenario_id = serializers.CharField(read_only=True)
    name = serializers.CharField(read_only=True)


class ScenarioMetadataStateSerializer(serializers.Serializer):
    """Response for a metadata update: the resolved overlay state."""

    scenario_id = serializers.CharField(read_only=True)
    enabled = serializers.BooleanField(read_only=True)
    staff_only = serializers.BooleanField(read_only=True)


class ScenarioExportSerializer(serializers.Serializer):
    """Response for an export: the scenario id and its YAML rendering."""

    scenario_id = serializers.CharField(read_only=True)
    yaml = serializers.CharField(read_only=True)


class YAMLValidationResultSerializer(serializers.Serializer):
    """Response for the YAML validate endpoint."""

    valid = serializers.BooleanField(read_only=True)
    errors = serializers.ListField(child=serializers.CharField(), read_only=True)
    definition = serializers.DictField(read_only=True, allow_null=True)
