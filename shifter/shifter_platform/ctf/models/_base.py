"""Base manager + abstract CTFBaseModel.

Split from monolithic ctf/models.py (PR #856) to satisfy python:S104
(file too large). Public symbols are re-exported by ctf/models/__init__.py
so ``from ctf.models import X`` keeps working unchanged.
"""

from __future__ import annotations

import logging
from typing import TypeVar
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import QuerySet
from django.utils import timezone

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
    # DJ012 (manager declared after fields would normally fire) is intentionally
    # suppressed: `all_objects` is the bypass-soft-delete escape hatch and must
    # be declared next to the active-objects manager for discoverability, not
    # buried at the top of the class.
    all_objects = models.Manager()  # noqa: DJ012

    class Meta:
        """Django model metadata."""

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
