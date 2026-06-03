"""Challenge taxonomy — topics, tags, files, prerequisites.

Split from monolithic ctf/models.py (PR #856) to satisfy python:S104
(file too large). Public symbols are re-exported by ctf/models/__init__.py
so ``from ctf.models import X`` keeps working unchanged.
"""

from __future__ import annotations

import logging

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from ._base import CTFBaseModel

logger = logging.getLogger(__name__)


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
        """Django model metadata."""

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
        "CTFEvent",
        on_delete=models.CASCADE,
        related_name="tags",
        help_text="Event this tag belongs to",
    )
    name = models.CharField(
        max_length=50,
        help_text="Tag label (e.g. XDR, Linux, Windows)",
    )

    class Meta:
        """Django model metadata."""

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
        """Django model metadata."""

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
        """Django model metadata."""

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
