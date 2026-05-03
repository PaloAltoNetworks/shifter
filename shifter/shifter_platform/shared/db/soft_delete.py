"""Soft-delete primitives shared across apps.

Centralises the ``deleted_at`` pattern so every consumer model gets the
same ``is_deleted`` accessor, the same active-only default queryset, and
the same expiry semantics. Re-implementing these locally is the failure
mode that produces the "forgot to filter out soft-deleted rows" bug class
— leaking soft-deleted records back into queries that should never see
them.

The defining design choice is that **the default manager pre-filters to
non-soft-deleted rows.** ``Model.objects`` only ever returns active rows,
so a call site cannot accidentally leak deleted records by writing the
plain ``Model.objects.filter(...)`` they would write for any other
model. Code that genuinely needs to read deleted rows (admin recovery
flows, audit jobs, restore actions) must reach for the explicit
``Model.all_objects`` manager — which makes the intent obvious to
reviewers and to grep.

A soft-delete-aware model:

1. Declares ``deleted_at = models.DateTimeField(null=True, blank=True)``.
2. Inherits :class:`SoftDeleteMixin` (or, transitively, ``Asset`` / etc).
3. Sets the canonical pair of managers::

       objects = SoftDeleteManager()                  # default — active rows only
       all_objects = SoftDeleteQuerySet.as_manager()  # explicit — full table

   Callers can still chain ``.active()`` or ``.deleted()`` on either
   manager when explicit intent improves readability.
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
    """Queryset helpers for models with a nullable ``deleted_at`` field.

    Provides ``active()`` / ``deleted()`` / ``with_deleted()`` so call
    sites that need to be explicit about soft-delete state have one
    canonical vocabulary across the codebase.

    Most code does not need to call these directly — the default
    ``objects`` manager (built via :class:`SoftDeleteManager`) already
    pre-filters to active rows. Use these chainable helpers when you
    start from a queryset that includes deleted rows (e.g. via
    ``all_objects``) and want to narrow it.
    """

    def active(self) -> SoftDeleteQuerySet:
        """Return only rows that have not been soft-deleted."""
        return self.filter(deleted_at__isnull=True)

    def deleted(self) -> SoftDeleteQuerySet:
        """Return only rows that have been soft-deleted."""
        return self.filter(deleted_at__isnull=False)


class SoftDeleteManager(models.Manager.from_queryset(SoftDeleteQuerySet)):  # type: ignore[misc]
    """Default manager for soft-delete-aware models.

    Pre-filters every queryset to non-deleted rows. This is the manager
    that closes the soft-delete bypass bug class: a normal
    ``Model.objects.filter(...)`` cannot return a deleted row because
    the manager never returns one to begin with.

    Pair every model that uses this manager with an
    ``all_objects = models.Manager()`` declaration so admin / restore /
    audit code can still reach the full table when it needs to.
    """

    def get_queryset(self) -> SoftDeleteQuerySet:
        return super().get_queryset().filter(deleted_at__isnull=True)
