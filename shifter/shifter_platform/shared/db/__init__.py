"""Shared cross-cutting model primitives.

Hosts model-layer helpers that apply across apps (CMS, CTF, risk register,
engine, mission control). Apps import from here rather than re-implementing
the same patterns locally.

Currently exposes:

* :class:`SoftDeleteMixin`     — ``is_deleted`` property for any model with
                                 a nullable ``deleted_at`` field.
* :class:`ExpiringStateMixin`  — ``is_expired`` / ``expires_soon`` properties
                                 for any model with a nullable ``expires_at`` field.
* :class:`SoftDeleteQuerySet`  — ``active()`` / ``deleted()`` query helpers,
                                 the canonical way to filter soft-delete state.
"""

from shared.db.soft_delete import (
    ExpiringStateMixin,
    SoftDeleteMixin,
    SoftDeleteQuerySet,
)

__all__ = [
    "ExpiringStateMixin",
    "SoftDeleteMixin",
    "SoftDeleteQuerySet",
]
