"""Bounded read projections for scoped communications (ADR-051, #2048).

Explicit, read-only serializers (never a writable ``ModelSerializer``) so the
generated OpenAPI schema and SPA types cannot express a field these projections
must never leak: another recipient's identity, an email or delivery coordinate,
provider details, credentials, flags, or a raw RAES document. The participant
inbox projection exposes only the requesting participant's own message and
receipt; the organizer summary exposes campaign shape and counts, never a
recipient list.
"""

from __future__ import annotations

from rest_framework import serializers

from ctf.models import CommunicationCampaign


class CommunicationInboxItemSerializer(serializers.Serializer):
    """One inbox item for the requesting participant (never another's).

    Bound to a ``RecipientSnapshot`` with its intent, revision, and receipt. The
    encrypted delivery coordinate, the participant email, and every other
    recipient are intentionally absent from the declared fields.
    """

    message_id = serializers.UUIDField(source="id", read_only=True)
    subject = serializers.CharField(source="intent.revision.subject", read_only=True)
    body = serializers.CharField(source="intent.revision.body", read_only=True)
    content_profile = serializers.CharField(source="intent.revision.content_profile", read_only=True)
    origin = serializers.CharField(source="intent.origin", read_only=True)
    acknowledgement_policy = serializers.CharField(source="intent.acknowledgement_policy", read_only=True)
    read_at = serializers.DateTimeField(source="receipt.read_at", read_only=True, allow_null=True)
    acknowledged_at = serializers.DateTimeField(source="receipt.acknowledged_at", read_only=True, allow_null=True)
    created_at = serializers.DateTimeField(source="intent.released_at", read_only=True, allow_null=True)


class CommunicationCampaignSummarySerializer(serializers.Serializer):
    """Organizer-facing campaign summary; carries shape and counts, never recipients."""

    id = serializers.UUIDField(read_only=True)
    title = serializers.CharField(read_only=True)
    status = serializers.CharField(read_only=True)
    origin = serializers.CharField(read_only=True)
    channels = serializers.ListField(child=serializers.CharField(), read_only=True)
    acknowledgement_policy = serializers.CharField(read_only=True)
    target_event_count = serializers.SerializerMethodField()
    created_at = serializers.DateTimeField(read_only=True)

    def get_target_event_count(self, campaign: CommunicationCampaign) -> int:
        """Return the number of events the campaign targets (no identities exposed)."""
        return campaign.target_events.count()
