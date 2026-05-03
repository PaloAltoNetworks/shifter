"""Soft-delete primitives shared across apps.

Centralises the ``deleted_at`` pattern so every consumer model gets the
same ``is_deleted`` accessor, the same ``active()`` / ``deleted()`` query
filters, and the same expiry semantics. Re-implementing these locally is
the failure mode that produces the "forgot to filter out soft-deleted
rows" bug class — leaking soft-deleted records back into queries that
should never see them.

A soft-delete-aware model:

1. Declares ``deleted_at = models.DateTimeField(null=True, blank=True)``.
2. Inherits :class:`SoftDeleteMixin` (or, transitively, ``Asset`` / etc).
3. Sets ``objects = SoftDeleteQuerySet.as_manager()`` so callers can
   write ``Model.objects.active()`` / ``Model.objects.deleted()`` instead
   of re-typing ``deleted_at__isnull=True`` filters.

Models with both managers — e.g. a default manager that returns all rows
and a separate ``active`` manager that pre-filters — should build the
``active`` manager from this queryset via
``models.Manager.from_queryset(SoftDeleteQuerySet)`` so the ``active()``
method is also available on its querysets.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from django.db import models
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


class SoftDeleteQuerySet(models.QuerySet):
    """Canonical queryset for models with a nullable ``deleted_at`` field.

    Use these helpers instead of inline ``deleted_at__isnull`` filters so
    every soft-delete query goes through one well-known code path. Forgetting
    the filter at a call site is the single most common way soft-deleted
    rows leak back into application queries.
    """

    def active(self) -> SoftDeleteQuerySet:
        """Return only rows that have not been soft-deleted."""
        return self.filter(deleted_at__isnull=True)

    def deleted(self) -> SoftDeleteQuerySet:
        """Return only rows that have been soft-deleted."""
        return self.filter(deleted_at__isnull=False)
