"""Organizer serializers for the canonical CTF DRF API: event + challenge management.

Typed request/response projections for the organizer event and challenge
management endpoints (events, scenarios, challenges, flags, hints, files,
prerequisites).
"""

from __future__ import annotations

from rest_framework import serializers

# ---------------------------------------------------------------------------
# Organizer serializers (event management)
# ---------------------------------------------------------------------------


class EventSummarySerializer(serializers.Serializer):
    """List projection of one of an organizer's events."""

    id = serializers.CharField(read_only=True)
    name = serializers.CharField(read_only=True)
    status = serializers.CharField(read_only=True)
    event_start = serializers.DateTimeField(read_only=True)
    event_end = serializers.DateTimeField(read_only=True)
    team_mode = serializers.BooleanField(read_only=True)


class EventListResponseSerializer(serializers.Serializer):
    """Envelope returned by the organizer event list."""

    events = EventSummarySerializer(many=True, read_only=True)


class EventDetailSerializer(serializers.Serializer):
    """Full organizer-facing event detail projection."""

    id = serializers.CharField(read_only=True)
    name = serializers.CharField(read_only=True)
    description = serializers.CharField(read_only=True, allow_blank=True)
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


class EventWriteSerializer(serializers.Serializer):
    """Create/update request body: the mutable event fields only.

    ``status``, ``created_by``, ``id``, and timestamps are intentionally absent;
    the service layer also filters to mutable fields, so mass assignment is
    prevented at two layers. Updates are validated ``partial=True`` by the view.
    """

    name = serializers.CharField(max_length=200)
    description = serializers.CharField(required=False, allow_blank=True)
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


# ---------------------------------------------------------------------------
# Organizer serializers (challenge management)
# ---------------------------------------------------------------------------


class ChallengeWriteSerializer(serializers.Serializer):
    """Create/update request body for a challenge.

    Declares every field the ``ctf.services.create_challenge`` /
    ``update_challenge`` facade consumes so nothing is silently dropped: the
    mass-assignable challenge fields plus the write-only ``flag`` (plaintext),
    ``flags`` (multi-flag records), ``tags``, ``topics``, and ``next_challenge``.
    ``flag`` is intentionally optional at this layer; the service enforces the
    flag-or-flags rule and raises ``CTFValidationError`` (mapped to 400).
    Updates are validated ``partial=True`` by the view.
    """

    name = serializers.CharField(max_length=200)
    description = serializers.CharField(required=False, allow_blank=True)
    category = serializers.CharField(required=False, allow_blank=True)
    points = serializers.IntegerField(required=False)
    difficulty = serializers.CharField(required=False, allow_blank=True)
    flag_format = serializers.CharField(required=False, allow_blank=True)
    solution = serializers.CharField(required=False, allow_blank=True)
    max_attempts = serializers.IntegerField(required=False)
    minimum_points = serializers.IntegerField(required=False, min_value=0)
    decay_function = serializers.CharField(required=False)
    decay_solve_count = serializers.IntegerField(required=False, min_value=0)
    release_time = serializers.DateTimeField(required=False, allow_null=True)
    order = serializers.IntegerField(required=False)
    visibility = serializers.CharField(required=False, allow_blank=True)
    target_instance_name = serializers.CharField(required=False, allow_blank=True)
    target_port = serializers.IntegerField(required=False, allow_null=True)
    flag = serializers.CharField(required=False, allow_blank=True, write_only=True)
    flags = serializers.ListField(child=serializers.DictField(), required=False)
    tags = serializers.ListField(child=serializers.CharField(), required=False)
    topics = serializers.ListField(child=serializers.CharField(), required=False)
    next_challenge = serializers.CharField(required=False, allow_null=True)


class ChallengeSummarySerializer(serializers.Serializer):
    """List projection of one challenge for an event."""

    id = serializers.CharField(read_only=True)
    name = serializers.CharField(read_only=True)
    category = serializers.CharField(read_only=True, allow_blank=True)
    points = serializers.IntegerField(read_only=True)
    difficulty = serializers.CharField(read_only=True, allow_blank=True)
    order = serializers.IntegerField(read_only=True)
    tags = serializers.ListField(child=serializers.CharField(), read_only=True)
    topics = serializers.ListField(child=serializers.CharField(), read_only=True)


class ChallengeListResponseSerializer(serializers.Serializer):
    """Envelope returned by the event challenge list."""

    challenges = ChallengeSummarySerializer(many=True, read_only=True)


class ChallengeHintSerializer(serializers.Serializer):
    """Organizer-facing hint projection (full text is exposed)."""

    id = serializers.CharField(read_only=True)
    text = serializers.CharField(read_only=True, allow_blank=True)
    penalty = serializers.IntegerField(read_only=True)
    order = serializers.IntegerField(read_only=True)


class OrganizerChallengeRatingSerializer(serializers.Serializer):
    """Aggregate participant rating shown to organizers (CTF-120)."""

    average = serializers.FloatField(read_only=True, allow_null=True)
    count = serializers.IntegerField(read_only=True)


class OrganizerChallengeDetailSerializer(serializers.Serializer):
    """Full organizer-facing challenge detail projection."""

    id = serializers.CharField(read_only=True)
    name = serializers.CharField(read_only=True)
    description = serializers.CharField(read_only=True, allow_blank=True)
    category = serializers.CharField(read_only=True, allow_blank=True)
    points = serializers.IntegerField(read_only=True)
    difficulty = serializers.CharField(read_only=True, allow_blank=True)
    flag_format = serializers.CharField(read_only=True, allow_blank=True)
    hints = ChallengeHintSerializer(many=True, read_only=True)
    max_attempts = serializers.IntegerField(read_only=True)
    minimum_points = serializers.IntegerField(read_only=True)
    decay_function = serializers.CharField(read_only=True)
    decay_solve_count = serializers.IntegerField(read_only=True)
    order = serializers.IntegerField(read_only=True)
    release_time = serializers.DateTimeField(read_only=True, allow_null=True)
    visibility = serializers.CharField(read_only=True, allow_blank=True)
    target_instance_name = serializers.CharField(read_only=True, allow_blank=True)
    target_port = serializers.IntegerField(read_only=True, allow_null=True)
    tags = serializers.ListField(child=serializers.CharField(), read_only=True)
    topics = serializers.ListField(child=serializers.CharField(), read_only=True)
    solution = serializers.CharField(read_only=True, allow_blank=True)
    rating = OrganizerChallengeRatingSerializer(read_only=True, allow_null=True)


class AwardSerializer(serializers.Serializer):
    """One organizer-granted award row (CTF-204)."""

    id = serializers.CharField(read_only=True)
    points = serializers.IntegerField(read_only=True)
    reason = serializers.CharField(read_only=True, allow_blank=True)
    granted_by = serializers.CharField(read_only=True, allow_null=True)
    created_at = serializers.CharField(read_only=True, allow_null=True)


class AwardListResponseSerializer(serializers.Serializer):
    """Envelope for a participant's award list."""

    awards = AwardSerializer(many=True, read_only=True)


class AwardWriteSerializer(serializers.Serializer):
    """Request body for granting an award (positive or negative points)."""

    points = serializers.IntegerField(min_value=-100000, max_value=100000)
    reason = serializers.CharField(max_length=2000)


class ChallengeMutationResultSerializer(serializers.Serializer):
    """Compact result returned after creating or updating a challenge."""

    id = serializers.CharField(read_only=True)
    name = serializers.CharField(read_only=True)
    category = serializers.CharField(read_only=True, allow_blank=True)
    points = serializers.IntegerField(read_only=True)


class DeleteSuccessSerializer(serializers.Serializer):
    """The ``{"success": true}`` envelope returned by service-backed deletes."""

    success = serializers.BooleanField(read_only=True)


class FlagWriteSerializer(serializers.Serializer):
    """Request body for adding a flag to a challenge.

    Mirrors the legacy view's ``flag_data`` construction: ``flag`` is optional
    here (the view enforces that a value is present for static/regex types), and
    ``case_sensitive`` / ``order`` / ``validator_config`` carry the same defaults
    the service consumes.
    """

    flag = serializers.CharField(required=False, allow_blank=True, default="")
    flag_type = serializers.CharField(required=False, default="static")
    case_sensitive = serializers.BooleanField(required=False, default=True)
    order = serializers.IntegerField(required=False, default=0)
    validator_config = serializers.DictField(required=False, allow_null=True, default=None)


class FlagCreateResultSerializer(serializers.Serializer):
    """Result returned after adding a flag (validator_config only when set)."""

    id = serializers.CharField(read_only=True)
    flag_type = serializers.CharField(read_only=True)
    case_sensitive = serializers.BooleanField(read_only=True)
    order = serializers.IntegerField(read_only=True)
    validator_config = serializers.DictField(read_only=True, required=False)


class HintWriteSerializer(serializers.Serializer):
    """Request body for adding a hint. ``penalty`` / ``order`` are optional so the
    service applies its own defaults (order defaults to the current hint count).
    """

    text = serializers.CharField()
    penalty = serializers.IntegerField(required=False)
    order = serializers.IntegerField(required=False)


class HintListResponseSerializer(serializers.Serializer):
    """Envelope returned by the challenge hint list."""

    hints = ChallengeHintSerializer(many=True, read_only=True)


class ChallengeFileMetaSerializer(serializers.Serializer):
    """Metadata projection of one challenge attachment (organizer list view)."""

    id = serializers.CharField(read_only=True)
    filename = serializers.CharField(read_only=True)
    display_name = serializers.CharField(read_only=True, allow_blank=True)
    file_size_bytes = serializers.IntegerField(read_only=True)
    file_size_display = serializers.CharField(read_only=True)
    content_type = serializers.CharField(read_only=True, allow_blank=True)
    sha256_hash = serializers.CharField(read_only=True, allow_blank=True)
    order = serializers.IntegerField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)


class ChallengeFileListResponseSerializer(serializers.Serializer):
    """Envelope returned by the challenge file list."""

    files = ChallengeFileMetaSerializer(many=True, read_only=True)


class ChallengeFileUploadSerializer(serializers.Serializer):
    """Multipart request body for uploading a challenge attachment."""

    file = serializers.FileField()
    display_name = serializers.CharField(required=False, allow_blank=True)


class ChallengeFileUploadResultSerializer(serializers.Serializer):
    """Result returned after uploading a challenge attachment."""

    id = serializers.CharField(read_only=True)
    filename = serializers.CharField(read_only=True)
    display_name = serializers.CharField(read_only=True, allow_blank=True)
    file_size_bytes = serializers.IntegerField(read_only=True)
    file_size_display = serializers.CharField(read_only=True)


class FileDownloadResponseSerializer(serializers.Serializer):
    """Presigned download URL for a challenge attachment."""

    url = serializers.CharField(read_only=True)
    filename = serializers.CharField(read_only=True)


class PrerequisiteWriteSerializer(serializers.Serializer):
    """Request body for adding a challenge prerequisite."""

    required_challenge_id = serializers.UUIDField()


class PrerequisiteSerializer(serializers.Serializer):
    """List projection of one challenge prerequisite."""

    id = serializers.CharField(read_only=True)
    required_challenge_id = serializers.CharField(read_only=True)
    required_challenge_name = serializers.CharField(read_only=True)
    required_challenge_category = serializers.CharField(read_only=True, allow_blank=True)
    required_challenge_points = serializers.IntegerField(read_only=True)


class PrerequisiteListResponseSerializer(serializers.Serializer):
    """Envelope returned by the challenge prerequisite list."""

    prerequisites = PrerequisiteSerializer(many=True, read_only=True)


class PrerequisiteCreateResultSerializer(serializers.Serializer):
    """Result returned after adding a prerequisite."""

    id = serializers.CharField(read_only=True)
    required_challenge_id = serializers.CharField(read_only=True)
    required_challenge_name = serializers.CharField(read_only=True)
