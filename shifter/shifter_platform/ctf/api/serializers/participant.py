"""Participant-facing serializers for the canonical CTF DRF API.

The participant-safe read projections (consumed by the ``/api/v1/ctf/me/*``
workspace) and the participant play surface (flag submission, hints, ratings,
own submissions). These serializers are the typed contract over the dicts
produced by :mod:`ctf.api.projections`; they intentionally never declare flag,
solution, or validator-config fields so the generated OpenAPI schema (and
therefore the SPA types) cannot express those values.
"""

from __future__ import annotations

from rest_framework import serializers

from ctf.api.serializers._common import _NamedRefSerializer


class ParticipantSelfSerializer(serializers.Serializer):
    """The requesting participant's own state (never another participant's)."""

    id = serializers.CharField(read_only=True)
    name = serializers.CharField(read_only=True)
    status = serializers.CharField(read_only=True)
    role = serializers.CharField(read_only=True)
    affiliation = serializers.CharField(read_only=True, allow_blank=True)
    range_status = serializers.CharField(read_only=True, allow_blank=True)
    cached_score = serializers.IntegerField(read_only=True)
    cached_solve_count = serializers.IntegerField(read_only=True)
    team = _NamedRefSerializer(read_only=True, allow_null=True)
    bracket = _NamedRefSerializer(read_only=True, allow_null=True)


class ParticipantEventSerializer(serializers.Serializer):
    """Read-only participant-facing projection of the current CTF event.

    Organizer-only configuration (range config, reminder schedule, spare counts,
    email templates, cleanup policy) is deliberately omitted.
    """

    id = serializers.CharField(read_only=True)
    name = serializers.CharField(read_only=True)
    description = serializers.CharField(read_only=True, allow_blank=True)
    status = serializers.CharField(read_only=True)
    team_mode = serializers.BooleanField(read_only=True)
    scoring_mode = serializers.CharField(read_only=True)
    rating_visibility = serializers.CharField(read_only=True)
    attempt_limit_mode = serializers.CharField(read_only=True)
    scoreboard_visible = serializers.BooleanField(read_only=True)
    scoreboard_visibility = serializers.CharField(read_only=True)
    event_start = serializers.DateTimeField(read_only=True, allow_null=True)
    event_end = serializers.DateTimeField(read_only=True, allow_null=True)
    registration_deadline = serializers.DateTimeField(read_only=True, allow_null=True)
    rules = serializers.CharField(read_only=True, allow_blank=True)
    logo_url = serializers.CharField(read_only=True, allow_blank=True)
    theme_color = serializers.CharField(read_only=True, allow_blank=True)


class ParticipantCurrentEventSerializer(serializers.Serializer):
    """The participant's current event plus their own participant state."""

    event = ParticipantEventSerializer(read_only=True)
    participant = ParticipantSelfSerializer(read_only=True)


class ParticipantChallengeListItemSerializer(serializers.Serializer):
    """A participant-safe browse entry for one available challenge.

    Carries only what the browse list renders. No flag hash, flag format,
    solution, or validator configuration is exposed.
    """

    id = serializers.CharField(read_only=True)
    name = serializers.CharField(read_only=True)
    category = serializers.CharField(read_only=True, allow_blank=True)
    points = serializers.IntegerField(read_only=True)
    difficulty = serializers.CharField(read_only=True, allow_blank=True)
    order = serializers.IntegerField(read_only=True)
    solved = serializers.BooleanField(read_only=True)
    tags = serializers.ListField(child=serializers.CharField(), read_only=True)
    topics = serializers.ListField(child=serializers.CharField(), read_only=True)


class ParticipantTeamMemberSerializer(serializers.Serializer):
    """A teammate's display identity (no score or account fields)."""

    id = serializers.CharField(read_only=True)
    name = serializers.CharField(read_only=True)
    is_captain = serializers.BooleanField(read_only=True)


class ParticipantTeamSerializer(serializers.Serializer):
    """The participant's own team and its members."""

    id = serializers.CharField(read_only=True)
    name = serializers.CharField(read_only=True)
    members = ParticipantTeamMemberSerializer(many=True, read_only=True)
    is_captain = serializers.BooleanField(read_only=True)
    team_size_limit = serializers.IntegerField(read_only=True, allow_null=True)
    invite_code = serializers.CharField(read_only=True, allow_null=True)


class TeamCreateRequestSerializer(serializers.Serializer):
    """Request body for creating a team."""

    name = serializers.CharField(max_length=100)


class TeamJoinRequestSerializer(serializers.Serializer):
    """Request body for joining a team by invite code."""

    invite_code = serializers.CharField(max_length=64)


class TeamMemberRequestSerializer(serializers.Serializer):
    """Request body naming a teammate (transfer captaincy, remove member)."""

    participant_id = serializers.UUIDField()


class ParticipantHintSerializer(serializers.Serializer):
    """A progressive hint. ``text`` is populated only when unlocked."""

    id = serializers.CharField(read_only=True)
    order = serializers.IntegerField(read_only=True)
    penalty = serializers.IntegerField(read_only=True)
    unlocked = serializers.BooleanField(read_only=True)
    text = serializers.CharField(read_only=True, allow_null=True)


class ParticipantChallengeFileSerializer(serializers.Serializer):
    """A participant-visible challenge attachment (metadata only)."""

    id = serializers.CharField(read_only=True)
    filename = serializers.CharField(read_only=True)
    display_name = serializers.CharField(read_only=True, allow_blank=True)
    size_bytes = serializers.IntegerField(read_only=True)
    content_type = serializers.CharField(read_only=True, allow_blank=True)


class ChallengeConnectionInfoSerializer(serializers.Serializer):
    """Target-instance connection info, surfaced only when the range is ready."""

    host = serializers.CharField(read_only=True)
    port = serializers.IntegerField(read_only=True, allow_null=True)
    instance_name = serializers.CharField(read_only=True)
    os_type = serializers.CharField(read_only=True, allow_blank=True)


class ChallengeRatingSerializer(serializers.Serializer):
    """Challenge rating projection (aggregate visible only when public)."""

    average = serializers.FloatField(read_only=True, allow_null=True)
    count = serializers.IntegerField(read_only=True)
    own_rating = serializers.IntegerField(read_only=True, allow_null=True)
    public = serializers.BooleanField(read_only=True)


class ParticipantChallengeDetailSerializer(serializers.Serializer):
    """Participant-safe challenge detail for the solve view.

    Never declares flag, flag-format, or validator-config fields. ``solution`` is
    non-null only after the event has ended/archived.
    """

    id = serializers.CharField(read_only=True)
    name = serializers.CharField(read_only=True)
    description = serializers.CharField(read_only=True, allow_blank=True)
    category = serializers.CharField(read_only=True, allow_blank=True)
    tags = serializers.ListField(child=serializers.CharField(), read_only=True)
    topics = serializers.ListField(child=serializers.CharField(), read_only=True)
    points = serializers.IntegerField(read_only=True)
    difficulty = serializers.CharField(read_only=True, allow_blank=True)
    max_attempts = serializers.IntegerField(read_only=True)
    attempt_limit_mode = serializers.CharField(read_only=True)
    solved = serializers.BooleanField(read_only=True)
    attempt_count = serializers.IntegerField(read_only=True)
    attempts_remaining = serializers.IntegerField(read_only=True, allow_null=True)
    timeout_retry_after = serializers.IntegerField(read_only=True, allow_null=True)
    hints = ParticipantHintSerializer(many=True, read_only=True)
    next_hint_id = serializers.CharField(read_only=True, allow_null=True)
    next_hint_cost = serializers.IntegerField(read_only=True)
    points_after_next_hint = serializers.IntegerField(read_only=True)
    total_hint_penalty = serializers.IntegerField(read_only=True)
    files = ParticipantChallengeFileSerializer(many=True, read_only=True)
    prerequisites_met = serializers.BooleanField(read_only=True)
    unmet_prerequisites = _NamedRefSerializer(many=True, read_only=True)
    connection_info = ChallengeConnectionInfoSerializer(read_only=True, allow_null=True)
    locked = serializers.BooleanField(read_only=True)
    show_solution = serializers.BooleanField(read_only=True)
    solution = serializers.CharField(read_only=True, allow_null=True)
    rating = ChallengeRatingSerializer(read_only=True, allow_null=True)


# ---------------------------------------------------------------------------
# Participant play serializers (rating, flag submission, hints, own submissions)
# ---------------------------------------------------------------------------


class RateChallengeRequestSerializer(serializers.Serializer):
    """Participant request body for rating a challenge (1-5)."""

    value = serializers.IntegerField()


class RateChallengeResultSerializer(serializers.Serializer):
    """Result returned after recording a challenge rating."""

    value = serializers.IntegerField(read_only=True)
    challenge_id = serializers.CharField(read_only=True)


class SubmitFlagRequestSerializer(serializers.Serializer):
    """Participant request body for submitting a flag.

    ``flag`` is blank-tolerant at this layer so the view can apply the legacy
    strip-then-reject rule and return the exact ``Could not process challenge
    action.`` 400 envelope for an empty or whitespace-only flag.
    """

    flag = serializers.CharField(required=False, allow_blank=True, allow_null=True, write_only=True)


class SubmitFlagResultSerializer(serializers.Serializer):
    """Scored result returned after a flag submission."""

    correct = serializers.BooleanField(read_only=True)
    points_awarded = serializers.IntegerField(read_only=True)
    attempt_number = serializers.IntegerField(read_only=True)
    score = serializers.IntegerField(read_only=True)
    rank = serializers.IntegerField(read_only=True, allow_null=True)
    message = serializers.CharField(read_only=True)


class UseHintRequestSerializer(serializers.Serializer):
    """Optional body for unlocking a hint.

    Omit the body (or send ``{}``) to unlock the next hint in order; pass
    ``hint_id`` to unlock a specific hint.
    """

    hint_id = serializers.UUIDField(required=False, write_only=True)


class UseHintResultSerializer(serializers.Serializer):
    """Result returned after unlocking a hint."""

    text = serializers.CharField(read_only=True)
    penalty = serializers.IntegerField(read_only=True)
    order = serializers.IntegerField(read_only=True)
    total_penalty = serializers.IntegerField(read_only=True)
    already_unlocked = serializers.BooleanField(read_only=True)


class SubmissionListItemSerializer(serializers.Serializer):
    """One of the requesting participant's own submissions."""

    id = serializers.CharField(read_only=True)
    challenge_id = serializers.CharField(read_only=True)
    challenge_name = serializers.CharField(read_only=True)
    is_correct = serializers.BooleanField(read_only=True)
    points_awarded = serializers.IntegerField(read_only=True)
    attempt_number = serializers.IntegerField(read_only=True)
    submitted_at = serializers.DateTimeField(read_only=True, allow_null=True)


class SubmissionListResponseSerializer(serializers.Serializer):
    """Envelope returned by the participant submission history."""

    submissions = SubmissionListItemSerializer(many=True, read_only=True)
    total = serializers.IntegerField(read_only=True)


class _ProfileEventRefSerializer(serializers.Serializer):
    """Minimal event reference on the profile payload."""

    id = serializers.CharField(read_only=True)
    name = serializers.CharField(read_only=True)


class ParticipantProfileSerializer(serializers.Serializer):
    """Event-scoped self profile (CTF-610)."""

    id = serializers.CharField(read_only=True)
    name = serializers.CharField(read_only=True)
    affiliation = serializers.CharField(read_only=True, allow_blank=True)
    email = serializers.CharField(read_only=True, allow_blank=True)
    username = serializers.CharField(read_only=True, allow_null=True)
    role = serializers.CharField(read_only=True)
    status = serializers.CharField(read_only=True)
    event = _ProfileEventRefSerializer(read_only=True)
    score = serializers.IntegerField(read_only=True)
    solve_count = serializers.IntegerField(read_only=True)


class ProfileUpdateRequestSerializer(serializers.Serializer):
    """Partial self-profile update: any omitted field is left unchanged."""

    name = serializers.CharField(required=False, max_length=100)
    affiliation = serializers.CharField(required=False, allow_blank=True, max_length=120)


class UsernameChangeRequestSerializer(serializers.Serializer):
    """Self-service username change request (#1593)."""

    username = serializers.CharField(max_length=49)


class ParticipantAnnouncementSerializer(serializers.Serializer):
    """One sent announcement on the participant surface (CTF-803)."""

    id = serializers.CharField(read_only=True)
    subject = serializers.CharField(read_only=True)
    body = serializers.CharField(read_only=True, allow_blank=True)
    sent_at = serializers.DateTimeField(read_only=True, allow_null=True)


class ParticipantAnnouncementListSerializer(serializers.Serializer):
    """Envelope for the participant announcement feed."""

    announcements = ParticipantAnnouncementSerializer(many=True, read_only=True)
