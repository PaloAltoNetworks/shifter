"""Moderation, staff, transfer, webhook, and page serializers (python:S104 split).

Split from ``organizer_ops``; import through ``ctf.api.serializers`` as
before.
"""

from __future__ import annotations

from rest_framework import serializers

from ctf.models.event import MAX_EVENT_PAGE_BODY_CHARS


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
    """Assignment request: organizer-tier user email plus staff role.

    ``role`` stays an unconstrained ``CharField`` at the HTTP boundary to keep the
    v1 request contract backward-compatible (ADR-040 — a request enum is a
    breaking change). The closed ``EventStaffRole`` vocabulary is still enforced
    fail-closed in ``assign_event_staff``, which rejects an unknown role with a
    400 (#1922).
    """

    email = serializers.EmailField()
    role = serializers.CharField(max_length=16)


class EventOwnershipTransferRequestSerializer(serializers.Serializer):
    """Ownership-transfer request: the target user's id (an existing co-organizer)."""

    user_id = serializers.IntegerField(min_value=1)


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


class EventPageSerializer(serializers.Serializer):
    """One organizer-authored event page (CTF-1303)."""

    id = serializers.CharField(read_only=True)
    title = serializers.CharField(read_only=True)
    slug = serializers.CharField(read_only=True)
    body = serializers.CharField(read_only=True)
    order = serializers.IntegerField(read_only=True)


class EventPagesResponseSerializer(serializers.Serializer):
    """Envelope for the event page listing."""

    pages = EventPageSerializer(many=True, read_only=True)


class EventPageWriteSerializer(serializers.Serializer):
    """Create/update body for a custom page."""

    title = serializers.CharField(max_length=120)
    slug = serializers.SlugField(required=False, allow_blank=True, max_length=140)
    # Bound the organizer-authored source: it is untrusted input rendered to
    # other participants, so a hostile or fat-fingered payload cannot balloon
    # the request, row, response, or render work (#1854).
    body = serializers.CharField(max_length=MAX_EVENT_PAGE_BODY_CHARS)
    order = serializers.IntegerField(required=False, min_value=0)
