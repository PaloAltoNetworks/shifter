"""CTFEvent — competition events.

Split from monolithic ctf/models.py (PR #856) to satisfy python:S104
(file too large). Public symbols are re-exported by ctf/models/__init__.py
so ``from ctf.models import X`` keeps working unchanged.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

from ctf.enums import (
    EVENT_TERMINAL_STATUSES,
    AttemptLimitMode,
    EventStatus,
    RatingVisibility,
)

from ._base import CTFBaseModel

if TYPE_CHECKING:
    from datetime import datetime

logger = logging.getLogger(__name__)


class CTFEvent(CTFBaseModel):
    """CTF competition event.

    Represents a single CTF competition with its configuration,
    schedule, and participants.

    Attributes:
        name: Event display name.
        description: Detailed event description.
        created_by: User who created the event.
        status: Current event lifecycle status.
        event_start: When the competition starts.
        event_end: When the competition ends.
        registration_deadline: Optional deadline for participant registration.
        scenario_id: ID of the range scenario template to use.
        auto_cleanup: Whether to auto-destroy ranges after event.
        cleanup_delay_hours: Hours after event end before cleanup.
        max_participants: Optional limit on participant count.
        team_mode: Whether this is a team-based competition.
        team_size_limit: Max members per team (if team_mode).
        range_spinup_minutes: Minutes before event to start provisioning.
        range_config: Range configuration (agents_by_os, ngfw_enabled, etc.).
    """

    name = models.CharField(
        max_length=200,
        help_text="Event display name",
    )
    description = models.TextField(
        blank=True,
        default="",
        help_text="Detailed event description (supports Markdown)",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="ctf_events_created",
        help_text="User who created this event",
    )
    status = models.CharField(
        max_length=20,
        choices=EventStatus.choices(),
        default=EventStatus.DRAFT.value,
        db_index=True,
        help_text="Current event lifecycle status",
    )
    event_start = models.DateTimeField(
        db_index=True,
        help_text="When the competition starts",
    )
    event_end = models.DateTimeField(
        help_text="When the competition ends",
    )
    registration_deadline = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Optional deadline for participant registration",
    )
    scenario_id = models.CharField(
        max_length=50,
        default="basic",
        help_text="ID of the range scenario template to use",
    )
    auto_cleanup = models.BooleanField(
        default=True,
        help_text="Whether to auto-destroy ranges after event ends",
    )
    cleanup_delay_hours = models.PositiveIntegerField(
        default=24,
        validators=[MinValueValidator(1), MaxValueValidator(168)],
        help_text="Hours after event end before auto-cleanup (1-168)",
    )
    max_participants = models.PositiveIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1)],
        help_text="Optional maximum number of participants",
    )
    team_mode = models.BooleanField(
        default=False,
        help_text="Whether this is a team-based competition",
    )
    team_size_limit = models.PositiveIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(2), MaxValueValidator(10)],
        help_text="Maximum team members (2-10, only for team mode)",
    )
    range_spinup_minutes = models.PositiveIntegerField(
        default=30,
        validators=[MinValueValidator(0), MaxValueValidator(1440)],
        help_text="Minutes before event start to begin range provisioning (0 = at event start)",
    )
    range_config = models.JSONField(
        default=dict,
        blank=True,
        help_text="Range configuration (agents_by_os, ngfw_enabled, etc.)",
    )
    submission_cooldown_seconds = models.PositiveIntegerField(
        default=0,
        validators=[MaxValueValidator(300)],
        help_text="Minimum seconds between flag submissions per participant per challenge (0 = no limit)",
    )
    attempt_limit_mode = models.CharField(
        max_length=20,
        choices=AttemptLimitMode.choices(),
        default=AttemptLimitMode.LOCKOUT.value,
        help_text="Behavior when max attempts reached: lockout (permanent) or timeout (temporary with cooldown)",
    )
    attempt_limit_cooldown_seconds = models.PositiveIntegerField(
        default=300,
        validators=[MaxValueValidator(3600)],
        help_text="Seconds before attempts reset when using timeout mode (0-3600)",
    )
    rating_visibility = models.CharField(
        max_length=20,
        choices=RatingVisibility.choices(),
        default=RatingVisibility.PUBLIC.value,
        help_text="Challenge rating visibility: public, organizer-only, or disabled",
    )
    scoreboard_visible = models.BooleanField(
        default=True,
        help_text="Whether the scoreboard is visible to participants. When False, participants see a hidden message.",
    )
    scoreboard_freeze_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Freeze scoreboard at this time. Solves after this time are hidden from participants.",
    )
    reminder_hours = models.JSONField(
        default=list,
        blank=True,
        help_text="Hours before event start to send reminders (e.g. [24, 1]). Empty list disables reminders.",
    )
    event_timezone = models.CharField(
        max_length=50,
        default="UTC",
        help_text="IANA timezone for displaying event times in emails (e.g. 'America/New_York')",
    )

    class Meta:
        """Django model metadata."""

        db_table = "ctf_event"
        ordering = ["-event_start"]
        verbose_name = "CTF Event"
        verbose_name_plural = "CTF Events"
        indexes = [
            models.Index(fields=["status", "event_start"]),
            models.Index(fields=["created_by", "status"]),
        ]

    def __str__(self) -> str:
        """Return event name."""
        return self.name

    def clean(self) -> None:
        """Validate event data."""
        errors: dict[str, list[str]] = {}
        self._validate_event_times(errors)
        self._validate_registration_deadline(errors)
        self._validate_team_settings(errors)
        self._validate_scoreboard_freeze_time(errors)
        if errors:
            raise ValidationError(errors)

    def _validate_event_times(self, errors: dict[str, list[str]]) -> None:
        if self.event_start and self.event_end and self.event_end <= self.event_start:
            errors.setdefault("event_end", []).append("Event end must be after event start.")

    def _validate_registration_deadline(self, errors: dict[str, list[str]]) -> None:
        if self.registration_deadline and self.event_start and self.registration_deadline > self.event_start:
            errors.setdefault("registration_deadline", []).append("Registration deadline must be before event start.")

    def _validate_team_settings(self, errors: dict[str, list[str]]) -> None:
        if self.team_mode and not self.team_size_limit:
            errors.setdefault("team_size_limit", []).append("Team size limit is required when team mode is enabled.")
        if not self.team_mode and self.team_size_limit:
            errors.setdefault("team_size_limit", []).append(
                "Team size limit should only be set when team mode is enabled."
            )

    def _validate_scoreboard_freeze_time(self, errors: dict[str, list[str]]) -> None:
        if not self.scoreboard_freeze_at:
            return
        if self.event_start and self.scoreboard_freeze_at <= self.event_start:
            errors.setdefault("scoreboard_freeze_at", []).append("Scoreboard freeze time must be after event start.")
        if self.event_end and self.scoreboard_freeze_at >= self.event_end:
            errors.setdefault("scoreboard_freeze_at", []).append("Scoreboard freeze time must be before event end.")

    @property
    def is_active(self) -> bool:
        """Return True if event is currently active."""
        return self.status == EventStatus.ACTIVE.value

    @property
    def is_upcoming(self) -> bool:
        """Return True if event is in registration but not started."""
        return self.status == EventStatus.REGISTRATION.value and self.event_start > timezone.now()

    @property
    def is_paused(self) -> bool:
        """Return True if event is currently paused."""
        return self.status == EventStatus.PAUSED.value

    @property
    def is_scoreboard_frozen(self) -> bool:
        """Return True if scoreboard is currently frozen for participants."""
        if not self.scoreboard_freeze_at:
            return False
        return timezone.now() >= self.scoreboard_freeze_at and self.status == EventStatus.ACTIVE.value

    @property
    def is_modifiable(self) -> bool:
        """Return True if event can be modified."""
        try:
            return EventStatus(self.status) not in EVENT_TERMINAL_STATUSES
        except ValueError:
            return False

    @property
    def is_content_modifiable(self) -> bool:
        """Return True if event content (challenges, etc.) can be modified.

        Content is only modifiable in DRAFT and REGISTRATION states.
        Active events should not have their challenges changed.
        """
        try:
            return EventStatus(self.status) in {EventStatus.DRAFT, EventStatus.REGISTRATION}
        except ValueError:
            return False

    @property
    def duration_hours(self) -> float:
        """Return event duration in hours."""
        delta = self.event_end - self.event_start
        return delta.total_seconds() / 3600

    @property
    def participant_count(self) -> int:
        """Return count of non-deleted participants."""
        return self.participants.count()

    @property
    def challenge_count(self) -> int:
        """Return count of non-deleted challenges."""
        return self.challenges.count()

    def get_cleanup_time(self) -> datetime:
        """Calculate when range cleanup should occur."""
        from datetime import timedelta

        return self.event_end + timedelta(hours=self.cleanup_delay_hours)

    def get_spinup_time(self) -> datetime:
        """Calculate when range provisioning should start."""
        from datetime import timedelta

        return self.event_start - timedelta(minutes=self.range_spinup_minutes)
