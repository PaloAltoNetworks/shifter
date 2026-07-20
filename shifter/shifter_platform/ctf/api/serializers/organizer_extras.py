"""Moderation, staff, transfer, and webhook serializers (python:S104 split).

Split from ``organizer_ops``; import through ``ctf.api.serializers`` as
before.
"""

from __future__ import annotations

from rest_framework import serializers


class ParticipantModerationRequestSerializer(serializers.Serializer):
    """Optional reason accompanying a ban or disqualification."""

    reason = serializers.CharField(required=False, allow_blank=True, max_length=2000)


class ParticipantRoleRequestSerializer(serializers.Serializer):
    """Target participation role for the role endpoint (CTF-604)."""

    role = serializers.CharField(max_length=16)


class ParticipantHiddenRequestSerializer(serializers.Serializer):
    """Target scoreboard visibility for the hidden endpoint (CTF-606)."""

    hidden = serializers.BooleanField()


class ParticipantUsernameRequestSerializer(serializers.Serializer):
    """New login handle for the username-rename endpoints (#1206/#1593)."""

    username = serializers.CharField(max_length=49)


class EventStaffMemberSerializer(serializers.Serializer):
    """One delegated staff assignment on an event (CTF-607)."""

    user_id = serializers.IntegerField(read_only=True)
    email = serializers.CharField(read_only=True)
    role = serializers.CharField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True, allow_null=True)


class EventStaffListResponseSerializer(serializers.Serializer):
    """Envelope for the event staff listing."""

    staff = EventStaffMemberSerializer(many=True, read_only=True)


class EventStaffAssignRequestSerializer(serializers.Serializer):
    """Assignment request: organizer-tier user email plus staff role."""

    email = serializers.EmailField()
    role = serializers.CharField(max_length=16)


class ChallengeImportRequestSerializer(serializers.Serializer):
    """Challenge import request: the export document itself (CTF-1101/1104)."""

    payload = serializers.DictField()


class ChallengeImportErrorSerializer(serializers.Serializer):
    """One skipped import entry with its reason."""

    index = serializers.IntegerField(read_only=True)
    name = serializers.CharField(read_only=True, required=False)
    error = serializers.CharField(read_only=True)


class ChallengeImportResultSerializer(serializers.Serializer):
    """Partial-success import outcome."""

    created = serializers.ListField(child=serializers.CharField(), read_only=True)
    errors = ChallengeImportErrorSerializer(many=True, read_only=True)


class WebhookSerializer(serializers.Serializer):
    """One registered webhook endpoint (CTF-1203); secrets never round-trip."""

    id = serializers.CharField(read_only=True)
    url = serializers.CharField(read_only=True)
    subscribed_events = serializers.ListField(child=serializers.CharField(), read_only=True)
    active = serializers.BooleanField(read_only=True)
    has_secret = serializers.BooleanField(read_only=True)
    last_status = serializers.CharField(read_only=True, allow_blank=True)
    last_delivery_at = serializers.DateTimeField(read_only=True, allow_null=True)


class WebhookListResponseSerializer(serializers.Serializer):
    """Envelope for the event webhook listing."""

    webhooks = WebhookSerializer(many=True, read_only=True)


class WebhookWriteSerializer(serializers.Serializer):
    """Webhook registration request."""

    url = serializers.URLField(max_length=500)
    secret = serializers.CharField(required=False, allow_blank=True, max_length=128)
    subscribed_events = serializers.ListField(child=serializers.CharField(), required=False, max_length=10)
