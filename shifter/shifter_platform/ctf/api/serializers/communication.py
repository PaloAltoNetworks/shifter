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

from typing import Any

from django.conf import settings
from rest_framework import serializers

from ctf.communication_contracts import (
    MAX_AUDIENCE_IDS,
    MAX_BODY_BYTES,
    MAX_REF_CHARS,
    MAX_SUBJECT_CODEPOINTS,
    MAX_TARGET_EVENTS,
    validate_audience_spec,
    validate_message_content,
    validate_trigger_spec,
)
from ctf.enums_communication import AcknowledgementPolicy, AudienceKind, CommunicationChannel, TriggerKind
from ctf.exceptions import CTFCommunicationError
from ctf.models import CommunicationCampaign
from shared.api.closed_serializer import ClosedSerializer
from shared.api.strict_json import ClosedJSONParser

INVALID_VALUE = "Invalid value."


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


# Write contracts deliberately enumerate every supported field. Domain validators
# own the discriminated shapes and content semantics for HTTP and internal callers.


class CommunicationJSONParser(ClosedJSONParser):
    """Allow escaped max-size content and bounded references in one envelope."""

    max_bytes = 1_048_576


class CommunicationAudienceSerializer(ClosedSerializer):
    """Closed audience variants; semantics remain in the domain contract."""

    kind = serializers.ChoiceField(choices=[v.value for v in AudienceKind])
    participant_ids = serializers.ListField(
        child=serializers.UUIDField(), min_length=1, max_length=MAX_AUDIENCE_IDS, required=False
    )
    team_ids = serializers.ListField(
        child=serializers.UUIDField(), min_length=1, max_length=MAX_AUDIENCE_IDS, required=False
    )
    event_ids = serializers.ListField(
        child=serializers.UUIDField(), min_length=1, max_length=MAX_AUDIENCE_IDS, required=False
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        normalized = {
            key: [str(v) for v in value] if isinstance(value, list) else value for key, value in attrs.items()
        }
        try:
            return validate_audience_spec(normalized)
        except CTFCommunicationError:
            raise serializers.ValidationError(INVALID_VALUE) from None


class CommunicationTriggerSerializer(ClosedSerializer):
    """Typed trigger fields with UTC/reference rules delegated to the domain."""

    kind = serializers.ChoiceField(choices=[v.value for v in TriggerKind])
    due_at = serializers.CharField(max_length=64, required=False)
    event_status = serializers.CharField(max_length=32, required=False)
    declaration_ref = serializers.CharField(max_length=MAX_REF_CHARS, required=False)
    occurrence_ref = serializers.CharField(max_length=MAX_REF_CHARS, required=False)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        try:
            return validate_trigger_spec(attrs)
        except CTFCommunicationError:
            raise serializers.ValidationError(INVALID_VALUE) from None


class CommunicationRevisionSerializer(ClosedSerializer):
    """Append-only content revision input."""

    subject = serializers.CharField(max_length=MAX_SUBJECT_CODEPOINTS, trim_whitespace=False)
    body = serializers.CharField(max_length=MAX_BODY_BYTES, allow_blank=True, trim_whitespace=False)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        try:
            content = validate_message_content(
                {key: attrs[key] for key in ("subject", "body")},
                allowed_link_hosts=settings.CTF_COMMUNICATION_ALLOWED_LINK_HOSTS,
            )
        except CTFCommunicationError:
            raise serializers.ValidationError(INVALID_VALUE) from None
        return {**attrs, "subject": content["subject"], "body": content["body"]}


class CommunicationCreateSerializer(CommunicationRevisionSerializer):
    """Organizer authoring input; actor and provenance are always server derived."""

    workspace_id = serializers.UUIDField()
    title = serializers.CharField(max_length=200)
    target_event_ids = serializers.ListField(child=serializers.UUIDField(), min_length=1, max_length=MAX_TARGET_EVENTS)
    audience_spec = CommunicationAudienceSerializer()
    trigger_spec = CommunicationTriggerSerializer()
    channels = serializers.ListField(
        child=serializers.ChoiceField(choices=[v.value for v in CommunicationChannel]), min_length=1, max_length=2
    )
    acknowledgement_policy = serializers.ChoiceField(choices=[v.value for v in AcknowledgementPolicy], default="none")


class CommunicationReleaseSerializer(ClosedSerializer):
    """Stable occurrence identity; scheduling time comes from the pinned trigger."""

    occurrence_key = serializers.RegexField(r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$", max_length=MAX_REF_CHARS)
    revision_id = serializers.UUIDField(required=False)


class CommunicationEmptySerializer(ClosedSerializer):
    """Actions with no caller-controlled state."""


class CommunicationIntentSerializer(serializers.Serializer):
    """Acceptance is distinct from channel delivery or participant interaction."""

    id = serializers.UUIDField(read_only=True)
    status = serializers.CharField(read_only=True)
    due_at = serializers.DateTimeField(read_only=True, allow_null=True)
    released_at = serializers.DateTimeField(read_only=True, allow_null=True)
