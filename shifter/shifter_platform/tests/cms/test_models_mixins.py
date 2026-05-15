"""Tests for the cms.models.mixins property mixins.

The mixins are field-free — they read attributes the consumer model
declares. These tests exercise them against minimal stand-ins so the
property semantics are pinned independently of any concrete model.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from shared.db import ExpiringStateMixin, SoftDeleteMixin


class _SoftDeleteSubject(SoftDeleteMixin):
    """Minimal subject class that only carries ``deleted_at``."""

    def __init__(self, deleted_at=None):
        self.deleted_at = deleted_at


class _ExpiringSubject(ExpiringStateMixin):
    """Minimal subject class that only carries ``expires_at``."""

    def __init__(self, expires_at=None):
        self.expires_at = expires_at


@pytest.mark.parametrize(
    ("deleted_at", "expected"),
    [
        pytest.param(None, False, id="active"),
        pytest.param(timezone.now(), True, id="deleted"),
    ],
)
def test_soft_delete_mixin_is_deleted(deleted_at, expected):
    assert _SoftDeleteSubject(deleted_at=deleted_at).is_deleted is expected


@pytest.mark.parametrize(
    ("expires_at", "expected"),
    [
        pytest.param(None, False, id="no_expiry"),
        pytest.param(timezone.now() - timedelta(days=1), True, id="past"),
        pytest.param(timezone.now() + timedelta(days=1), False, id="future"),
    ],
)
def test_expiring_state_mixin_is_expired(expires_at, expected):
    assert _ExpiringSubject(expires_at=expires_at).is_expired is expected


@pytest.mark.parametrize(
    ("offset_days", "expected"),
    [
        pytest.param(None, False, id="no_expiry"),
        pytest.param(-1, False, id="already_expired"),
        pytest.param(15, True, id="within_30_days"),
        pytest.param(31, False, id="far_future"),
    ],
)
def test_expiring_state_mixin_expires_soon(offset_days, expected):
    expires_at = timezone.now() + timedelta(days=offset_days) if offset_days is not None else None
    assert _ExpiringSubject(expires_at=expires_at).expires_soon is expected
