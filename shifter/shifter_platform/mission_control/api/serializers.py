"""Serializers for the Mission Control DRF API."""

from __future__ import annotations

from typing import Any

from rest_framework import serializers

from shared.aces.projections import DEFAULT_HISTORY_LIMIT, MAX_HISTORY_LIMIT
from shared.enums import ResourceStatus

AGENT_TYPE_CHOICES = ("xdr", "xdr_collector", "cloud_identity_engine")

# Single source for the range-status choice set, shared by every serializer that
# exposes a ``status`` field AND referenced by ``ENUM_NAME_OVERRIDES`` in
# ``config._drf_settings`` so drf-spectacular names this enum ``ResourceStatusEnum``
# (stable) instead of a hash-suffixed collision name against the Risk Register
# ``status`` enum. Keep the field ``choices`` and the override pointing at THIS list.
RESOURCE_STATUS_VALUES = [s.value for s in ResourceStatus]


class AcesRecordQuerySerializer(serializers.Serializer):
    """Validate query params for ACES operation-record read endpoints (#1275)."""

    limit = serializers.IntegerField(
        required=False,
        min_value=1,
        max_value=MAX_HISTORY_LIMIT,
        default=DEFAULT_HISTORY_LIMIT,
    )


class AcesParticipantRecordQuerySerializer(serializers.Serializer):
    """Validate query params for ACES participant-runtime record read endpoints (#1288)."""

    limit = serializers.IntegerField(
        required=False,
        min_value=1,
        max_value=MAX_HISTORY_LIMIT,
        default=DEFAULT_HISTORY_LIMIT,
    )
    participant_ref = serializers.CharField(
        required=False,
        allow_blank=False,
        trim_whitespace=True,
        max_length=256,
    )


class AcesParticipantRuntimeRecordSerializer(serializers.Serializer):
    """Read-only projection of one ACES participant-runtime sidecar record (#1288).

    Serializes an ``AcesParticipantRuntimeRecordProjection`` (already redacted
    by the shared read seam); it never touches the raw model ``payload``.
    """

    id = serializers.UUIDField(read_only=True)
    request_id = serializers.UUIDField(read_only=True)
    range_id = serializers.UUIDField(read_only=True, allow_null=True)
    range_instance_id = serializers.UUIDField(read_only=True, allow_null=True)
    participant_ref = serializers.CharField(read_only=True)
    record_kind = serializers.CharField(read_only=True)
    contract_kind = serializers.CharField(read_only=True)
    contract_version = serializers.CharField(read_only=True)
    contract_profile = serializers.CharField(read_only=True)
    participant_runtime_profile = serializers.CharField(read_only=True)
    source_timestamp = serializers.DateTimeField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)
    updated_at = serializers.DateTimeField(read_only=True)
    payload_digest = serializers.CharField(read_only=True)
    payload = serializers.DictField(read_only=True)
    diagnostic_refs = serializers.DictField(read_only=True)


class AcesOperationRecordSerializer(serializers.Serializer):
    """Read-only projection of one ACES operation sidecar record (#1275).

    Serializes an ``AcesOperationRecordProjection`` (already redacted by the
    shared read seam); it never touches the raw model ``payload``.
    """

    id = serializers.UUIDField(read_only=True)
    request_id = serializers.UUIDField(read_only=True)
    range_id = serializers.UUIDField(read_only=True, allow_null=True)
    record_kind = serializers.CharField(read_only=True)
    contract_kind = serializers.CharField(read_only=True)
    contract_version = serializers.CharField(read_only=True)
    contract_profile = serializers.CharField(read_only=True)
    source_timestamp = serializers.DateTimeField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)
    updated_at = serializers.DateTimeField(read_only=True)
    payload_digest = serializers.CharField(read_only=True)
    payload = serializers.DictField(read_only=True)
    diagnostic_refs = serializers.DictField(read_only=True)


class AcesOperationRecordListResponseSerializer(serializers.Serializer):
    """Response body shared by ``mission_control.api.aces`` list endpoints."""

    request_id = serializers.UUIDField()
    record_kind = serializers.CharField()
    results = AcesOperationRecordSerializer(many=True)


class AcesParticipantRuntimeRecordListResponseSerializer(serializers.Serializer):
    """Response body shared by ``mission_control.api.aces_participant`` list endpoints."""

    request_id = serializers.UUIDField()
    record_kind = serializers.CharField()
    results = AcesParticipantRuntimeRecordSerializer(many=True)


# ---------------------------------------------------------------------------
# Presentation / OpenAPI projection serializers (#1370)
#
# ``RangePresentationSerializer`` / ``InstancePresentationSerializer`` mirror
# the pydantic ``RangeContext`` / ``InstanceContext`` projections
# (``cyberscript.schemas.range``, re-exported as ``shared.schemas.RangeContext``
# / ``InstanceContext``) field-for-field. They exist ONLY so drf-spectacular
# can generate a typed OpenAPI response schema (and, downstream, SPA
# TypeScript types) for the range endpoints that embed
# ``RangeContext.model_dump(mode="json")`` as ``range``. They are never
# instantiated to build the actual JSON response — that stays the existing
# raw ``model_dump()`` dict, so response bytes are unchanged. Keep the field
# set in sync with the pydantic model by hand; a drift is caught by
# ``tests/mission_control/test_api_serializers.py``.
# ---------------------------------------------------------------------------


class InstancePresentationSerializer(serializers.Serializer):
    """Response-only projection of ``shared.schemas.InstanceContext``."""

    uuid = serializers.CharField(allow_null=True)
    name = serializers.CharField(allow_blank=True)
    role = serializers.ChoiceField(choices=["attacker", "victim", "dc", "ngfw"])
    os_type = serializers.ChoiceField(choices=["kali", "ubuntu", "windows", "panos"])
    join_domain = serializers.BooleanField()
    ami_key = serializers.CharField(allow_null=True)
    private_ip = serializers.CharField(allow_null=True)


class RangePresentationSerializer(serializers.Serializer):
    """Response-only projection of ``shared.schemas.RangeContext``.

    Field set mirrors ``RangeContext.model_fields`` plus its computed
    properties (``is_ready``, ``is_terminal``, ``is_active``).
    """

    request_id = serializers.UUIDField()
    range_id = serializers.IntegerField(allow_null=True)
    scenario_id = serializers.CharField()
    user_id = serializers.IntegerField()
    status = serializers.ChoiceField(choices=RESOURCE_STATUS_VALUES)
    instances = InstancePresentationSerializer(many=True)
    agent_name = serializers.CharField(allow_null=True)
    range_type = serializers.ChoiceField(choices=["demo"])
    is_ready = serializers.BooleanField()
    is_terminal = serializers.BooleanField()
    is_active = serializers.BooleanField()


class LaunchRangeSerializer(serializers.Serializer):
    """Validate range launch requests."""

    agents = serializers.DictField(child=serializers.IntegerField(min_value=1), required=False)
    agent_id = serializers.IntegerField(required=False, allow_null=True)
    scenario = serializers.CharField(required=False, default="basic", allow_blank=False, trim_whitespace=True)

    def validate_agent_id(self, value: int | None) -> int:
        if not value:
            raise serializers.ValidationError("agent_id is required")
        return value

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if "agents" not in attrs and "agent_id" not in attrs:
            raise serializers.ValidationError("Either 'agents' or 'agent_id' is required")
        return attrs


class RangeLifecycleSerializer(serializers.Serializer):
    """Validate range cancel/destroy/pause/resume requests."""

    request_id = serializers.UUIDField(required=False)
    range_id = serializers.IntegerField(min_value=1, required=False)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if "request_id" not in attrs and "range_id" not in attrs:
            raise serializers.ValidationError("request_id or range_id is required")
        return attrs


# ---------------------------------------------------------------------------
# Response-only serializers for ``mission_control.api.ranges`` (#1370)
#
# These document the existing ``Response({...})`` dict shapes for
# drf-spectacular; none of them are used to construct the actual response, so
# response bytes are unchanged.
# ---------------------------------------------------------------------------


class ConnectionUrlSerializer(serializers.Serializer):
    """One entry from ``mission_control.utils.build_connection_urls``."""

    uuid = serializers.CharField(allow_null=True)
    terminal_url = serializers.CharField()


class RangeLeaseSerializer(serializers.Serializer):
    """Safe, server-owned lease projection for one Mission Control range."""

    expires_at = serializers.DateTimeField()
    maximum_expires_at = serializers.DateTimeField()
    extension_days = serializers.IntegerField(min_value=1)
    can_extend = serializers.BooleanField()


class CurrentRangeResponseSerializer(serializers.Serializer):
    """Response body for ``CurrentRangeView.get``."""

    has_range = serializers.BooleanField()
    range = RangePresentationSerializer(allow_null=True)
    connection_urls = ConnectionUrlSerializer(many=True)
    aces_projection = serializers.DictField(allow_null=True)
    aces_participant_runtime = serializers.DictField(allow_null=True)
    lifecycle = RangeLeaseSerializer(allow_null=True)
    vpn_profile_available = serializers.BooleanField()


class RangeLeaseResponseSerializer(serializers.Serializer):
    """Response body for one bounded Mission Control lease extension."""

    lifecycle = RangeLeaseSerializer()


class LaunchRangeResponseSerializer(serializers.Serializer):
    """Response body for ``LaunchRangeView.post``."""

    success = serializers.BooleanField()
    range = RangePresentationSerializer()


class SuccessResponseSerializer(serializers.Serializer):
    """Generic ``{"success": true}`` response body.

    Shared by the range lifecycle mutations (cancel/destroy/pause/resume),
    upload cancel, and credential delete — every Mission Control mutation
    endpoint that has no payload beyond a boolean acknowledgement.
    """

    success = serializers.BooleanField()


class AgentListItemSerializer(serializers.Serializer):
    """One entry from ``cms.services.list_agents`` (``_agent_projection_dict``)."""

    id = serializers.IntegerField()
    name = serializers.CharField()
    os_name = serializers.CharField()
    os_slug = serializers.CharField()
    file_size_mb = serializers.FloatField()
    original_filename = serializers.CharField()
    created_at = serializers.DateTimeField()
    agent_type = serializers.ChoiceField(choices=list(AGENT_TYPE_CHOICES))
    agent_type_display = serializers.CharField()


class AgentListResponseSerializer(serializers.Serializer):
    """Response body for ``AgentListView.get``."""

    agents = AgentListItemSerializer(many=True)


class ScenarioListItemSerializer(serializers.Serializer):
    """One entry from ``cms.services.list_launchable_scenarios``.

    Legacy YAML/DB scenarios and ACES-derived catalog entries share this
    projection but are not fully homogeneous; fields the SPA does not render
    stay loosely typed (``DictField``/``ListField(DictField)``) rather than
    modeling the full ``ScenarioTemplate``/ACES catalog schema here.
    """

    id = serializers.CharField()
    name = serializers.CharField()
    description = serializers.CharField(allow_blank=True)
    enabled = serializers.BooleanField()
    is_default = serializers.BooleanField()
    staff_only = serializers.BooleanField()
    launchable = serializers.BooleanField()
    ngfw = serializers.BooleanField(required=False)
    instances = serializers.ListField(child=serializers.DictField(), required=False)
    subnets = serializers.ListField(child=serializers.DictField(), required=False)
    agent_requirements = serializers.DictField(required=False)


class ScenarioListResponseSerializer(serializers.Serializer):
    """Response body for ``ScenarioListView.get``."""

    scenarios = ScenarioListItemSerializer(many=True)


class RangeHistorySerializer(serializers.Serializer):
    """One entry in the range-history list (``GET .../ranges/``, #1370).

    Projects the durable identifiers off ``cms.models.RangeInstance`` without
    conflating them: ``request_id`` is the durable UUID correlation key
    (``None`` for pre-Request-pattern legacy rows with no linked
    ``cms.models.Request``); ``range_id`` is the legacy nullable integer id.
    """

    request_id = serializers.UUIDField(allow_null=True)
    range_id = serializers.IntegerField(allow_null=True)
    scenario_id = serializers.CharField()
    status = serializers.ChoiceField(choices=RESOURCE_STATUS_VALUES)
    range_source = serializers.CharField()
    created_at = serializers.DateTimeField()
    updated_at = serializers.DateTimeField()
    deleted_at = serializers.DateTimeField(allow_null=True)


class RangeHistoryResponseSerializer(serializers.Serializer):
    """Response body for the range-history list endpoint."""

    ranges = RangeHistorySerializer(many=True)


class UploadInitiateSerializer(serializers.Serializer):
    """Validate agent-upload initiation requests."""

    name = serializers.CharField(required=False, allow_blank=True, trim_whitespace=True)
    filename = serializers.CharField(required=False, allow_blank=True, trim_whitespace=True)
    file_size = serializers.JSONField(required=False)
    agent_type = serializers.CharField(required=False, allow_blank=True, default="xdr", trim_whitespace=True)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        name = attrs.get("name", "")
        filename = attrs.get("filename", "")
        file_size = attrs.get("file_size", 0)
        agent_type = attrs.get("agent_type", "xdr") or "xdr"

        if not name:
            raise serializers.ValidationError("Agent name is required")
        if not filename:
            raise serializers.ValidationError("Filename is required")
        if not isinstance(file_size, int) or file_size <= 0:
            raise serializers.ValidationError("Valid file size is required")
        if agent_type not in AGENT_TYPE_CHOICES:
            choices = ", ".join(AGENT_TYPE_CHOICES)
            raise serializers.ValidationError(f"Invalid agent type. Must be one of: {choices}")

        attrs["agent_type"] = agent_type
        return attrs


class UploadCompleteSerializer(serializers.Serializer):
    """Validate agent-upload completion requests."""

    upload_token = serializers.CharField(allow_blank=True, required=False, default="")


class UploadCancelSerializer(serializers.Serializer):
    """Validate agent-upload cancel requests."""

    upload_token = serializers.CharField(allow_blank=False, required=True, trim_whitespace=True)


class UploadInitiateResponseSerializer(serializers.Serializer):
    """Response body for ``UploadInitiateView.post`` (``cms.services.initiate_upload``).

    ``presigned_url`` is a short-lived, single-use S3 PUT URL — an existing
    response field, typed here for the schema but never given a real example.
    """

    presigned_url = serializers.CharField()
    s3_key = serializers.CharField()
    upload_token = serializers.CharField()
    expected_os = serializers.CharField(allow_null=True)


class UploadCompleteResponseSerializer(serializers.Serializer):
    """Response body for ``UploadCompleteView.post``."""

    success = serializers.BooleanField()
    agent_id = serializers.IntegerField()
    message = serializers.CharField()


class GuacamoleInstanceSerializer(serializers.Serializer):
    """Validate range Guacamole URL bootstrap requests."""

    instance_uuid = serializers.CharField(allow_blank=False, trim_whitespace=True)


class GuacamoleBootstrapQueuedSerializer(serializers.Serializer):
    """Response body for a queued Guacamole bootstrap (RDP/SSH/NGFW-SSH POST, HTTP 202).

    ``url`` here is the compatibility opener route, not a signed session URL
    (that one-time URL is delivered only by the status poll, see
    ``GuacamoleBootstrapStatusSerializer``).
    """

    request_id = serializers.UUIDField()
    status = serializers.CharField()
    status_url = serializers.CharField()
    url = serializers.CharField()


class GuacamoleBootstrapStatusSerializer(serializers.Serializer):
    """Response body for ``GuacamoleBootstrapStatusView.get``.

    ``url`` is the one-time signed Guacamole session URL, delivered exactly
    once on a ``succeeded`` poll; never given a real example. ``duration_ms``
    and ``error`` are present only once the bootstrap has finished or failed.
    """

    request_id = serializers.UUIDField()
    status = serializers.CharField()
    duration_ms = serializers.IntegerField(required=False)
    error = serializers.CharField(required=False)
    url = serializers.CharField(required=False)


class NGFWCreateSerializer(serializers.Serializer):
    """Validate NGFW creation requests."""

    name = serializers.CharField(allow_blank=True, required=False, default="", trim_whitespace=True)
    deployment_profile_id = serializers.IntegerField(required=False, allow_null=True)
    registration_method = serializers.CharField(required=False, allow_blank=True, default="", trim_whitespace=True)
    scm_credential_id = serializers.IntegerField(required=False, allow_null=True)
    otp_value = serializers.CharField(required=False, allow_blank=True, allow_null=True, trim_whitespace=True)
    otp_folder = serializers.CharField(required=False, allow_blank=True, allow_null=True, trim_whitespace=True)


class NGFWDestroySerializer(serializers.Serializer):
    """Validate NGFW destroy requests."""

    confirm_name = serializers.CharField(allow_blank=True, required=False, default="", trim_whitespace=True)


class CredentialCreateSerializer(serializers.Serializer):
    """Validate credential creation requests before schema-specific validation."""

    credential_type = serializers.CharField(trim_whitespace=True)
    name = serializers.CharField(required=False, allow_blank=True, trim_whitespace=True)
    expires_at = serializers.CharField(required=False, allow_blank=True, allow_null=True, trim_whitespace=True)
    scm_folder_name = serializers.CharField(required=False, allow_blank=True, trim_whitespace=True)
    scm_pin_id = serializers.CharField(required=False, allow_blank=True, trim_whitespace=True)
    scm_pin_value = serializers.CharField(required=False, allow_blank=True, trim_whitespace=False)
    sls_region = serializers.CharField(required=False, allow_blank=True, trim_whitespace=True)
    authcode = serializers.CharField(required=False, allow_blank=True, trim_whitespace=False)

    def validate_credential_type(self, value: str) -> str:
        if value not in ("scm", "deployment_profile"):
            raise serializers.ValidationError(f"Invalid credential type: {value}")
        return value


class NGFWCreateResponseSerializer(serializers.Serializer):
    """Response body for ``NGFWCreateView.post`` (HTTP 201)."""

    id = serializers.CharField()
    name = serializers.CharField()
    status = serializers.CharField()


class NGFWListItemSerializer(serializers.Serializer):
    """One entry from ``NGFWListView.get``."""

    id = serializers.CharField()
    name = serializers.CharField()
    status = serializers.CharField()
    created_at = serializers.DateTimeField()
    serial_number = serializers.CharField(allow_null=True, allow_blank=True)


class NGFWListResponseSerializer(serializers.Serializer):
    """Response body for ``NGFWListView.get``."""

    ngfws = NGFWListItemSerializer(many=True)


class NGFWDestroyResponseSerializer(serializers.Serializer):
    """Response body for ``NGFWDestroyView.post``."""

    status = serializers.CharField()


class CredentialCreateResponseSerializer(serializers.Serializer):
    """Response body for ``CredentialCreateView.post`` (HTTP 201)."""

    id = serializers.IntegerField()
    name = serializers.CharField()
    credential_type = serializers.CharField()
