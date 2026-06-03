"""CTFBracket, CTFTeam, CTFParticipant — participant grouping models.

Split from monolithic ctf/models.py (PR #856) to satisfy python:S104
(file too large). Public symbols are re-exported by ctf/models/__init__.py
so ``from ctf.models import X`` keeps working unchanged.
"""

from __future__ import annotations

import logging
import secrets

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q, Sum
from django.utils import timezone

from ctf.enums import (
    ParticipantStatus,
)

from ._base import CTFBaseModel

logger = logging.getLogger(__name__)


class CTFBracket(CTFBaseModel):
    """Named bracket for grouping participants by skill level.

    Brackets enable fair competition in mixed-experience events by
    providing separate scoreboards per bracket (e.g. beginner,
    intermediate, advanced).

    Attributes:
        event: The event this bracket belongs to.
        name: Bracket display name.
        description: Optional description of this bracket.
        display_order: Sort order for bracket tabs.
    """

    event = models.ForeignKey(
        "CTFEvent",
        on_delete=models.CASCADE,
        related_name="brackets",
        help_text="Event this bracket belongs to",
    )
    name = models.CharField(
        max_length=100,
        help_text="Bracket display name (e.g. Beginner, Intermediate, Advanced)",
    )
    description = models.TextField(
        blank=True,
        default="",
        help_text="Optional bracket description",
    )
    display_order = models.PositiveIntegerField(
        default=0,
        help_text="Sort order for bracket display (lower = first)",
    )

    class Meta:
        """Django model metadata."""

        db_table = "ctf_bracket"
        ordering = ["display_order", "name"]
        verbose_name = "CTF Bracket"
        verbose_name_plural = "CTF Brackets"
        constraints = [
            models.UniqueConstraint(
                fields=["event", "name"],
                condition=Q(deleted_at__isnull=True),
                name="unique_active_bracket_name_per_event",
            ),
        ]

    def __str__(self) -> str:
        """Return bracket name."""
        return self.name

    @property
    def participant_count(self) -> int:
        """Return count of participants in this bracket."""
        return self.participants.count()


class CTFTeam(CTFBaseModel):
    """Team for team-based CTF competitions.

    Attributes:
        event: The event this team belongs to.
        name: Team display name.
        invite_code: Code for joining the team.
        captain: Team captain (first member or designated).
    """

    event = models.ForeignKey(
        "CTFEvent",
        on_delete=models.CASCADE,
        related_name="teams",
        help_text="Event this team belongs to",
    )
    name = models.CharField(
        max_length=100,
        help_text="Team display name",
    )
    invite_code = models.CharField(
        max_length=32,
        unique=True,
        db_index=True,
        help_text="Code for joining the team",
    )
    captain = models.ForeignKey(
        "CTFParticipant",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="captained_teams",
        help_text="Team captain",
    )

    class Meta:
        """Django model metadata."""

        db_table = "ctf_team"
        ordering = ["name"]
        verbose_name = "CTF Team"
        verbose_name_plural = "CTF Teams"
        constraints = [
            models.UniqueConstraint(
                fields=["event", "name"],
                condition=Q(deleted_at__isnull=True),
                name="unique_active_team_name_per_event",
            ),
        ]

    def __str__(self) -> str:
        """Return team name."""
        return self.name

    def save(self, *args, **kwargs) -> None:
        """Generate invite code on first save."""
        if not self.invite_code:
            self.invite_code = secrets.token_urlsafe(16)
        super().save(*args, **kwargs)

    @property
    def member_count(self) -> int:
        """Return count of team members."""
        return self.members.count()

    @property
    def is_full(self) -> bool:
        """Return True if team is at capacity."""
        if not self.event.team_size_limit:
            return False
        return self.member_count >= self.event.team_size_limit

    @property
    def total_score(self) -> int:
        """Calculate total team score from eligible members (submissions + awards).

        Codex review (#765/#768/#769 cycle 5 + cycle 7):
          - Cycle 5: aggregating both `submissions` and `awards` on the
            same `self.members` queryset joined them in one SQL query, so
            a member with both a solve and an award caused the
            cartesian-product row multiplication and inflated the total.
            Aggregate the two relations separately.
          - Cycle 7: filter members by `eligible_participant_q()` so a
            disqualified or unregistered teammate's solves/awards do not
            appear in the participant-visible team score (the official
            `get_team_scoreboard` already excludes them).
        """
        from ctf.models import CTFAward, CTFSubmission
        from ctf.services.participant import eligible_participant_q

        eligible_member_ids = self.members.filter(eligible_participant_q()).values_list("id", flat=True)
        submission_total = (
            CTFSubmission.objects.filter(participant_id__in=eligible_member_ids, is_correct=True).aggregate(
                t=Sum("points_awarded")
            )["t"]
            or 0
        )
        award_total = (
            CTFAward.objects.filter(participant_id__in=eligible_member_ids).aggregate(t=Sum("points"))["t"] or 0
        )
        return submission_total + award_total


class CTFParticipant(CTFBaseModel):
    """Individual participant in a CTF event.

    Participants can be invited before they register. Once registered,
    they are linked to a User account.

    Attributes:
        event: The event this participant belongs to.
        user: Linked user account (null before registration).
        email: Participant email (for invitation).
        name: Display name.
        team: Optional team membership.
        cognito_sub: Cognito subject identifier (set on registration).
        status: Current participant lifecycle status.
        range_instance_id: Linked CMS RangeInstance ID.
        range_status: Cached range status for quick lookups.
        invite_token: Secure token for registration link.
        invite_token_expires: When the invite token expires.
        invited_at: When invitation was sent.
        registered_at: When user completed registration.
        last_active_at: Last activity timestamp.
    """

    event = models.ForeignKey(
        "CTFEvent",
        on_delete=models.CASCADE,
        related_name="participants",
        help_text="Event this participant belongs to",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ctf_participations",
        help_text="Linked user account (null before registration)",
    )
    email = models.EmailField(
        db_index=True,
        help_text="Participant email",
    )
    name = models.CharField(
        max_length=100,
        help_text="Display name",
    )
    team = models.ForeignKey(
        CTFTeam,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="members",
        help_text="Team membership (for team-based events)",
    )
    bracket = models.ForeignKey(
        CTFBracket,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="participants",
        help_text="Bracket assignment (for bracket-based events)",
    )
    # DJ001 (CharField with null=True should not allow blank=True without
    # choices) and Sonar's python:S6553 ("remove this null=True") are
    # intentionally suppressed: cognito_sub is genuinely optional for
    # non-Cognito participants (e.g. email-only invites), so both null and
    # blank are legitimate "no value yet" sentinels rather than competing
    # zero-value representations. Removing null=True would force every
    # legacy non-Cognito participant row to migrate to an empty-string
    # sentinel.
    cognito_sub = models.CharField(  # noqa: DJ001
        max_length=36,
        null=True,  # NOSONAR
        blank=True,
        db_index=True,
        help_text="Cognito user pool subject identifier",
    )
    status = models.CharField(
        max_length=20,
        choices=ParticipantStatus.choices(),
        default=ParticipantStatus.INVITED.value,
        db_index=True,
        help_text="Current participant lifecycle status",
    )
    range_instance_id = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Linked CMS RangeInstance ID",
    )
    range_status = models.CharField(
        max_length=20,
        blank=True,
        default="",
        help_text="Cached range status for quick lookups",
    )
    invite_token = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
        help_text="Secure token for registration link",
    )
    invite_token_expires = models.DateTimeField(
        help_text="When the invite token expires",
    )
    invited_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When invitation was sent",
    )
    registered_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When user completed registration",
    )
    last_active_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Last activity timestamp",
    )

    class Meta:
        """Django model metadata."""

        db_table = "ctf_participant"
        ordering = ["name"]
        verbose_name = "CTF Participant"
        verbose_name_plural = "CTF Participants"
        constraints = [
            models.UniqueConstraint(
                fields=["event", "email"],
                condition=Q(deleted_at__isnull=True),
                name="unique_active_participant_email_per_event",
            ),
        ]
        indexes = [
            models.Index(fields=["event", "status"]),
            models.Index(fields=["event", "team"]),
        ]

    def __str__(self) -> str:
        """Return participant name with email."""
        return f"{self.name} <{self.email}>"

    def save(self, *args, **kwargs) -> None:
        """Generate invite token on first save."""
        if not self.invite_token:
            self.invite_token = secrets.token_urlsafe(32)
        if not self.invite_token_expires:
            from datetime import timedelta

            from django.conf import settings

            hours = getattr(settings, "MAGIC_LINK_EXPIRY_HOURS", 24)
            config_expiry = timezone.now() + timedelta(hours=hours)
            if hasattr(self, "event") and self.event_id and self.event.event_end:
                # Use the earlier of event end or configured expiry
                self.invite_token_expires = min(self.event.event_end, config_expiry)
            else:
                self.invite_token_expires = config_expiry
        super().save(*args, **kwargs)

    def clean(self) -> None:
        """Validate participant data."""
        errors: dict[str, list[str]] = {}

        # Validate team membership
        if self.team:
            if not self.event.team_mode:
                errors.setdefault("team", []).append("Cannot join a team in non-team-mode event.")
            elif self.team.event_id != self.event_id:
                errors.setdefault("team", []).append("Team must belong to the same event.")

        if errors:
            raise ValidationError(errors)

    @property
    def is_registered(self) -> bool:
        """Return True if participant has completed registration."""
        return self.user is not None and self.registered_at is not None

    @property
    def is_invite_valid(self) -> bool:
        """Return True if invite token is still valid."""
        return self.invite_token_expires is not None and timezone.now() < self.invite_token_expires

    @property
    def total_score(self) -> int:
        """Calculate participant's total score (submissions + awards)."""
        submission_result = self.submissions.filter(is_correct=True).aggregate(total=Sum("points_awarded"))
        award_result = self.awards.aggregate(total=Sum("points"))
        return (submission_result["total"] or 0) + (award_result["total"] or 0)

    @property
    def solved_challenge_count(self) -> int:
        """Return count of correctly solved challenges."""
        return self.submissions.filter(is_correct=True).count()

    def update_last_active(self) -> None:
        """Update last_active_at timestamp."""
        self.last_active_at = timezone.now()
        self.save(update_fields=["last_active_at", "updated_at"])
