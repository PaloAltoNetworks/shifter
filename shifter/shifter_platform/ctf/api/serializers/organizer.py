"""Organizer serializers for the canonical CTF DRF API: event + challenge management.

Typed request/response projections for the organizer event and challenge
management endpoints (events, scenarios, challenges, flags, hints, files,
prerequisites).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

# Imported at runtime (not TYPE_CHECKING): drf-spectacular calls typing.get_type_hints
# on the SerializerMethodField methods, which evaluates the ``event: CTFEvent``
# annotations, so the name must resolve at runtime.
from ctf.models import CTFEvent
from shared.api.closed_serializer import ClosedSerializer
from shared.api.model_sources import ModelSourceRevisionField, ModelSourceSelectionField

# ---------------------------------------------------------------------------
# Organizer serializers (event management)
# ---------------------------------------------------------------------------


class ManagedContentSummarySerializer(serializers.Serializer):
    """Bounded managed-content status for the organizer (issue #1971).

    Exposes only the current revision fence and drift state so the organizer can
    refresh; never object keys, flag material, or validator configuration.
    """

    scenario_id = serializers.CharField(read_only=True)
    declared_digest = serializers.CharField(read_only=True)
    state = serializers.CharField(read_only=True)
    is_refreshable = serializers.BooleanField(read_only=True)


class OwnerRefSerializer(serializers.Serializer):
    """Bounded event-owner projection: stable id and display name only (ADR-052).

    Never serializes the Django ``User``, provider subject, email, groups, or role
    facts. Consumed by the organizer/platform-admin list and detail so the owner
    is visible without leaking identity payload.
    """

    id = serializers.CharField(read_only=True)
    display_name = serializers.CharField(read_only=True)


class _EventAccessProjectionMixin:
    """Owner + server-derived access-source/capabilities projection shared by list/detail.

    Reads ``actor``, ``is_platform_admin``, and a prefetched ``staff_roles`` map
    (event id -> role) from serializer context so a list render adds no per-row
    query (ADR-052-R3). ``access_source`` and ``access_capabilities`` are advisory
    UI hints; the server re-authorizes every operation and a hidden control is not
    an authorization boundary.
    """

    if TYPE_CHECKING:
        # Provided by ``serializers.Serializer`` at runtime; declared here so the
        # mixin's methods type-check against the serializer context.
        context: dict[str, Any]

    @extend_schema_field(OwnerRefSerializer)
    def get_owner(self, event: CTFEvent) -> dict[str, str]:
        """Return the bounded owner reference for ``event``."""
        owner = event.created_by
        display = (owner.get_full_name() or owner.get_username()) if owner is not None else ""
        return {"id": str(event.created_by_id), "display_name": display}

    def _access_source(self, event: CTFEvent) -> str:
        """Compute the discovery access source without a per-row query."""
        from ctf.services.authorization import EventAuthoritySource

        actor = self.context.get("actor")
        if actor is not None and event.created_by_id == actor.pk:
            return EventAuthoritySource.OWNER.value
        if self.context.get("is_platform_admin"):
            return EventAuthoritySource.PLATFORM_ADMIN.value
        return EventAuthoritySource.EVENT_STAFF.value

    def get_access_source(self, event: CTFEvent) -> str:
        """Return the closed authority source by which the actor reaches ``event``."""
        return self._access_source(event)

    @extend_schema_field(serializers.ListField(child=serializers.CharField()))
    def get_access_capabilities(self, event: CTFEvent) -> list[str]:
        """Return the advisory capability nouns the actor holds for ``event``."""
        from ctf.services.authorization import EventAuthoritySource
        from ctf.services.event.staff import ALL_DELEGABLE_CAPABILITIES, capabilities_for_role

        source = self._access_source(event)
        if source in (EventAuthoritySource.OWNER.value, EventAuthoritySource.PLATFORM_ADMIN.value):
            return list(ALL_DELEGABLE_CAPABILITIES)
        role = (self.context.get("staff_roles") or {}).get(event.id)
        return list(capabilities_for_role(role))


class EventSummarySerializer(_EventAccessProjectionMixin, serializers.Serializer):
    """List projection of one event with owner and server-derived access context."""

    id = serializers.CharField(read_only=True)
    name = serializers.CharField(read_only=True)
    status = serializers.CharField(read_only=True)
    event_start = serializers.DateTimeField(read_only=True)
    event_end = serializers.DateTimeField(read_only=True)
    team_mode = serializers.BooleanField(read_only=True)
    owner = serializers.SerializerMethodField()
    access_source = serializers.SerializerMethodField()
    access_capabilities = serializers.SerializerMethodField()


class EventListResponseSerializer(serializers.Serializer):
    """Envelope returned by the organizer event list."""

    events = EventSummarySerializer(many=True, read_only=True)


class EventListQuerySerializer(serializers.Serializer):
    """Bounded, allowlisted query for the authority-aware event list (ADR-052-R3).

    Search and ordering are allowlisted, status uses ``EventStatus``, owner is an
    exact owner-id filter, and page/page-size are capped. These are data-selection
    filters only and are never authority inputs.
    """

    _ORDERING = ("event_start", "-event_start", "name", "-name", "status", "-status")

    search = serializers.CharField(required=False, allow_blank=True, max_length=100)
    status = serializers.CharField(required=False, allow_blank=True, max_length=32)
    owner = serializers.CharField(required=False, allow_blank=True, max_length=64)
    ordering = serializers.ChoiceField(choices=_ORDERING, required=False, allow_blank=True)
    page = serializers.IntegerField(required=False, min_value=1)
    page_size = serializers.IntegerField(required=False, min_value=1, max_value=500)

    def validate_status(self, value: str) -> str:
        """Reject a status that is not a known ``EventStatus`` value."""
        from ctf.enums import EventStatus

        if value and value not in {s.value for s in EventStatus}:
            raise serializers.ValidationError("Unknown event status.")
        return value


class EventDetailSerializer(_EventAccessProjectionMixin, serializers.Serializer):
    """Full organizer-facing event detail projection with owner and access context."""

    owner = serializers.SerializerMethodField()
    access_source = serializers.SerializerMethodField()
    access_capabilities = serializers.SerializerMethodField()
    id = serializers.CharField(read_only=True)
    name = serializers.CharField(read_only=True)
    description = serializers.CharField(read_only=True, allow_blank=True)
    public_registration_enabled = serializers.BooleanField(read_only=True)
    public_registration_url = serializers.SerializerMethodField()
    status = serializers.CharField(read_only=True)
    event_start = serializers.DateTimeField(read_only=True)
    event_end = serializers.DateTimeField(read_only=True)
    registration_deadline = serializers.DateTimeField(read_only=True, allow_null=True)
    scenario_id = serializers.CharField(read_only=True, allow_blank=True)
    auto_cleanup = serializers.BooleanField(read_only=True)
    cleanup_delay_hours = serializers.IntegerField(read_only=True)
    max_participants = serializers.IntegerField(read_only=True, allow_null=True)
    team_mode = serializers.BooleanField(read_only=True)
    team_size_limit = serializers.IntegerField(read_only=True, allow_null=True)
    range_config = serializers.DictField(read_only=True)
    range_spinup_minutes = serializers.IntegerField(read_only=True)
    submission_cooldown_seconds = serializers.IntegerField(read_only=True)
    attempt_limit_mode = serializers.CharField(read_only=True)
    attempt_limit_cooldown_seconds = serializers.IntegerField(read_only=True)
    rating_visibility = serializers.CharField(read_only=True)
    scoring_mode = serializers.CharField(read_only=True)
    scoreboard_visible = serializers.BooleanField(read_only=True)
    scoreboard_visibility = serializers.CharField(read_only=True)
    scoreboard_freeze_at = serializers.DateTimeField(read_only=True, allow_null=True)
    rules = serializers.CharField(read_only=True, allow_blank=True)
    reminder_hours = serializers.ListField(child=serializers.IntegerField(), read_only=True)
    event_timezone = serializers.CharField(read_only=True, allow_blank=True)
    capacity_hints = serializers.DictField(read_only=True)
    model_demand = serializers.ListField(child=serializers.DictField(), read_only=True)
    model_sources = ModelSourceSelectionField(read_only=True)
    workspace = serializers.SerializerMethodField()

    def get_workspace(self, event: CTFEvent) -> str | None:
        from workspaces.services import WorkspaceAuthorizationError, WorkspaceOperation, authorize_bound_workspace

        request = self.context.get("request")
        if request is None:
            return None
        try:
            return str(
                authorize_bound_workspace(
                    request.user, event.workspace_id, WorkspaceOperation.USE_CTF_COMMUNICATIONS
                ).workspace_uuid
            )
        except WorkspaceAuthorizationError:
            return None

    model_source_revision = serializers.IntegerField(read_only=True)
    logo_url = serializers.CharField(read_only=True, allow_blank=True)
    visible_os_types = serializers.ListField(child=serializers.CharField(), read_only=True)
    theme_color = serializers.CharField(read_only=True, allow_blank=True)
    managed_content = serializers.SerializerMethodField()

    @extend_schema_field(serializers.URLField(allow_null=True))
    def get_public_registration_url(self, event: CTFEvent) -> str | None:
        """Build the share URL only from the validated installation origin."""
        from django.urls import reverse

        from shared.site_url import SiteUrlUnavailable, validated_site_url

        try:
            origin = validated_site_url()
        except SiteUrlUnavailable:
            return None
        return f"{origin}{reverse('ctf:public_event_registration', args=[event.pk])}"

    @extend_schema_field(ManagedContentSummarySerializer(allow_null=True))
    def get_managed_content(self, event: CTFEvent) -> dict[str, object] | None:
        """Return the event's managed-content summary, or None when unmanaged."""
        from ctf.models import CTFContentHydrationReceipt

        receipt = CTFContentHydrationReceipt.objects.filter(event=event).first()
        if receipt is None:
            return None
        return {
            "scenario_id": receipt.scenario_id,
            "declared_digest": receipt.declared_digest,
            "state": receipt.state,
            "is_refreshable": bool(event.is_content_modifiable or event.is_live_flag_repairable),
        }


class EventWriteSerializer(ClosedSerializer):
    """Create/update request body: the mutable event fields only.

    ``status``, ``created_by``, ``id``, and timestamps are intentionally absent;
    the service layer also filters to mutable fields, so mass assignment is
    prevented at two layers. Updates are validated ``partial=True`` by the view.
    """

    name = serializers.CharField(max_length=200)
    description = serializers.CharField(required=False, allow_blank=True)
    public_registration_enabled = serializers.BooleanField(required=False)
    event_start = serializers.DateTimeField()
    event_end = serializers.DateTimeField()
    registration_deadline = serializers.DateTimeField(required=False, allow_null=True)
    scenario_id = serializers.CharField(required=False, allow_blank=True, max_length=255)
    auto_cleanup = serializers.BooleanField(required=False)
    cleanup_delay_hours = serializers.IntegerField(required=False)
    max_participants = serializers.IntegerField(required=False, allow_null=True)
    team_mode = serializers.BooleanField(required=False)
    team_size_limit = serializers.IntegerField(required=False, allow_null=True)
    range_spinup_minutes = serializers.IntegerField(required=False)
    range_config = serializers.DictField(required=False)
    submission_cooldown_seconds = serializers.IntegerField(required=False)
    attempt_limit_mode = serializers.CharField(required=False)
    attempt_limit_cooldown_seconds = serializers.IntegerField(required=False)
    rating_visibility = serializers.CharField(required=False)
    scoring_mode = serializers.CharField(required=False)
    scoreboard_visibility = serializers.CharField(required=False)
    scoreboard_freeze_at = serializers.DateTimeField(required=False, allow_null=True)
    rules = serializers.CharField(required=False, allow_blank=True)
    reminder_hours = serializers.ListField(
        child=serializers.IntegerField(min_value=1, max_value=720), required=False, max_length=10
    )
    event_timezone = serializers.CharField(required=False, allow_blank=True, max_length=64)
    capacity_hints = serializers.DictField(required=False)
    model_demand = serializers.ListField(child=serializers.DictField(), required=False, max_length=64)
    model_sources = ModelSourceSelectionField(required=False)
    workspace = serializers.UUIDField(required=False)
    expected_model_source_revision = ModelSourceRevisionField(required=False, min_value=0)
    logo_url = serializers.URLField(required=False, allow_blank=True, max_length=500)
    visible_os_types = serializers.ListField(child=serializers.CharField(max_length=32), required=False, max_length=16)
    theme_color = serializers.RegexField(r"^(#[0-9a-fA-F]{6})?$", required=False, allow_blank=True)

    def validate_model_demand(self, value: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Validate each typed model-demand entry (PLAT-202, CTF-908).

        Organizer input is bounded by the closed ``EventModelDemand`` contract; a
        malformed entry is rejected at the write boundary rather than dropped later.
        """
        from pydantic import ValidationError as _PydanticValidationError

        from shared.model_access.admission import EventModelDemand

        for entry in value:
            try:
                EventModelDemand.model_validate(entry)
            except _PydanticValidationError as exc:
                raise serializers.ValidationError("invalid model demand entry") from exc
        return value


class EventLifecycleRequestSerializer(serializers.Serializer):
    """One lifecycle transition to apply to an owned event (CTF-007)."""

    action = serializers.ChoiceField(choices=["open_registration", "activate", "pause", "resume", "end", "cancel"])


class ScheduledTaskSerializer(serializers.Serializer):
    """One scheduler row in the organizer task history (#526)."""

    id = serializers.CharField(read_only=True)
    task_type = serializers.CharField(read_only=True)
    status = serializers.CharField(read_only=True)
    scheduled_for = serializers.DateTimeField(read_only=True)
    executed_at = serializers.DateTimeField(read_only=True, allow_null=True)
    error_message = serializers.CharField(read_only=True, allow_blank=True)
    retry_count = serializers.IntegerField(read_only=True)


class ScheduledTaskListResponseSerializer(serializers.Serializer):
    """Envelope for the organizer scheduled-task listing."""

    tasks = ScheduledTaskSerializer(many=True, read_only=True)


class CleanupControlRequestSerializer(serializers.Serializer):
    """Defer or cancel the pending automated range cleanup (CTF-1003)."""

    action = serializers.ChoiceField(choices=["defer", "cancel"])
    hours = serializers.IntegerField(required=False, min_value=1, max_value=168)


class EventMutationResultSerializer(serializers.Serializer):
    """Compact result returned after creating or updating an event."""

    id = serializers.CharField(read_only=True)
    name = serializers.CharField(read_only=True)
    status = serializers.CharField(read_only=True)


class EventContentRefreshRequestSerializer(serializers.Serializer):
    """Refresh managed event content to the configured revision (issue #1971).

    The organizer supplies only the digest they currently see as an optimistic
    concurrency fence; the server-configured bundle is the target. No object
    key, URL, bundle body, flag, or target digest is caller-controlled.
    """

    expected_current_digest = serializers.RegexField(
        r"^sha256:[0-9a-f]{64}$",
        max_length=71,
        help_text="The declared digest the organizer currently sees (optimistic fence).",
    )


class EventContentRefreshResultSerializer(serializers.Serializer):
    """Bounded result of an in-place managed content refresh."""

    event_id = serializers.CharField(read_only=True)
    outcome = serializers.CharField(read_only=True)
    changed_categories = serializers.ListField(child=serializers.CharField(), read_only=True)
    challenge_count = serializers.IntegerField(read_only=True)
    flag_count = serializers.IntegerField(read_only=True)
    hint_count = serializers.IntegerField(read_only=True)
    prerequisite_count = serializers.IntegerField(read_only=True)


class ForceDeleteEventRequestSerializer(serializers.Serializer):
    """Force-delete confirmation body."""

    confirmation_name = serializers.CharField()


class ForceDeleteEventResultSerializer(serializers.Serializer):
    """Summary returned by a force-delete (range teardown counts)."""

    event_id = serializers.CharField(read_only=True)
    event_name = serializers.CharField(read_only=True)
    ranges_destroyed = serializers.IntegerField(read_only=True)
    ranges_failed = serializers.IntegerField(read_only=True)


class CtfScenarioRefSerializer(serializers.Serializer):
    """A CMS scenario id/name pair available for a CTF event."""

    id = serializers.CharField(read_only=True)
    name = serializers.CharField(read_only=True)


class CtfScenarioListResponseSerializer(serializers.Serializer):
    """Envelope returned by the scenario list."""

    scenarios = CtfScenarioRefSerializer(many=True, read_only=True)
