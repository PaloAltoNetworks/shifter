"""Organizer serializers for the canonical CTF DRF API: challenge management.

Typed request/response projections for the organizer challenge-management
endpoints (challenges, flags, hints, files, prerequisites, awards). Split from
``organizer.py`` to keep each serializer module within the file-size budget
(python:S104); the event-management serializers remain in ``organizer.py``.
"""

from __future__ import annotations

from rest_framework import serializers

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
    category = serializers.CharField(required=False, allow_blank=True, max_length=100)
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
