"""CTFChallenge — individual challenges within events.

Split from monolithic ctf/models.py (PR #856) to satisfy python:S104
(file too large). Public symbols are re-exported by ctf/models/__init__.py
so ``from ctf.models import X`` keeps working unchanged.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone

from ctf.enums import (
    ChallengeCategory,
    ChallengeDifficulty,
    ChallengeVisibility,
)

from ._base import CTFBaseModel

if TYPE_CHECKING:
    from .submission import CTFSubmission
    from .taxonomy import CTFChallengeTag, CTFTopic

logger = logging.getLogger(__name__)


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
        "CTFEvent",
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
    target_instance_name = models.CharField(
        max_length=100,
        blank=True,
        default="",
        help_text="Instance name for connection info (e.g. 'windows-target')",
    )
    target_port = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Target port for this challenge (e.g. 80, 3389)",
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
        """Django model metadata."""

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
        self._validate_release_time(errors)
        self._validate_next_challenge(errors)
        if errors:
            raise ValidationError(errors)

    def _validate_release_time(self, errors: dict[str, list[str]]) -> None:
        if not (self.release_time and hasattr(self, "event") and self.event_id):
            return
        if self.release_time < self.event.event_start:
            errors.setdefault("release_time", []).append("Release time cannot be before event start.")
        if self.release_time > self.event.event_end:
            errors.setdefault("release_time", []).append("Release time cannot be after event end.")

    def _validate_next_challenge(self, errors: dict[str, list[str]]) -> None:
        if not self.next_challenge_id:
            return
        if self.pk and self.next_challenge_id == self.pk:
            errors.setdefault("next_challenge", []).append("A challenge cannot be its own next challenge.")
        nc = self.next_challenge
        if self.event_id and nc is not None and nc.event_id != self.event_id:
            errors.setdefault("next_challenge", []).append("Next challenge must belong to the same event.")

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
            Points to award. A 100% (or above) cumulative penalty floors at 0
            per CTF-203 ("the net score for a challenge solve shall never go
            below zero"). The historical 1-point floor was the bug fixed by
            issue #519.
        """
        if total_hint_penalty > 0:
            capped = min(total_hint_penalty, 100)
            reduction = (self.points * capped) // 100
            return max(0, self.points - reduction)
        return self.points
