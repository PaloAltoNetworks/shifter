"""Organizer serializers for the canonical CTF DRF API: participant / range / notification / scoreboard ops.

Typed request/response projections for the organizer participant-management,
range-lifecycle, notification/email-template, and scoreboard endpoints.
"""

from __future__ import annotations

from rest_framework import serializers

from ctf.api.serializers._common import _NamedRefSerializer
from ctf.api.serializers.organizer import AwardSerializer

# ---------------------------------------------------------------------------
# Organizer serializers (participant management)
# ---------------------------------------------------------------------------


class ParticipantSummarySerializer(serializers.Serializer):
    """List projection of one participant for an event."""

    id = serializers.CharField(read_only=True)
    name = serializers.CharField(read_only=True)
    email = serializers.CharField(read_only=True)
    status = serializers.CharField(read_only=True)
    role = serializers.CharField(read_only=True)
    hidden = serializers.BooleanField(read_only=True)
    team_name = serializers.CharField(read_only=True, allow_null=True)
    registered_at = serializers.DateTimeField(read_only=True, allow_null=True)
    total_score = serializers.IntegerField(read_only=True)


class ParticipantListResponseSerializer(serializers.Serializer):
    """Envelope returned by the event participant list."""

    participants = ParticipantSummarySerializer(many=True, read_only=True)
    total = serializers.IntegerField(read_only=True)


class ParticipantInviteSerializer(serializers.Serializer):
    """Request body for inviting a single participant.

    ``name`` and ``email`` are both required and non-blank (mirroring the legacy
    truthiness check). ``email`` is a plain ``CharField`` rather than an
    ``EmailField`` because the service layer owns email validation.
    """

    name = serializers.CharField()
    email = serializers.CharField()


class ParticipantInviteResultSerializer(serializers.Serializer):
    """Result returned after inviting a single participant."""

    id = serializers.CharField(read_only=True)
    name = serializers.CharField(read_only=True)
    email = serializers.CharField(read_only=True)
    status = serializers.CharField(read_only=True)
    invited = serializers.BooleanField(read_only=True)


class ParticipantImportSerializer(serializers.Serializer):
    """Request body for bulk-importing participants.

    ``participants`` is typed as a bare list (each element validated per-item in
    the view, mirroring the legacy #1149 handling) rather than a strict
    ``ListField(child=DictField())``: a non-list still 400s at this layer, but a
    list carrying non-object elements must yield per-item errors, not a
    top-level 400.
    """

    participants = serializers.ListField(required=False, default=list)


class ParticipantImportedItemSerializer(serializers.Serializer):
    """One successfully imported participant."""

    id = serializers.CharField(read_only=True)
    name = serializers.CharField(read_only=True)
    email = serializers.CharField(read_only=True)


class ParticipantImportErrorSerializer(serializers.Serializer):
    """One per-row import error (``email`` present only for service failures)."""

    index = serializers.IntegerField(read_only=True)
    email = serializers.CharField(read_only=True, required=False)
    error = serializers.CharField(read_only=True)


class ParticipantImportResultSerializer(serializers.Serializer):
    """Summary returned by a bulk import."""

    imported = serializers.IntegerField(read_only=True)
    participants = ParticipantImportedItemSerializer(many=True, read_only=True)
    errors = ParticipantImportErrorSerializer(many=True, read_only=True)


class ParticipantDetailSerializer(serializers.Serializer):
    """Full organizer-facing participant detail projection."""

    id = serializers.CharField(read_only=True)
    name = serializers.CharField(read_only=True)
    email = serializers.CharField(read_only=True)
    status = serializers.CharField(read_only=True)
    status_reason = serializers.CharField(read_only=True, allow_blank=True)
    role = serializers.CharField(read_only=True)
    hidden = serializers.BooleanField(read_only=True)
    affiliation = serializers.CharField(read_only=True, allow_blank=True)
    username = serializers.CharField(read_only=True, allow_null=True)
    team_name = serializers.CharField(read_only=True, allow_null=True)
    registered_at = serializers.DateTimeField(read_only=True, allow_null=True)
    invited_at = serializers.DateTimeField(read_only=True, allow_null=True)
    last_active_at = serializers.DateTimeField(read_only=True, allow_null=True)
    total_score = serializers.IntegerField(read_only=True)
    solved_count = serializers.IntegerField(read_only=True)
    attempt_count = serializers.IntegerField(read_only=True)
    event_id = serializers.CharField(read_only=True)
    bracket_id = serializers.CharField(read_only=True, allow_null=True)
    bracket_name = serializers.CharField(read_only=True, allow_null=True)
    awards = AwardSerializer(many=True, read_only=True)


class ParticipantDeleteResultSerializer(serializers.Serializer):
    """Confirmation returned after soft-deleting a participant."""

    deleted = serializers.BooleanField(read_only=True)
    id = serializers.CharField(read_only=True)


class ResendInviteResultSerializer(serializers.Serializer):
    """Confirmation returned after resetting and resending a participant invite."""

    success = serializers.BooleanField(read_only=True)
    id = serializers.CharField(read_only=True)
    invited = serializers.BooleanField(read_only=True)


class AssignBracketRequestSerializer(serializers.Serializer):
    """Request body for assigning or removing a participant's bracket.

    ``bracket_id`` is typed loosely (nullable string) so the view keeps the
    legacy branch mapping: a malformed value 400s as ``Invalid bracket ID
    format``, a same-event violation 400s, an unknown bracket 404s, and ``null``
    removes the current bracket.
    """

    bracket_id = serializers.CharField(required=False, allow_null=True, allow_blank=True)


class AssignBracketResultSerializer(serializers.Serializer):
    """Result returned after assigning or removing a participant's bracket."""

    status = serializers.CharField(read_only=True)
    bracket = _NamedRefSerializer(read_only=True, allow_null=True)


# ---------------------------------------------------------------------------
# Range lifecycle serializers (participant status/access + organizer range ops)
# ---------------------------------------------------------------------------


class RangeTargetInstanceSerializer(serializers.Serializer):
    """A participant-safe target box in a ready range (issue #1740).

    Documents the projected {uuid, name, private_ip, os_type} allowlist. The
    ``ctf.bridges.cms_get_range_target_instances`` projection is what enforces the
    allowlist at runtime; this serializer only publishes the contract.
    """

    uuid = serializers.CharField(read_only=True)
    name = serializers.CharField(read_only=True)
    private_ip = serializers.CharField(read_only=True)
    os_type = serializers.CharField(read_only=True)


class RangeStatusResponseSerializer(serializers.Serializer):
    """Participant range status projection (or the not-assigned sentinel)."""

    participant_id = serializers.CharField(read_only=True, required=False)
    status = serializers.CharField(read_only=True)
    range_instance_id = serializers.IntegerField(read_only=True, allow_null=True)
    vpn_profile_available = serializers.BooleanField(read_only=True, default=False)
    target_instances = RangeTargetInstanceSerializer(many=True, read_only=True, required=False)


class RangeAccessResponseSerializer(serializers.Serializer):
    """Redirect pointer to the mission_control Guacamole RDP endpoint."""

    redirect = serializers.CharField(read_only=True)
    message = serializers.CharField(read_only=True)


class RangeListItemSerializer(serializers.Serializer):
    """A single participant's range row in the organizer range list."""

    participant_id = serializers.CharField(read_only=True)
    name = serializers.CharField(read_only=True)
    email = serializers.CharField(read_only=True)
    range_instance_id = serializers.IntegerField(read_only=True, allow_null=True)
    range_status = serializers.CharField(read_only=True)


class RangeListResponseSerializer(serializers.Serializer):
    """Organizer range list plus the provisioning-progress projection."""

    event_id = serializers.CharField(read_only=True)
    ranges = RangeListItemSerializer(many=True, read_only=True)
    progress = serializers.DictField(read_only=True)


class RangeProvisionQueuedSerializer(serializers.Serializer):
    """Acknowledgement returned when bulk range provisioning is enqueued."""

    event_id = serializers.CharField(read_only=True)
    status = serializers.CharField(read_only=True)
    task_id = serializers.CharField(read_only=True)
    task_status = serializers.CharField(read_only=True)


class ParticipantRangeActionResultSerializer(serializers.Serializer):
    """Pass-through result of a single-participant range lifecycle action."""

    participant_id = serializers.CharField(read_only=True, required=False)
    range_instance_id = serializers.IntegerField(read_only=True, allow_null=True, required=False)
    status = serializers.CharField(read_only=True, required=False)


class RangeRecoveryRequestSerializer(serializers.Serializer):
    """Organizer range-recovery request body (issue #1018).

    ``strategy`` and ``spare_range_instance_id`` are typed loosely so the view
    keeps the legacy boundary validation (a non-string strategy or a
    non-positive-int spare id both 400) while the service validates ``strategy``
    against ``ctf.enums`` and resolves/validates the spare range itself.
    """

    strategy = serializers.CharField()
    spare_range_instance_id = serializers.IntegerField(required=False, allow_null=True)


class RangeRecoveryResultSerializer(serializers.Serializer):
    """Result returned after a range recovery attempt."""

    recovery_id = serializers.CharField(read_only=True)
    participant_id = serializers.CharField(read_only=True)
    event_id = serializers.CharField(read_only=True)
    old_range_instance_id = serializers.IntegerField(read_only=True, allow_null=True)
    replacement_range_instance_id = serializers.IntegerField(read_only=True, allow_null=True)
    replacement_request_id = serializers.CharField(read_only=True, allow_null=True)
    strategy = serializers.CharField(read_only=True)
    phase = serializers.CharField(read_only=True)
    failure_category = serializers.CharField(read_only=True, allow_null=True)


class SparePoolRequestSerializer(serializers.Serializer):
    """Organizer spare-pool top-up request body (``count`` bounded non-negative)."""

    count = serializers.IntegerField()


class SpareProvisionResultSerializer(serializers.Serializer):
    """Summary returned after topping up an event's spare-range pool."""

    event_id = serializers.CharField(read_only=True)
    target_count = serializers.IntegerField(read_only=True)
    existing = serializers.IntegerField(read_only=True)
    created = serializers.IntegerField(read_only=True)


class SendInvitationsResultSerializer(serializers.Serializer):
    """Result returned after queuing invitation emails for an event."""

    success = serializers.BooleanField(read_only=True)
    event_id = serializers.CharField(read_only=True)
    total = serializers.IntegerField(read_only=True)
    sent = serializers.IntegerField(read_only=True)
    failed = serializers.IntegerField(read_only=True)


# ---------------------------------------------------------------------------
# Notification serializers (organizer announcements + email-template overrides)
# ---------------------------------------------------------------------------


class NotificationListItemSerializer(serializers.Serializer):
    """List projection of one notification for an event."""

    id = serializers.CharField(read_only=True)
    notification_type = serializers.CharField(read_only=True)
    subject = serializers.CharField(read_only=True, allow_blank=True)
    status = serializers.CharField(read_only=True)
    sent_count = serializers.IntegerField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)
    sent_at = serializers.DateTimeField(read_only=True, allow_null=True)
    scheduled_at = serializers.DateTimeField(read_only=True, allow_null=True)


class NotificationListResponseSerializer(serializers.Serializer):
    """Envelope returned by the event notification list."""

    notifications = NotificationListItemSerializer(many=True, read_only=True)


class NotificationAnnounceRequestSerializer(serializers.Serializer):
    """Request body for sending an announcement notification.

    ``subject`` and ``body`` are blank-tolerant at this layer so the view can
    apply the legacy strip-then-reject rule and return the exact ``Invalid
    notification request.`` 400 envelope for an empty or whitespace-only value.
    """

    subject = serializers.CharField(required=False, allow_blank=True, default="")
    body = serializers.CharField(required=False, allow_blank=True, default="")
    scheduled_at = serializers.DateTimeField(required=False, allow_null=True)


class NotificationAnnounceResultSerializer(serializers.Serializer):
    """Result returned after creating and sending an announcement (201)."""

    id = serializers.CharField(read_only=True)
    subject = serializers.CharField(read_only=True, allow_blank=True)
    status = serializers.CharField(read_only=True)
    sent_count = serializers.IntegerField(read_only=True)


class NotificationSendResultSerializer(serializers.Serializer):
    """Result returned after dispatching a notification to its recipients."""

    notification_id = serializers.CharField(read_only=True)
    status = serializers.CharField(read_only=True)


class EmailTemplateWriteSerializer(serializers.Serializer):
    """Request body for creating/updating a per-event email-template override.

    Fields are blank-tolerant so the view keeps the legacy validation: a missing
    or empty ``html_body`` / ``text_body`` and any disallowed template syntax
    both surface as a controlled 400. Organizer templates are restricted to the
    flat ``{{ name }}`` placeholder grammar over the per-notification-type
    allowlist enforced by ``ctf.services.email_template`` (CWE-1336, issue #1095).
    """

    subject = serializers.CharField(required=False, allow_blank=True, default="")
    html_body = serializers.CharField(required=False, allow_blank=True, default="")
    text_body = serializers.CharField(required=False, allow_blank=True, default="")


class EmailTemplateResponseSerializer(serializers.Serializer):
    """Per-event email-template override projection."""

    id = serializers.CharField(read_only=True)
    notification_type = serializers.CharField(read_only=True)
    subject = serializers.CharField(read_only=True, allow_blank=True)
    html_body = serializers.CharField(read_only=True, allow_blank=True)
    text_body = serializers.CharField(read_only=True, allow_blank=True)


class EmailTemplateRevertResultSerializer(serializers.Serializer):
    """Confirmation returned after reverting a template to the platform default."""

    status = serializers.CharField(read_only=True)


# ---------------------------------------------------------------------------
# Scoreboard serializers (per-participant timeline + public scoreboard)
# ---------------------------------------------------------------------------


class ScoreTimelineResponseSerializer(serializers.Serializer):
    """Per-participant chronological score progression for a step chart."""

    participant_id = serializers.CharField(read_only=True)
    participant_name = serializers.CharField(read_only=True)
    timeline = serializers.ListField(child=serializers.DictField(), read_only=True)


class PublicScoreboardResponseSerializer(serializers.Serializer):
    """Public scoreboard read surface.

    The runtime returns one of two shapes: the ``{"scoreboard_hidden": true}``
    sentinel when the event hides its scoreboard, or the full ranking payload
    (``event_id``, ``team_mode``, ``frozen``, ``rankings``, ``bracket_rankings``,
    ``brackets``). Every field is optional so this one serializer documents the
    union without changing the view's runtime ``JsonResponse``.
    """

    scoreboard_hidden = serializers.BooleanField(read_only=True, required=False)
    event_id = serializers.CharField(read_only=True, required=False)
    team_mode = serializers.BooleanField(read_only=True, required=False)
    frozen = serializers.BooleanField(read_only=True, required=False)
    rankings = serializers.ListField(child=serializers.DictField(), read_only=True, required=False)
    bracket_rankings = serializers.ListField(
        child=serializers.DictField(), read_only=True, required=False, allow_null=True
    )
    brackets = _NamedRefSerializer(many=True, read_only=True, required=False)


class OrganizerScoreboardResponseSerializer(serializers.Serializer):
    """Organizer monitoring scoreboard — always the full ranking payload.

    Unlike :class:`PublicScoreboardResponseSerializer`, this projection never
    carries the ``scoreboard_hidden`` sentinel and never withholds rows: an
    organizer sees every ranking regardless of the event's ``scoreboard_visible``
    flag or freeze window. ``frozen`` is reported for display only; the rankings
    are computed as of now (``freeze_at=None``).
    """

    event_id = serializers.CharField(read_only=True)
    team_mode = serializers.BooleanField(read_only=True)
    frozen = serializers.BooleanField(read_only=True)
    rankings = serializers.ListField(child=serializers.DictField(), read_only=True)
    bracket_rankings = serializers.ListField(child=serializers.DictField(), read_only=True, allow_null=True)
    brackets = _NamedRefSerializer(many=True, read_only=True)
