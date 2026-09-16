"""Session-only Administer API for runtime Mission Control lease policy (#2169)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.authentication import SessionAuthentication
from rest_framework.response import Response
from rest_framework.views import APIView

from cms.services import (
    LeasePolicyAuditContext,
    LeasePolicyOverride,
    MissionControlLeasePolicyAdminError,
    MissionControlLeasePolicySettings,
    get_mission_control_lease_settings,
    replace_group_lease_policy,
    replace_tenant_lease_policy,
    reset_group_lease_policy,
    reset_tenant_lease_policy,
)
from shared.api.errors import api_error_response
from shared.api.permissions import IsStaffSession
from shared.api_tokens.authentication import ApiTokenAuthentication
from shared.audit import get_actor_from_request, get_client_ip, get_request_id
from shared.mission_control_lease import MAX_LEASE_DAYS, MissionControlLeasePolicy

if TYPE_CHECKING:
    from rest_framework.request import Request

_ADMIN_AUTHENTICATION = [ApiTokenAuthentication, SessionAuthentication]

_ERROR_STATUS = {
    MissionControlLeasePolicyAdminError.Kind.FORBIDDEN: 403,
    MissionControlLeasePolicyAdminError.Kind.INVALID_POLICY: 400,
    MissionControlLeasePolicyAdminError.Kind.REVISION_CONFLICT: 409,
    MissionControlLeasePolicyAdminError.Kind.GROUP_NOT_FOUND: 404,
    MissionControlLeasePolicyAdminError.Kind.GROUP_INELIGIBLE: 409,
    MissionControlLeasePolicyAdminError.Kind.CHILD_POLICY_CONFLICT: 409,
}
_ERROR_MESSAGES = {
    MissionControlLeasePolicyAdminError.Kind.FORBIDDEN: (
        "Only an active platform superuser may administer lease policy."
    ),
    MissionControlLeasePolicyAdminError.Kind.INVALID_POLICY: "The lease policy is invalid.",
    MissionControlLeasePolicyAdminError.Kind.REVISION_CONFLICT: "The lease policy changed; refresh and try again.",
    MissionControlLeasePolicyAdminError.Kind.GROUP_NOT_FOUND: "Group not found.",
    MissionControlLeasePolicyAdminError.Kind.GROUP_INELIGIBLE: "This group is not eligible for lease policy.",
    MissionControlLeasePolicyAdminError.Kind.CHILD_POLICY_CONFLICT: (
        "A group lease policy exceeds the proposed tenant maximum."
    ),
}


class StrictObjectSerializer(serializers.Serializer):
    """Reject non-object input and unknown keys instead of silently ignoring them."""

    def to_internal_value(self, data: Any) -> dict[str, Any]:
        if not isinstance(data, Mapping):
            raise serializers.ValidationError({"non_field_errors": ["Expected a JSON object."]})
        unknown = set(data) - set(self.fields)
        if unknown:
            raise serializers.ValidationError(dict.fromkeys(sorted(unknown), "Unknown field."))
        return super().to_internal_value(data)


class StrictIntegerField(serializers.IntegerField):
    """Integer field that rejects booleans, strings, and fractional values."""

    def to_internal_value(self, data: Any) -> int:
        if isinstance(data, bool) or not isinstance(data, int):
            self.fail("invalid")
        return super().to_internal_value(data)


class StrictBooleanField(serializers.BooleanField):
    """Boolean field that rejects integer/string coercion."""

    def to_internal_value(self, data: Any) -> bool:
        if not isinstance(data, bool):
            self.fail("invalid", input=data)
        return super().to_internal_value(data)


class LeasePolicySerializer(serializers.Serializer):
    """The canonical four-field policy projection."""

    initial_days = serializers.IntegerField(min_value=1, max_value=MAX_LEASE_DAYS)
    extension_days = serializers.IntegerField(min_value=1, max_value=MAX_LEASE_DAYS)
    maximum_days = serializers.IntegerField(min_value=1, max_value=MAX_LEASE_DAYS)
    extensions_enabled = serializers.BooleanField()


class LeasePolicyOverrideSerializer(serializers.Serializer):
    """Serialize one complete runtime override and its revision."""

    policy = LeasePolicySerializer()
    revision = serializers.IntegerField(min_value=1)


class LeasePolicyGroupSettingsSerializer(serializers.Serializer):
    """Serialize one eligible group and its optional runtime override."""

    id = serializers.IntegerField(min_value=1)
    name = serializers.CharField()
    revision = serializers.IntegerField(min_value=0)
    override = LeasePolicyOverrideSerializer(allow_null=True)


class MissionControlLeasePolicySettingsSerializer(serializers.Serializer):
    """Serialize the complete administrator settings projection."""

    baseline = LeasePolicySerializer()
    tenant_revision = serializers.IntegerField(min_value=0)
    tenant_override = LeasePolicyOverrideSerializer(allow_null=True)
    effective_tenant = LeasePolicySerializer()
    effective_source = serializers.ChoiceField(choices=["deployment", "runtime"])
    groups = LeasePolicyGroupSettingsSerializer(many=True)


class ReplaceLeasePolicySerializer(StrictObjectSerializer):
    """Strict full replacement plus expected revision."""

    expected_revision = StrictIntegerField(min_value=0)
    initial_days = StrictIntegerField(min_value=1, max_value=MAX_LEASE_DAYS)
    extension_days = StrictIntegerField(min_value=1, max_value=MAX_LEASE_DAYS)
    maximum_days = StrictIntegerField(min_value=1, max_value=MAX_LEASE_DAYS)
    extensions_enabled = StrictBooleanField()

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if attrs["initial_days"] > attrs["maximum_days"]:
            raise serializers.ValidationError("initial_days must not exceed maximum_days.")
        return attrs


class ResetLeasePolicySerializer(StrictObjectSerializer):
    """Strict explicit reset command."""

    expected_revision = StrictIntegerField(min_value=0)


def _policy(data: dict[str, Any]) -> MissionControlLeasePolicy:
    """Build the canonical policy from validated command data."""
    return MissionControlLeasePolicy.model_validate(
        {
            "initial_days": data["initial_days"],
            "extension_days": data["extension_days"],
            "maximum_days": data["maximum_days"],
            "extensions_enabled": data["extensions_enabled"],
        }
    )


def _override_payload(value: LeasePolicyOverride | None) -> dict[str, object] | None:
    """Project an optional override into serializer-ready primitives."""
    if value is None:
        return None
    return {"policy": value.policy.model_dump(), "revision": value.revision}


def _settings_payload(settings: MissionControlLeasePolicySettings) -> dict[str, object]:
    """Project service settings into the explicit response contract."""
    return {
        "baseline": settings.baseline.model_dump(),
        "tenant_revision": settings.tenant_revision,
        "tenant_override": _override_payload(settings.tenant_override),
        "effective_tenant": settings.effective_tenant.model_dump(),
        "effective_source": settings.effective_source,
        "groups": [
            {
                "id": group.group_id,
                "name": group.group_name,
                "revision": group.revision,
                "override": _override_payload(group.override),
            }
            for group in settings.groups
        ],
    }


def _audit_context(request: Request) -> LeasePolicyAuditContext:
    """Capture bounded trusted request attribution for strict audit."""
    actor_type, actor_id = get_actor_from_request(request)
    return LeasePolicyAuditContext(
        actor_type=actor_type,
        actor_id=actor_id,
        request_id=get_request_id(request),
        source_ip=get_client_ip(request),
        user_agent=request.META.get("HTTP_USER_AGENT", "")[:500],
    )


def _error_response(request: Request, exc: MissionControlLeasePolicyAdminError) -> Response:
    """Map a classified service error to the shared safe envelope."""
    return api_error_response(
        code=exc.kind.value,
        message=_ERROR_MESSAGES[exc.kind],
        status_code=_ERROR_STATUS[exc.kind],
        request=request,
    )


def _current_response(request: Request) -> Response:
    """Return the current settings projection after reauthorization."""
    try:
        settings = get_mission_control_lease_settings(request.user)
    except MissionControlLeasePolicyAdminError as exc:
        return _error_response(request, exc)
    return Response(MissionControlLeasePolicySettingsSerializer(_settings_payload(settings)).data)


class _LeasePolicyAdminView(APIView):
    """Apply the shared authentication and staff-session policy."""

    authentication_classes = _ADMIN_AUTHENTICATION
    permission_classes = [IsStaffSession]


class MissionControlLeasePolicySettingsView(_LeasePolicyAdminView):
    """Read fallback, runtime tenant state, and policy-eligible groups."""

    @extend_schema(
        responses=MissionControlLeasePolicySettingsSerializer,
        operation_id="api_v1_administer_mission_control_lease_policy_retrieve",
    )
    def get(self, request: Request) -> Response:
        return _current_response(request)


class MissionControlTenantLeasePolicyView(_LeasePolicyAdminView):
    """Replace the complete runtime tenant policy under revision CAS."""

    @extend_schema(
        request=ReplaceLeasePolicySerializer,
        responses=MissionControlLeasePolicySettingsSerializer,
        operation_id="api_v1_administer_mission_control_lease_policy_tenant_replace",
    )
    def put(self, request: Request) -> Response:
        serializer = ReplaceLeasePolicySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            replace_tenant_lease_policy(
                request.user,
                _policy(data),
                expected_revision=data["expected_revision"],
                audit=_audit_context(request),
            )
        except MissionControlLeasePolicyAdminError as exc:
            return _error_response(request, exc)
        return _current_response(request)


class MissionControlTenantLeasePolicyResetView(_LeasePolicyAdminView):
    """Explicitly remove the runtime tenant replacement."""

    @extend_schema(
        request=ResetLeasePolicySerializer,
        responses=MissionControlLeasePolicySettingsSerializer,
        operation_id="api_v1_administer_mission_control_lease_policy_tenant_reset",
    )
    def post(self, request: Request) -> Response:
        serializer = ResetLeasePolicySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            reset_tenant_lease_policy(
                request.user,
                expected_revision=serializer.validated_data["expected_revision"],
                audit=_audit_context(request),
            )
        except MissionControlLeasePolicyAdminError as exc:
            return _error_response(request, exc)
        return _current_response(request)


class MissionControlGroupLeasePolicyView(_LeasePolicyAdminView):
    """Replace one policy-eligible RBAC group's complete lease policy."""

    @extend_schema(
        request=ReplaceLeasePolicySerializer,
        responses=MissionControlLeasePolicySettingsSerializer,
        operation_id="api_v1_administer_mission_control_lease_policy_group_replace",
    )
    def put(self, request: Request, group_id: int) -> Response:
        serializer = ReplaceLeasePolicySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            replace_group_lease_policy(
                request.user,
                group_id,
                _policy(data),
                expected_revision=data["expected_revision"],
                audit=_audit_context(request),
            )
        except MissionControlLeasePolicyAdminError as exc:
            return _error_response(request, exc)
        return _current_response(request)


class MissionControlGroupLeasePolicyResetView(_LeasePolicyAdminView):
    """Explicitly remove one group policy so the group inherits tenant policy."""

    @extend_schema(
        request=ResetLeasePolicySerializer,
        responses=MissionControlLeasePolicySettingsSerializer,
        operation_id="api_v1_administer_mission_control_lease_policy_group_reset",
    )
    def post(self, request: Request, group_id: int) -> Response:
        serializer = ResetLeasePolicySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            reset_group_lease_policy(
                request.user,
                group_id,
                expected_revision=serializer.validated_data["expected_revision"],
                audit=_audit_context(request),
            )
        except MissionControlLeasePolicyAdminError as exc:
            return _error_response(request, exc)
        return _current_response(request)


__all__ = [
    "MissionControlGroupLeasePolicyResetView",
    "MissionControlGroupLeasePolicyView",
    "MissionControlLeasePolicySettingsView",
    "MissionControlTenantLeasePolicyResetView",
    "MissionControlTenantLeasePolicyView",
]
