"""Scoped CTF communication domain models (ADR-051, #2048).

The durable domain for scoped communications: an authoring ``CommunicationCampaign``
confined to one workspace, immutable ``MessageRevision`` content, normalized
``CommunicationIntent`` occurrences, server-resolved ``RecipientSnapshot`` rows,
per-transport ``DeliveryAttempt`` commands, and per-recipient ``ParticipantReceipt``
read/acknowledgement state.

This is the model slice of the umbrella capability (issue #2047). It is NOT a
second notification system: ``CTFNotification`` stays legacy aggregate evidence
and ``WebSocketNotification`` stays transport-replay state; neither becomes this
model. Recipient authority is always the event-scoped ``CTFParticipant`` captured
into an immutable snapshot, never an email address or ambient user.

Split from the ctf/models package for the python:S104 file-size budget; public
symbols are re-exported by ``ctf/models/__init__.py``.
"""

from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from ctf.communication_contracts import (
    CONTENT_PROFILE_V1,
    validate_acknowledgement_policy,
    validate_audience_spec,
    validate_channels,
    validate_trigger_spec,
)
from ctf.enums_communication import (
    AcknowledgementPolicy,
    CampaignStatus,
    CommunicationChannel,
    CommunicationOrigin,
    DeliveryStatus,
    IntentStatus,
    TriggerKind,
)
from shared.field_encryption import EncryptedStringField

from ._base import CTFBaseModel, ImmutableFieldsMixin
from .event import CTFEvent
from .team import CTFParticipant

# Bounds for stored reference/identity scalars. Occurrence, idempotency, and RAES
# reference values are opaque identifiers, never bodies or secrets.
_REF_MAX = 255


class CommunicationCampaign(CTFBaseModel):
    """Authoring aggregate for one scoped communication campaign (ADR-051).

    A campaign is bound to exactly one immutable workspace and may target one or
    more events, but only events that share that workspace and that the author is
    separately authorized on (enforced by the service). It is mutable only while
    ``DRAFT``.
    """

    workspace_id = models.IntegerField(
        db_index=True,
        help_text="Immutable workspace scope; every target event must share it (ADR-046/ADR-051).",
    )
    title = models.CharField(max_length=200, help_text="Organizer-facing campaign title")
    origin = models.CharField(
        max_length=32,
        choices=CommunicationOrigin.choices(),
        help_text="Source kind for provenance/audit; never an authorization grant",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="ctf_communication_campaigns",
        help_text="Session actor who authored the campaign",
    )
    actor_token_id = models.IntegerField(
        null=True,
        blank=True,
        help_text="Non-secret API-token row identity when token-authored; never raw token material",
    )
    status = models.CharField(
        max_length=16,
        choices=CampaignStatus.choices(),
        default=CampaignStatus.DRAFT.value,
        db_index=True,
        help_text="Lifecycle; mutable only while draft",
    )
    audience_spec = models.JSONField(help_text="Closed audience selector (public CTF UUIDs only; no emails/ORM)")
    trigger_spec = models.JSONField(help_text="Closed trigger declaration (data, not code)")
    channels = models.JSONField(help_text="Selected delivery channels (non-empty subset of the closed channel set)")
    acknowledgement_policy = models.CharField(
        max_length=16,
        choices=AcknowledgementPolicy.choices(),
        default=AcknowledgementPolicy.NONE.value,
        help_text="none | read | explicit",
    )
    # Annotated explicitly because django-stubs cannot infer the descriptor type
    # when ``through`` is a forward-reference string; ``from __future__ import
    # annotations`` keeps the forward reference lazy at runtime.
    target_events: models.ManyToManyField[CTFEvent, CommunicationTargetEvent] = models.ManyToManyField(
        CTFEvent,
        through="CommunicationTargetEvent",
        related_name="communication_campaigns",
        help_text="Events this campaign targets; all share the campaign workspace",
    )

    class Meta:
        """Django model metadata."""

        db_table = "ctf_communication_campaign"
        ordering = ["-created_at"]
        verbose_name = "CTF Communication Campaign"
        verbose_name_plural = "CTF Communication Campaigns"
        indexes = [
            models.Index(fields=["workspace_id", "status"]),
            models.Index(fields=["status", "created_at"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(status__in=[s.value for s in CampaignStatus]),
                name="ctf_comm_campaign_status_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(origin__in=[o.value for o in CommunicationOrigin]),
                name="ctf_comm_campaign_origin_valid",
            ),
        ]

    def __str__(self) -> str:
        """Return the campaign title."""
        return self.title

    def clean(self) -> None:
        """Validate the closed audience/trigger/channel/ack shapes (defense in depth)."""
        errors: dict[str, list[str]] = {}
        for field, validator in (
            ("audience_spec", validate_audience_spec),
            ("trigger_spec", validate_trigger_spec),
            ("channels", validate_channels),
            ("acknowledgement_policy", validate_acknowledgement_policy),
        ):
            try:
                validator(getattr(self, field))
            except Exception as exc:
                errors.setdefault(field, []).append(str(exc))
        if errors:
            raise ValidationError(errors)


class CommunicationTargetEvent(CTFBaseModel):
    """One (campaign, event) target link; the workspace match is enforced by the service."""

    campaign = models.ForeignKey(
        CommunicationCampaign,
        on_delete=models.CASCADE,
        related_name="target_event_links",
    )
    event = models.ForeignKey(CTFEvent, on_delete=models.CASCADE, related_name="communication_target_links")

    class Meta:
        """Django model metadata."""

        db_table = "ctf_communication_target_event"
        verbose_name = "CTF Communication Target Event"
        verbose_name_plural = "CTF Communication Target Events"
        constraints = [
            models.UniqueConstraint(fields=["campaign", "event"], name="ctf_comm_unique_campaign_event"),
        ]

    def __str__(self) -> str:
        """Return the (campaign, event) pair."""
        return f"{self.campaign_id}->{self.event_id}"


class MessageRevision(ImmutableFieldsMixin, CTFBaseModel):
    """Immutable, versioned content for a campaign (ADR-051).

    Editing content never mutates a revision; the service creates a new one. The
    default-locale subject/body are stored directly; locale variants and the
    render step belong to a later transport slice, keyed off ``content_profile``
    and ``default_locale``.
    """

    campaign = models.ForeignKey(
        CommunicationCampaign,
        on_delete=models.CASCADE,
        related_name="message_revisions",
    )
    revision_number = models.PositiveIntegerField(help_text="Monotonic per campaign, starting at 1")
    content_profile = models.CharField(
        max_length=64,
        default=CONTENT_PROFILE_V1,
        help_text="Versioned safe-content profile the body conforms to",
    )
    default_locale = models.CharField(max_length=35, default="en", help_text="Normalized BCP-47 default locale tag")
    subject = models.CharField(max_length=200)
    body = models.TextField(help_text="Safe-profile Markdown source (bounded, validated at creation)")
    content_digest = models.CharField(max_length=71, help_text="sha256: digest of the normalized content")

    class Meta:
        """Django model metadata."""

        db_table = "ctf_communication_message_revision"
        ordering = ["campaign", "revision_number"]
        verbose_name = "CTF Message Revision"
        verbose_name_plural = "CTF Message Revisions"
        constraints = [
            models.UniqueConstraint(fields=["campaign", "revision_number"], name="ctf_comm_unique_campaign_revision"),
        ]

    def __str__(self) -> str:
        """Return the campaign/revision identity."""
        return f"{self.campaign_id} r{self.revision_number}"

    # Editing content never mutates a revision; the service appends a new one.
    IMMUTABLE_FIELDS = (
        "subject",
        "body",
        "content_digest",
        "content_profile",
        "default_locale",
        "revision_number",
    )

    def clean(self) -> None:
        """Reject any change to a persisted revision's content (immutability)."""
        errors: dict[str, list[str]] = {}
        self.validate_immutable(errors)
        if errors:
            raise ValidationError(errors)


class CommunicationIntent(CTFBaseModel):
    """Immutable normalized occurrence produced at release (ADR-051).

    Static, manual, timed, and RAES/range sources converge here. It pins campaign,
    revision, occurrence identity, source/RAES/range references, and channel/ack
    policy. Reference scalars carry opaque identifiers only, never guest secrets or
    raw provider/RAES payloads.
    """

    campaign = models.ForeignKey(
        CommunicationCampaign,
        on_delete=models.CASCADE,
        related_name="intents",
    )
    revision = models.ForeignKey(
        MessageRevision,
        on_delete=models.PROTECT,
        related_name="intents",
        help_text="Pinned immutable content; a released intent never changes revision",
    )
    status = models.CharField(
        max_length=16,
        choices=IntentStatus.choices(),
        default=IntentStatus.SCHEDULED.value,
        help_text="scheduled | released | cancelled | fenced",
    )
    trigger_kind = models.CharField(max_length=32, choices=TriggerKind.choices())
    origin = models.CharField(max_length=32, choices=CommunicationOrigin.choices())
    actor_user_id = models.IntegerField(null=True, blank=True, help_text="Non-secret authoring user identity")
    actor_token_id = models.IntegerField(null=True, blank=True, help_text="Non-secret authoring token-row identity")
    channels = models.JSONField(help_text="Channel policy snapshot at release")
    acknowledgement_policy = models.CharField(max_length=16, choices=AcknowledgementPolicy.choices())
    occurrence_key = models.CharField(max_length=_REF_MAX, help_text="Validated occurrence identity")
    idempotency_key = models.CharField(
        max_length=_REF_MAX,
        help_text="Stable key from occurrence + range generation; a retry collapses onto it",
    )
    raes_declaration_ref = models.CharField(max_length=_REF_MAX, blank=True, default="")
    raes_occurrence_ref = models.CharField(max_length=_REF_MAX, blank=True, default="")
    scenario_digest = models.CharField(max_length=_REF_MAX, blank=True, default="")
    range_request_ref = models.CharField(max_length=_REF_MAX, blank=True, default="")
    range_generation_ref = models.CharField(
        max_length=_REF_MAX,
        blank=True,
        default="",
        db_index=True,
        help_text="Bound operation generation; range replacement fences work by this value",
    )
    policy_revision = models.CharField(max_length=_REF_MAX, blank=True, default="")
    audit_correlation_id = models.CharField(max_length=_REF_MAX, blank=True, default="")
    due_at = models.DateTimeField(null=True, blank=True, help_text="UTC due time for a timed intent")
    released_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        """Django model metadata."""

        db_table = "ctf_communication_intent"
        ordering = ["-created_at"]
        verbose_name = "CTF Communication Intent"
        verbose_name_plural = "CTF Communication Intents"
        constraints = [
            models.UniqueConstraint(fields=["idempotency_key"], name="ctf_comm_unique_intent_idempotency"),
            models.CheckConstraint(
                condition=models.Q(status__in=[s.value for s in IntentStatus]),
                name="ctf_comm_intent_status_valid",
            ),
        ]
        indexes = [
            models.Index(fields=["status", "due_at"]),
            models.Index(fields=["campaign", "status"]),
            models.Index(fields=["status", "created_at"]),
        ]

    def __str__(self) -> str:
        """Return the intent idempotency identity."""
        return self.idempotency_key


class RecipientSnapshot(CTFBaseModel):
    """Immutable, event-qualified recipient captured at intent release (ADR-051).

    One row identifies an internal CTF participant and its event/team/user
    projection. The delivery coordinate is encrypted sensitive data, never
    authority, and is erased at retention or participant removal; the immutable
    snapshot identity remains bounded historical evidence and is never retargeted.
    """

    intent = models.ForeignKey(
        CommunicationIntent,
        on_delete=models.CASCADE,
        related_name="recipient_snapshots",
    )
    event = models.ForeignKey(
        CTFEvent,
        on_delete=models.PROTECT,
        related_name="communication_recipient_snapshots",
        help_text="The event that qualifies this recipient",
    )
    participant = models.ForeignKey(
        CTFParticipant,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="communication_recipient_snapshots",
        help_text="Live participant link; cleared on hard delete while the scalar identity persists as evidence",
    )
    participant_public_id = models.UUIDField(help_text="Immutable participant identity captured at release")
    team_id = models.UUIDField(null=True, blank=True, help_text="Team projection at release")
    user_id = models.IntegerField(null=True, blank=True, db_index=True, help_text="Account projection for inbox reads")
    delivery_coordinate = EncryptedStringField(
        blank=True,
        default="",
        help_text="Encrypted delivery coordinate (e.g. email); erased at retention/removal, never authority",
    )

    class Meta:
        """Django model metadata."""

        db_table = "ctf_communication_recipient_snapshot"
        verbose_name = "CTF Recipient Snapshot"
        verbose_name_plural = "CTF Recipient Snapshots"
        constraints = [
            models.UniqueConstraint(
                fields=["intent", "participant_public_id"],
                name="ctf_comm_unique_intent_recipient",
            ),
        ]
        indexes = [
            models.Index(fields=["intent"]),
            models.Index(fields=["participant_public_id"]),
        ]

    def __str__(self) -> str:
        """Return the (intent, participant) identity."""
        return f"{self.intent_id}:{self.participant_public_id}"


class DeliveryAttempt(CTFBaseModel):
    """One durable per-transport delivery command for one recipient snapshot (ADR-051).

    Created transactionally at release; the transport worker (#2098) claims and
    sends it. Delivery is at-least-once: a stable ``(intent, snapshot, channel)``
    identity plus the unique ``(snapshot, channel)`` command row collapse enqueue
    and replay, and ``attempt_number`` distinguishes retries. Status is truthful:
    ``accepted`` means the backend accepted the message, never that it was read.

    The delivery engine (#2098) claims a command with a short lock, stamps
    ``lease_token`` and ``lease_expires_at``, then does the transport call with no
    lock held. Only a worker whose ``lease_token`` still matches may record the
    outcome, so a reclaimed stale worker cannot overwrite a newer lease. ``due_at``
    is when a ``QUEUED``/``RETRY_DUE`` command is next claimable; ``lease_expires_at``
    is when a ``CLAIMED`` command may be reclaimed. ``attempted_at`` marks the
    transport boundary (never proof of acceptance) and ``observed_at`` when the
    outcome was persisted.
    """

    intent = models.ForeignKey(
        CommunicationIntent,
        on_delete=models.CASCADE,
        related_name="delivery_attempts",
    )
    snapshot = models.ForeignKey(
        RecipientSnapshot,
        on_delete=models.CASCADE,
        related_name="delivery_attempts",
    )
    channel = models.CharField(max_length=16, choices=CommunicationChannel.choices())
    status = models.CharField(
        max_length=24,
        choices=DeliveryStatus.choices(),
        default=DeliveryStatus.QUEUED.value,
        help_text="queued | claimed | retry_due | accepted | permanent_failure | cancelled | suppressed | expired",
    )
    attempt_number = models.PositiveIntegerField(default=0, help_text="Incremented per transport retry")
    idempotency_key = models.CharField(max_length=_REF_MAX, help_text="Stable per (intent, snapshot, channel)")
    due_at = models.DateTimeField(null=True, blank=True, help_text="When the command is next due to be claimed")
    result_reason = models.CharField(max_length=64, blank=True, default="", help_text="Bounded terminal reason class")
    provider_receipt = models.CharField(
        max_length=_REF_MAX,
        blank=True,
        default="",
        help_text="Optional stable backend message identity for at-least-once de-duplication; never provider text",
    )
    lease_token = models.CharField(
        max_length=64,
        blank=True,
        default="",
        help_text="Opaque per-claim fence; a stale worker whose token no longer matches cannot record an outcome",
    )
    lease_expires_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When a CLAIMED lease may be reclaimed by another worker (stale-lease recovery)",
    )
    first_attempt_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="First transport-attempt time; the stable baseline for the elapsed-time ceiling across retries",
    )
    attempted_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Latest transport-attempt boundary: set just before the call, never proof of acceptance",
    )
    observed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the worker persisted the observed transport outcome",
    )

    class Meta:
        """Django model metadata."""

        db_table = "ctf_communication_delivery_attempt"
        verbose_name = "CTF Delivery Attempt"
        verbose_name_plural = "CTF Delivery Attempts"
        constraints = [
            models.UniqueConstraint(fields=["snapshot", "channel"], name="ctf_comm_unique_snapshot_channel"),
            models.CheckConstraint(
                condition=models.Q(status__in=[s.value for s in DeliveryStatus]),
                name="ctf_comm_delivery_status_valid",
            ),
        ]
        indexes = [
            models.Index(fields=["status", "due_at"]),
            models.Index(fields=["intent", "status"]),
            # Worker claim query: due commands for a channel with a registered adapter.
            models.Index(fields=["channel", "status", "due_at"]),
            # Stale-lease recovery sweep: CLAIMED commands past their lease expiry.
            models.Index(fields=["status", "lease_expires_at"]),
        ]

    def __str__(self) -> str:
        """Return the delivery command identity."""
        return f"{self.snapshot_id}:{self.channel}:{self.status}"


class ParticipantReceipt(CTFBaseModel):
    """Per-recipient in-app read/acknowledgement state (ADR-051).

    Kept separate from the immutable ``RecipientSnapshot`` so read/ack can change
    without touching the snapshot. ``read_at`` may be set by an authenticated
    inbox-body read; ``acknowledged_at`` only by an explicit participant action.
    Email acceptance and WebSocket publication satisfy neither.
    """

    snapshot = models.OneToOneField(
        RecipientSnapshot,
        on_delete=models.CASCADE,
        related_name="receipt",
    )
    read_at = models.DateTimeField(null=True, blank=True)
    acknowledged_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        """Django model metadata."""

        db_table = "ctf_communication_participant_receipt"
        verbose_name = "CTF Participant Receipt"
        verbose_name_plural = "CTF Participant Receipts"

    def __str__(self) -> str:
        """Return the receipt's snapshot identity."""
        return f"receipt:{self.snapshot_id}"
