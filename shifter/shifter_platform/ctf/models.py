"""CTF models - Core data models for CTF management.

This module defines all database models for CTF event management including:
- CTFEvent: Competition events
- CTFChallenge: Individual challenges within events
- CTFTeam: Team groupings for team-based competitions
- CTFParticipant: Individual competitors
- CTFSubmission: Flag submission attempts
- CTFNotification: Event notifications
- CTFScheduledTask: Scheduled automation tasks
"""

from __future__ import annotations

import logging
import secrets
from typing import TYPE_CHECKING, TypeVar
from uuid import uuid4

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q, QuerySet, Sum
from django.utils import timezone

from ctf.enums import (
    EVENT_TERMINAL_STATUSES,
    AttemptLimitMode,
    ChallengeCategory,
    ChallengeDifficulty,
    ChallengeVisibility,
    EventStatus,
    NotificationStatus,
    NotificationType,
    ParticipantStatus,
    RatingVisibility,
    ScheduledTaskStatus,
    ScheduledTaskType,
)

if TYPE_CHECKING:
    from datetime import datetime

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# Managers
# -----------------------------------------------------------------------------


_M = TypeVar("_M", bound="CTFBaseModel")


class SoftDeleteManager(models.Manager[_M]):
    """Manager that excludes soft-deleted records by default."""

    def get_queryset(self) -> QuerySet[_M]:
        """Return queryset excluding soft-deleted records."""
        return super().get_queryset().filter(deleted_at__isnull=True)

    def with_deleted(self) -> QuerySet[_M]:
        """Return queryset including soft-deleted records."""
        return super().get_queryset()

    def deleted_only(self) -> QuerySet[_M]:
        """Return queryset with only soft-deleted records."""
        return super().get_queryset().filter(deleted_at__isnull=False)


# -----------------------------------------------------------------------------
# Abstract Base Models
# -----------------------------------------------------------------------------


class CTFBaseModel(models.Model):
    """Abstract base model for CTF entities.

    Provides common fields and behaviors for all CTF models:
    - UUID primary key for cross-system correlation
    - Timestamps for creation and updates
    - Soft delete functionality
    - Logging integration

    Attributes:
        id: UUID primary key (auto-generated).
        created_at: When this record was created.
        updated_at: When this record was last modified.
        deleted_at: Soft delete timestamp (None = active).
    """

    id = models.UUIDField(
        primary_key=True,
        default=uuid4,
        editable=False,
        help_text="Unique identifier for cross-system correlation",
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
        help_text="When this record was created",
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        help_text="When this record was last modified",
    )
    deleted_at = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
        help_text="Soft delete timestamp (null = active)",
    )

    objects = SoftDeleteManager()
    all_objects = models.Manager()  # noqa: DJ012

    class Meta:
        abstract = True

    def save(self, *args, **kwargs) -> None:
        """Save with logging and validation."""
        is_new = self._state.adding
        try:
            self.full_clean()
        except ValidationError:
            logger.exception(
                "Validation failed for %s %s",
                self.__class__.__name__,
                getattr(self, "pk", "new"),
            )
            raise

        super().save(*args, **kwargs)

        if is_new:
            logger.info(
                "Created %s: %s",
                self.__class__.__name__,
                self.pk,
            )
        else:
            logger.debug(
                "Updated %s: %s",
                self.__class__.__name__,
                self.pk,
            )

    def delete(  # type: ignore[override]
        self,
        soft: bool = True,
        using: str | None = None,
        keep_parents: bool = False,
    ) -> tuple[int, dict[str, int]]:
        """Delete record (soft delete by default).

        Args:
            soft: If True, perform soft delete. If False, permanently delete.
            *args: Additional positional arguments.
            **kwargs: Additional keyword arguments.

        Returns:
            Tuple of (number of objects deleted, dict of deleted counts by model).
        """
        if soft:
            self.deleted_at = timezone.now()
            self.save(update_fields=["deleted_at", "updated_at"])
            logger.info(
                "Soft-deleted %s: %s",
                self.__class__.__name__,
                self.pk,
            )
            return (1, {self.__class__.__name__: 1})
        else:
            logger.warning(
                "Hard-deleted %s: %s",
                self.__class__.__name__,
                self.pk,
            )
            return super().delete(using=using, keep_parents=keep_parents)

    def restore(self) -> None:
        """Restore a soft-deleted record."""
        if self.deleted_at is not None:
            self.deleted_at = None
            self.save(update_fields=["deleted_at", "updated_at"])
            logger.info(
                "Restored %s: %s",
                self.__class__.__name__,
                self.pk,
            )

    @property
    def is_deleted(self) -> bool:
        """Return True if this record has been soft-deleted."""
        return self.deleted_at is not None


# -----------------------------------------------------------------------------
# Core Models
# -----------------------------------------------------------------------------


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

    class Meta:
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

        # Validate event times (only if both are set)
        if self.event_start and self.event_end and self.event_end <= self.event_start:
            errors.setdefault("event_end", []).append("Event end must be after event start.")

        # Validate registration deadline
        if self.registration_deadline and self.event_start and self.registration_deadline > self.event_start:
            errors.setdefault("registration_deadline", []).append("Registration deadline must be before event start.")

        # Validate team settings
        if self.team_mode and not self.team_size_limit:
            errors.setdefault("team_size_limit", []).append("Team size limit is required when team mode is enabled.")
        if not self.team_mode and self.team_size_limit:
            errors.setdefault("team_size_limit", []).append(
                "Team size limit should only be set when team mode is enabled."
            )

        # Validate scoreboard freeze time
        if self.scoreboard_freeze_at:
            if self.event_start and self.scoreboard_freeze_at <= self.event_start:
                errors.setdefault("scoreboard_freeze_at", []).append(
                    "Scoreboard freeze time must be after event start."
                )
            if self.event_end and self.scoreboard_freeze_at >= self.event_end:
                errors.setdefault("scoreboard_freeze_at", []).append("Scoreboard freeze time must be before event end.")

        if errors:
            raise ValidationError(errors)

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


class CTFChallenge(CTFBaseModel):
    """Individual challenge within a CTF event.

    Attributes:
        event: The event this challenge belongs to.
        name: Challenge display name.
        description: Challenge description and instructions.
        category: Challenge category (web, crypto, etc.).
        points: Points awarded for solving.
        difficulty: Challenge difficulty level.
        flag_hash: Hashed flag value (bcrypt).
        flag_format: Optional format hint (e.g., "FLAG{...}").
        max_attempts: Maximum submission attempts (0 = unlimited).
        release_time: When challenge becomes visible (null = immediately).
        order: Display order within category.
    """

    event = models.ForeignKey(
        CTFEvent,
        on_delete=models.CASCADE,
        related_name="challenges",
        help_text="Event this challenge belongs to",
    )
    name = models.CharField(
        max_length=200,
        help_text="Challenge display name",
    )
    description = models.TextField(
        help_text="Challenge description and instructions (supports Markdown)",
    )
    category = models.CharField(
        max_length=20,
        choices=ChallengeCategory.choices(),
        db_index=True,
        help_text="Challenge category",
    )
    points = models.PositiveIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(10000)],
        help_text="Points awarded for solving (1-10000)",
    )
    difficulty = models.CharField(
        max_length=20,
        choices=ChallengeDifficulty.choices(),
        default=ChallengeDifficulty.MEDIUM.value,
        help_text="Challenge difficulty level",
    )
    flag_hash = models.CharField(
        max_length=255,
        help_text="Hashed flag value (bcrypt)",
    )
    flag_format = models.CharField(
        max_length=100,
        blank=True,
        default="",
        help_text="Optional format hint (e.g., 'FLAG{...}')",
    )
    solution = models.TextField(
        blank=True,
        default="",
        help_text="Official solution writeup (supports Markdown, visible to participants after event ends)",
    )
    max_attempts = models.PositiveIntegerField(
        default=0,
        help_text="Maximum submission attempts (0 = unlimited)",
    )
    release_time = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When challenge becomes visible (null = immediately)",
    )
    order = models.PositiveIntegerField(
        default=0,
        help_text="Display order within category",
    )
    visibility = models.CharField(
        max_length=20,
        choices=ChallengeVisibility.choices(),
        default=ChallengeVisibility.VISIBLE.value,
        db_index=True,
        help_text="Challenge visibility state (visible, hidden, locked)",
    )
    tags: models.ManyToManyField[CTFChallengeTag, CTFChallengeTag] = models.ManyToManyField(
        "CTFChallengeTag",
        blank=True,
        related_name="challenges",
        help_text="Freeform metadata tags (e.g. XDR, Linux, Windows)",
    )
    topics: models.ManyToManyField[CTFTopic, CTFTopic] = models.ManyToManyField(
        "CTFTopic",
        blank=True,
        related_name="challenges",
        help_text="Knowledge areas or attack techniques (controlled vocabulary)",
    )
    next_challenge = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="suggested_by",
        help_text="Suggested follow-up challenge after solving (non-blocking)",
    )

    class Meta:
        db_table = "ctf_challenge"
        ordering = ["category", "order", "name"]
        verbose_name = "CTF Challenge"
        verbose_name_plural = "CTF Challenges"
        constraints = [
            models.UniqueConstraint(
                fields=["event", "name"],
                condition=Q(deleted_at__isnull=True),
                name="unique_active_challenge_name_per_event",
            ),
        ]
        indexes = [
            models.Index(fields=["event", "category"]),
            models.Index(fields=["event", "release_time"]),
        ]

    def __str__(self) -> str:
        """Return challenge name with category."""
        return f"[{self.category}] {self.name}"

    def clean(self) -> None:
        """Validate challenge data."""
        errors: dict[str, list[str]] = {}

        # Validate release time
        if self.release_time and hasattr(self, "event") and self.event_id:
            if self.release_time < self.event.event_start:
                errors.setdefault("release_time", []).append("Release time cannot be before event start.")
            if self.release_time > self.event.event_end:
                errors.setdefault("release_time", []).append("Release time cannot be after event end.")

        # Validate next_challenge
        if self.next_challenge_id:
            if self.pk and self.next_challenge_id == self.pk:
                errors.setdefault("next_challenge", []).append("A challenge cannot be its own next challenge.")
            nc = self.next_challenge
            if self.event_id and nc is not None and nc.event_id != self.event_id:
                errors.setdefault("next_challenge", []).append("Next challenge must belong to the same event.")

        if errors:
            raise ValidationError(errors)

    @property
    def is_released(self) -> bool:
        """Return True if challenge is visible to participants.

        A challenge is released if it is not hidden and its release time
        (if set) has passed.
        """
        if self.visibility == ChallengeVisibility.HIDDEN.value:
            return False
        if self.release_time is None:
            return True
        return timezone.now() >= self.release_time

    @property
    def is_visibility_locked(self) -> bool:
        """Return True if challenge is explicitly locked by organizer."""
        return self.visibility == ChallengeVisibility.LOCKED.value

    @property
    def solve_count(self) -> int:
        """Return number of correct solutions."""
        return self.submissions.filter(is_correct=True).count()

    @property
    def first_blood(self) -> CTFSubmission | None:
        """Return first correct submission, if any."""
        return self.submissions.filter(is_correct=True).order_by("submitted_at").first()

    def calculate_points_with_penalty(self, total_hint_penalty: int) -> int:
        """Calculate points after cumulative hint penalty.

        Args:
            total_hint_penalty: Sum of penalties of all unlocked hints (0-100+).

        Returns:
            Points to award (minimum 1).
        """
        if total_hint_penalty > 0:
            capped = min(total_hint_penalty, 100)
            reduction = (self.points * capped) // 100
            return max(1, self.points - reduction)
        return self.points


class CTFTopic(CTFBaseModel):
    """Controlled vocabulary topic for challenges.

    Topics represent knowledge areas or attack techniques (e.g. SQL Injection,
    Privilege Escalation, Network Analysis). Unlike tags, topics are global
    (not event-scoped) and form a managed taxonomy reusable across events.

    Attributes:
        name: Topic name (e.g. "SQL Injection", "Privilege Escalation").
        description: Optional description of the topic.
    """

    name = models.CharField(
        max_length=100,
        unique=True,
        help_text="Topic name (e.g. SQL Injection, Privilege Escalation)",
    )
    description = models.TextField(
        blank=True,
        default="",
        help_text="Optional description of the topic",
    )

    class Meta:
        db_table = "ctf_topic"
        ordering = ["name"]
        verbose_name = "CTF Topic"
        verbose_name_plural = "CTF Topics"

    def __str__(self) -> str:
        """Return topic name."""
        return self.name


class CTFChallengeTag(CTFBaseModel):
    """Freeform metadata tag for challenges, scoped to an event.

    Tags provide a secondary organizational axis orthogonal to categories.
    A tag like "XDR" or "Linux" can be applied to challenges across
    different categories within the same event.

    Attributes:
        event: The event this tag belongs to.
        name: Tag label (e.g. "XDR", "Linux", "Windows").
    """

    event = models.ForeignKey(
        CTFEvent,
        on_delete=models.CASCADE,
        related_name="tags",
        help_text="Event this tag belongs to",
    )
    name = models.CharField(
        max_length=50,
        help_text="Tag label (e.g. XDR, Linux, Windows)",
    )

    class Meta:
        db_table = "ctf_challenge_tag"
        ordering = ["name"]
        verbose_name = "CTF Challenge Tag"
        verbose_name_plural = "CTF Challenge Tags"
        constraints = [
            models.UniqueConstraint(
                fields=["event", "name"],
                condition=Q(deleted_at__isnull=True),
                name="unique_active_tag_name_per_event",
            ),
        ]

    def __str__(self) -> str:
        """Return tag name."""
        return self.name


class CTFChallengeFile(CTFBaseModel):
    """File attachment for a CTF challenge.

    Stores metadata for downloadable files (binaries, pcaps, images, etc.)
    associated with a challenge. Actual file content is stored in S3.

    Attributes:
        challenge: The challenge this file belongs to.
        filename: Original filename as uploaded.
        s3_key: S3 object key for the file.
        file_size_bytes: File size in bytes.
        content_type: MIME type of the file.
        sha256_hash: SHA256 hash for integrity verification.
        display_name: Optional friendly display name.
        order: Display order.
    """

    challenge = models.ForeignKey(
        "CTFChallenge",
        on_delete=models.CASCADE,
        related_name="files",
        help_text="Challenge this file belongs to",
    )
    filename = models.CharField(
        max_length=255,
        help_text="Original filename",
    )
    s3_key = models.CharField(
        max_length=512,
        help_text="S3 object key",
    )
    file_size_bytes = models.PositiveIntegerField(
        help_text="File size in bytes",
    )
    content_type = models.CharField(
        max_length=100,
        default="application/octet-stream",
        help_text="MIME type",
    )
    sha256_hash = models.CharField(
        max_length=64,
        help_text="SHA256 hash for integrity verification",
    )
    display_name = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Optional friendly display name",
    )
    order = models.PositiveIntegerField(
        default=0,
        help_text="Display order",
    )

    class Meta:
        db_table = "ctf_challenge_file"
        ordering = ["order", "created_at"]
        verbose_name = "CTF Challenge File"
        verbose_name_plural = "CTF Challenge Files"
        indexes = [
            models.Index(fields=["challenge", "order"]),
        ]

    def __str__(self) -> str:
        """Return file description."""
        name = self.display_name or self.filename
        return f"{name} ({self.challenge.name})"

    @property
    def display(self) -> str:
        """Return display name or filename."""
        return self.display_name or self.filename

    @property
    def file_size_display(self) -> str:
        """Return human-readable file size."""
        size: float = self.file_size_bytes
        for unit in ("B", "KB", "MB", "GB"):
            if size < 1024:
                return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} {unit}"
            size /= 1024
        return f"{size:.1f} TB"


class CTFChallengePrerequisite(CTFBaseModel):
    """Prerequisite relationship between challenges.

    Defines that a challenge requires another challenge to be solved first.

    Attributes:
        challenge: The dependent challenge.
        required_challenge: The challenge that must be solved first.
    """

    challenge = models.ForeignKey(
        "CTFChallenge",
        on_delete=models.CASCADE,
        related_name="prerequisites",
        help_text="The dependent challenge",
    )
    required_challenge = models.ForeignKey(
        "CTFChallenge",
        on_delete=models.CASCADE,
        related_name="dependents",
        help_text="Challenge that must be solved first",
    )

    class Meta:
        db_table = "ctf_challenge_prerequisite"
        ordering = ["created_at"]
        verbose_name = "CTF Challenge Prerequisite"
        verbose_name_plural = "CTF Challenge Prerequisites"
        constraints = [
            models.UniqueConstraint(
                fields=["challenge", "required_challenge"],
                condition=Q(deleted_at__isnull=True),
                name="unique_active_prerequisite",
            ),
        ]
        indexes = [
            models.Index(fields=["challenge"]),
            models.Index(fields=["required_challenge"]),
        ]

    def __str__(self) -> str:
        """Return prerequisite description."""
        return f"{self.challenge.name} requires {self.required_challenge.name}"

    def clean(self) -> None:
        """Validate prerequisite data."""
        errors: dict[str, list[str]] = {}

        if hasattr(self, "challenge") and hasattr(self, "required_challenge"):
            # No self-reference
            if self.challenge_id == self.required_challenge_id:
                errors.setdefault("required_challenge", []).append("A challenge cannot be a prerequisite of itself.")

            # Same event
            if self.challenge.event_id != self.required_challenge.event_id:
                errors.setdefault("required_challenge", []).append("Prerequisites must be in the same event.")

        if errors:
            raise ValidationError(errors)


class CTFFlag(CTFBaseModel):
    """Individual flag for a CTF challenge.

    Supports multiple flags per challenge where any correct flag constitutes a solve.
    Each flag independently supports different types and case sensitivity.

    Attributes:
        challenge: The challenge this flag belongs to.
        flag_hash: Hashed flag value (static), regex pattern (regex), or sentinel
            value for programmable/http types.
        flag_type: Type of flag verification.
        case_sensitive: Whether flag comparison is case-sensitive.
        order: Display order for admin UI.
        validator_config: JSON configuration for programmable/http validators.
    """

    FLAG_TYPE_CHOICES = [
        ("static", "Static (hashed comparison)"),
        ("regex", "Regex (pattern match)"),
        ("programmable", "Programmable (custom validator)"),
        ("http", "HTTP (external endpoint)"),
    ]

    challenge = models.ForeignKey(
        "CTFChallenge",
        on_delete=models.CASCADE,
        related_name="flags",
        help_text="Challenge this flag belongs to",
    )
    flag_hash = models.CharField(
        max_length=255,
        help_text="Hashed flag value (static), regex pattern (regex), or sentinel for programmable/http",
    )
    flag_type = models.CharField(
        max_length=20,
        choices=FLAG_TYPE_CHOICES,
        default="static",
        help_text="Flag verification type",
    )
    case_sensitive = models.BooleanField(
        default=True,
        help_text="Whether flag comparison is case-sensitive",
    )
    order = models.PositiveIntegerField(
        default=0,
        help_text="Display order in admin UI",
    )
    validator_config = models.JSONField(
        null=True,
        blank=True,
        default=None,
        help_text="Configuration for programmable/http validators",
    )

    class Meta:
        db_table = "ctf_flag"
        ordering = ["order", "created_at"]
        verbose_name = "CTF Flag"
        verbose_name_plural = "CTF Flags"
        indexes = [
            models.Index(fields=["challenge", "flag_type"]),
        ]

    def __str__(self) -> str:
        """Return flag description."""
        return f"Flag #{self.order} ({self.flag_type}) for {self.challenge.name}"


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
        CTFEvent,
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
        CTFEvent,
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
        """Calculate total team score from all members (submissions + awards)."""
        result = self.members.aggregate(
            submission_total=Sum(
                "submissions__points_awarded",
                filter=Q(submissions__is_correct=True),
            ),
            award_total=Sum("awards__points"),
        )
        return (result["submission_total"] or 0) + (result["award_total"] or 0)


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
        CTFEvent,
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
    cognito_sub = models.CharField(  # noqa: DJ001
        max_length=36,
        null=True,
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
            # Token valid through event end
            if hasattr(self, "event") and self.event_id and self.event.event_end:
                self.invite_token_expires = self.event.event_end
            else:
                from datetime import timedelta

                self.invite_token_expires = timezone.now() + timedelta(days=7)
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


class CTFSubmission(CTFBaseModel):
    """Flag submission attempt by a participant.

    Records all submission attempts for auditing and scoring.

    Attributes:
        participant: The participant who submitted.
        challenge: The challenge being attempted.
        submitted_flag: The flag value submitted.
        is_correct: Whether the submission was correct.
        points_awarded: Points awarded (0 if incorrect).
        attempt_number: Which attempt this is for this challenge.
        ip_address: Client IP address for audit.
        submitted_at: When the submission was made.
    """

    participant = models.ForeignKey(
        CTFParticipant,
        on_delete=models.CASCADE,
        related_name="submissions",
        help_text="Participant who submitted",
    )
    challenge = models.ForeignKey(
        CTFChallenge,
        on_delete=models.CASCADE,
        related_name="submissions",
        help_text="Challenge being attempted",
    )
    submitted_flag = models.CharField(
        max_length=500,
        help_text="The flag value submitted (stored for audit)",
    )
    is_correct = models.BooleanField(
        default=False,
        db_index=True,
        help_text="Whether the submission was correct",
    )
    points_awarded = models.PositiveIntegerField(
        default=0,
        help_text="Points awarded for this submission",
    )
    attempt_number = models.PositiveIntegerField(
        default=1,
        help_text="Which attempt this is for this challenge",
    )
    ip_address = models.GenericIPAddressField(
        null=True,
        blank=True,
        help_text="Client IP address for audit",
    )
    submitted_at = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
        help_text="When the submission was made",
    )

    class Meta:
        db_table = "ctf_submission"
        ordering = ["-submitted_at"]
        verbose_name = "CTF Submission"
        verbose_name_plural = "CTF Submissions"
        indexes = [
            models.Index(fields=["participant", "challenge"]),
            models.Index(fields=["challenge", "is_correct"]),
            models.Index(fields=["participant", "is_correct"]),
        ]

    def __str__(self) -> str:
        """Return submission description."""
        status = "correct" if self.is_correct else "incorrect"
        return f"{self.participant.name} -> {self.challenge.name}: {status}"

    def clean(self) -> None:
        """Validate submission data."""
        errors: dict[str, list[str]] = {}

        # Validate participant and challenge belong to same event
        if (
            hasattr(self, "participant")
            and hasattr(self, "challenge")
            and self.participant.event_id != self.challenge.event_id
        ):
            errors.setdefault("challenge", []).append("Challenge must belong to participant's event.")

        if errors:
            raise ValidationError(errors)


class CTFAward(CTFBaseModel):
    """Organizer-granted award (bonus or deduction) for a participant.

    Awards allow organizers to adjust participant scores outside of
    normal flag submissions — e.g. bonus points for creative solutions,
    penalties for rule violations, or extra credit tasks.

    Attributes:
        event: The event this award belongs to.
        participant: The participant receiving the award.
        points: Points to add (positive) or deduct (negative).
        reason: Organizer's explanation for the award.
        granted_by: User who granted the award.
    """

    event = models.ForeignKey(
        CTFEvent,
        on_delete=models.CASCADE,
        related_name="awards",
        help_text="Event this award belongs to",
    )
    participant = models.ForeignKey(
        CTFParticipant,
        on_delete=models.CASCADE,
        related_name="awards",
        help_text="Participant receiving the award",
    )
    points = models.IntegerField(
        validators=[MinValueValidator(-10000), MaxValueValidator(10000)],
        help_text="Points to add (positive) or deduct (negative)",
    )
    reason = models.TextField(
        help_text="Organizer's explanation for the award",
    )
    granted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="ctf_awards_granted",
        help_text="User who granted the award",
    )

    class Meta:
        db_table = "ctf_award"
        ordering = ["-created_at"]
        verbose_name = "CTF Award"
        verbose_name_plural = "CTF Awards"
        indexes = [
            models.Index(fields=["event", "participant"]),
            models.Index(fields=["participant"]),
        ]

    def __str__(self) -> str:
        """Return award description."""
        sign = "+" if self.points >= 0 else ""
        return f"Award: {sign}{self.points} pts — {self.reason[:50]}"

    def clean(self) -> None:
        """Validate award data."""
        errors: dict[str, list[str]] = {}

        if (
            hasattr(self, "participant")
            and hasattr(self, "event")
            and self.participant_id
            and self.event_id
            and self.participant.event_id != self.event_id
        ):
            errors.setdefault("participant", []).append("Participant must belong to the same event.")

        if errors:
            raise ValidationError(errors)


class CTFChallengeRating(CTFBaseModel):
    """Participant rating of a challenge.

    Participants who have solved a challenge can rate it on a 1-5 scale.
    One rating per participant per challenge (upsert on re-rate).

    Attributes:
        participant: The participant who rated.
        challenge: The challenge being rated.
        value: Rating value (1-5).
    """

    participant = models.ForeignKey(
        CTFParticipant,
        on_delete=models.CASCADE,
        related_name="ratings",
        help_text="Participant who rated",
    )
    challenge = models.ForeignKey(
        CTFChallenge,
        on_delete=models.CASCADE,
        related_name="ratings",
        help_text="Challenge being rated",
    )
    value = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)],
        help_text="Rating value (1-5)",
    )

    class Meta:
        db_table = "ctf_challenge_rating"
        ordering = ["-created_at"]
        verbose_name = "CTF Challenge Rating"
        verbose_name_plural = "CTF Challenge Ratings"
        constraints = [
            models.UniqueConstraint(
                fields=["participant", "challenge"],
                condition=Q(deleted_at__isnull=True),
                name="unique_active_rating_per_participant_challenge",
            ),
        ]
        indexes = [
            models.Index(fields=["challenge"]),
        ]

    def __str__(self) -> str:
        """Return rating description."""
        return f"{self.participant.name} rated {self.challenge.name}: {self.value}/5"


class CTFHint(CTFBaseModel):
    """Progressive hint for a CTF challenge.

    Hints are revealed in order. Each hint has its own text and penalty.
    Cumulative penalty = sum of penalties of all unlocked hints.

    Attributes:
        challenge: The challenge this hint belongs to.
        text: The hint text content.
        penalty: Percentage of challenge points deducted for this hint (0-100).
        order: Reveal order (lower = earlier).
    """

    challenge = models.ForeignKey(
        CTFChallenge,
        on_delete=models.CASCADE,
        related_name="hints",
        help_text="Challenge this hint belongs to",
    )
    text = models.TextField(
        help_text="Hint text content",
    )
    penalty = models.PositiveIntegerField(
        default=0,
        validators=[MaxValueValidator(100)],
        help_text="Percentage of points deducted for using this hint (0-100)",
    )
    order = models.PositiveIntegerField(
        default=0,
        help_text="Reveal order (lower = earlier)",
    )

    class Meta:
        db_table = "ctf_hint"
        ordering = ["order", "created_at"]
        verbose_name = "CTF Hint"
        verbose_name_plural = "CTF Hints"
        indexes = [
            models.Index(fields=["challenge", "order"]),
        ]

    def __str__(self) -> str:
        """Return hint description."""
        return f"Hint #{self.order} for {self.challenge.name}"


class CTFHintUsage(CTFBaseModel):
    """Records which hints a participant has unlocked.

    Attributes:
        participant: The participant who unlocked the hint.
        hint: The hint that was unlocked.
        unlocked_at: When the hint was unlocked.
    """

    participant = models.ForeignKey(
        CTFParticipant,
        on_delete=models.CASCADE,
        related_name="hint_usages",
        help_text="Participant who unlocked the hint",
    )
    hint = models.ForeignKey(
        CTFHint,
        on_delete=models.CASCADE,
        related_name="usages",
        help_text="The hint that was unlocked",
    )
    unlocked_at = models.DateTimeField(
        auto_now_add=True,
        help_text="When the hint was unlocked",
    )

    class Meta:
        db_table = "ctf_hint_usage"
        ordering = ["unlocked_at"]
        verbose_name = "CTF Hint Usage"
        verbose_name_plural = "CTF Hint Usages"
        constraints = [
            models.UniqueConstraint(
                fields=["participant", "hint"],
                condition=Q(deleted_at__isnull=True),
                name="unique_active_hint_usage",
            ),
        ]
        indexes = [
            models.Index(fields=["participant", "hint"]),
        ]

    def __str__(self) -> str:
        """Return usage description."""
        return f"{self.participant.name} unlocked {self.hint}"


class CTFNotification(CTFBaseModel):
    """Notification record for CTF events.

    Tracks scheduled and sent notifications.

    Attributes:
        event: The event this notification belongs to.
        notification_type: Type of notification.
        subject: Email subject line.
        body: Email body content.
        status: Current notification status.
        recipient_filter: Who should receive (all, organizers, participants).
        recipient_emails: Specific emails for individual targeting.
        scheduled_at: When to send (null = immediate).
        sent_at: When actually sent.
        sent_count: Number of emails sent.
        error_message: Error details if failed.
        created_by: User who created notification.
    """

    event = models.ForeignKey(
        CTFEvent,
        on_delete=models.CASCADE,
        related_name="notifications",
        help_text="Event this notification belongs to",
    )
    notification_type = models.CharField(
        max_length=20,
        choices=NotificationType.choices(),
        help_text="Type of notification",
    )
    subject = models.CharField(
        max_length=200,
        help_text="Email subject line",
    )
    body = models.TextField(
        help_text="Email body content (supports Markdown)",
    )
    status = models.CharField(
        max_length=20,
        choices=NotificationStatus.choices(),
        default=NotificationStatus.DRAFT.value,
        db_index=True,
        help_text="Current notification status",
    )
    recipient_filter = models.CharField(
        max_length=20,
        choices=[
            ("all", "All Participants"),
            ("organizers", "Organizers Only"),
            ("participants", "Participants Only"),
            ("individual", "Individual Recipients"),
        ],
        default="participants",
        help_text="Who should receive this notification",
    )
    recipient_emails = models.JSONField(
        default=list,
        blank=True,
        help_text="Specific emails for individual targeting",
    )
    scheduled_at = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
        help_text="When to send (null = immediate)",
    )
    sent_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When actually sent",
    )
    sent_count = models.PositiveIntegerField(
        default=0,
        help_text="Number of emails sent",
    )
    error_message = models.TextField(
        blank=True,
        default="",
        help_text="Error details if failed",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="ctf_notifications_created",
        help_text="User who created notification",
    )

    class Meta:
        db_table = "ctf_notification"
        ordering = ["-created_at"]
        verbose_name = "CTF Notification"
        verbose_name_plural = "CTF Notifications"
        indexes = [
            models.Index(fields=["event", "status"]),
            models.Index(fields=["status", "scheduled_at"]),
        ]

    def __str__(self) -> str:
        """Return notification description."""
        return f"[{self.notification_type}] {self.subject}"


class CTFScheduledTask(CTFBaseModel):
    """Scheduled automation task for CTF events.

    Tracks tasks like range provisioning and cleanup.

    Note: Tasks are database records only -- no background worker (e.g. Celery)
    auto-executes them yet. A management command or cron job is needed to poll
    for due tasks and run them.

    Attributes:
        event: The event this task belongs to.
        task_type: Type of scheduled task.
        scheduled_for: When the task should execute.
        executed_at: When the task was executed.
        status: Current task status.
        error_message: Error details if failed.
        metadata: Additional task-specific data.
    """

    event = models.ForeignKey(
        CTFEvent,
        on_delete=models.CASCADE,
        related_name="scheduled_tasks",
        help_text="Event this task belongs to",
    )
    task_type = models.CharField(
        max_length=30,
        choices=ScheduledTaskType.choices(),
        help_text="Type of scheduled task",
    )
    scheduled_for = models.DateTimeField(
        db_index=True,
        help_text="When the task should execute",
    )
    executed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the task was executed",
    )
    status = models.CharField(
        max_length=20,
        choices=ScheduledTaskStatus.choices(),
        default=ScheduledTaskStatus.PENDING.value,
        db_index=True,
        help_text="Current task status",
    )
    error_message = models.TextField(
        blank=True,
        default="",
        help_text="Error details if failed",
    )
    metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text="Additional task-specific data",
    )

    class Meta:
        db_table = "ctf_scheduled_task"
        ordering = ["scheduled_for"]
        verbose_name = "CTF Scheduled Task"
        verbose_name_plural = "CTF Scheduled Tasks"
        indexes = [
            models.Index(fields=["status", "scheduled_for"]),
            models.Index(fields=["event", "task_type"]),
        ]

    def __str__(self) -> str:
        """Return task description."""
        return f"[{self.task_type}] {self.event.name} @ {self.scheduled_for}"

    @property
    def is_due(self) -> bool:
        """Return True if task is ready to execute."""
        return self.status == ScheduledTaskStatus.PENDING.value and timezone.now() >= self.scheduled_for

    def mark_running(self) -> None:
        """Mark task as running."""
        self.status = ScheduledTaskStatus.RUNNING.value
        self.save(update_fields=["status", "updated_at"])
        logger.info("Task %s started: %s", self.task_type, self.pk)

    def mark_completed(self) -> None:
        """Mark task as completed."""
        self.status = ScheduledTaskStatus.COMPLETED.value
        self.executed_at = timezone.now()
        self.save(update_fields=["status", "executed_at", "updated_at"])
        logger.info("Task %s completed: %s", self.task_type, self.pk)

    def mark_failed(self, error: str) -> None:
        """Mark task as failed.

        Args:
            error: Error message to record.
        """
        self.status = ScheduledTaskStatus.FAILED.value
        self.executed_at = timezone.now()
        self.error_message = error
        self.save(update_fields=["status", "executed_at", "error_message", "updated_at"])
        logger.error("Task %s failed: %s - %s", self.task_type, self.pk, error)

    def mark_cancelled(self) -> None:
        """Mark task as cancelled."""
        self.status = ScheduledTaskStatus.CANCELLED.value
        self.save(update_fields=["status", "updated_at"])
        logger.info("Task %s cancelled: %s", self.task_type, self.pk)
