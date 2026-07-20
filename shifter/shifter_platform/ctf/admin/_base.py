"""Shared admin mixin for CTF admin classes."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from django.db import models as _models
    from django.db.models import QuerySet
    from django.http import HttpRequest


class SoftDeleteAdminMixin:
    """Mixin for handling soft-deleted records in admin."""

    model: type[_models.Model]

    def get_queryset(self, request: HttpRequest) -> QuerySet:  # NOSONAR - Django override requires request param
        """Include soft-deleted records in admin queryset."""
        return self.model.all_objects.all()  # type: ignore[attr-defined]
