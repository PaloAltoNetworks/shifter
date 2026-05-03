"""Lightweight property mixins shared across CMS models.

These are field-free mixins — each declares properties that read a field
the consumer model defines (``deleted_at`` for :class:`SoftDeleteMixin`,
``expires_at`` for :class:`ExpiringStateMixin`). The consumer model must
declare the field; the mixin only supplies the convenience properties so
the same logic isn't re-implemented across every model that needs it.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from django.utils import timezone


class SoftDeleteMixin:
    """``is_deleted`` accessor for models with a nullable ``deleted_at`` field."""

    # The consumer model declares ``deleted_at`` as a Django field; the mixin
    # only reads it, so annotate with Any to tell mypy the attribute exists.
    deleted_at: Any

    @property
    def is_deleted(self) -> bool:
        """Return True if this row has been soft-deleted."""
        return self.deleted_at is not None


class ExpiringStateMixin:
    """``is_expired`` / ``expires_soon`` accessors for models with a nullable ``expires_at`` field."""

    # Provided by the consumer model as a nullable DateTimeField.
    expires_at: datetime | None

    @property
    def is_expired(self) -> bool:
        """Return True if this entity's ``expires_at`` is in the past."""
        if not self.expires_at:
            return False
        return timezone.now() > self.expires_at

    @property
    def expires_soon(self) -> bool:
        """Return True if ``expires_at`` is within 30 days and not yet past."""
        if not self.expires_at:
            return False
        if self.is_expired:
            return False
        return self.expires_at <= timezone.now() + timedelta(days=30)
