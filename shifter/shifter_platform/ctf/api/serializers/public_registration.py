"""Organizer API contracts for pending public registration requests."""

from __future__ import annotations

from rest_framework import serializers


class PublicRegistrationRequestSerializer(serializers.Serializer):
    """One pending request visible only to an authorized event organizer."""

    id = serializers.UUIDField(read_only=True)
    name = serializers.CharField(read_only=True)
    email = serializers.EmailField(read_only=True)
    disposition = serializers.CharField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)


class PublicRegistrationRequestListResponseSerializer(serializers.Serializer):
    """Paginated pending-request queue."""

    requests = PublicRegistrationRequestSerializer(many=True, read_only=True)
    total = serializers.IntegerField(read_only=True)


class PublicRegistrationDispositionSerializer(serializers.Serializer):
    """Closed organizer decision vocabulary."""

    action = serializers.ChoiceField(choices=("approve", "reject"))


class PublicRegistrationDispositionResultSerializer(serializers.Serializer):
    """Terminal disposition result."""

    request_id = serializers.UUIDField(read_only=True)
    disposition = serializers.CharField(read_only=True)
    participant_id = serializers.UUIDField(read_only=True, allow_null=True)
