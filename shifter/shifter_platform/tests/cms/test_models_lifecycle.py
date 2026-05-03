"""Tests for the cms.models.lifecycle helpers.

Pure-function coverage for ``apply_terminal_soft_delete`` so the invariant
can be tested without standing up Django models. The integration-style
tests for ``EntityBase.save()`` and ``RangeInstance.save()`` already
exercise the helper through the model layer.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from django.utils import timezone

from cms.models.lifecycle import apply_terminal_soft_delete
from shared.enums import TERMINAL_STATUSES, ResourceStatus

# Deterministic representative of the terminal-status set so xdist workers
# all collect the same parametrize id; sets don't guarantee iteration order.
_FIRST_TERMINAL = sorted(s.value for s in TERMINAL_STATUSES)[0]


def _instance(status: str, deleted_at=None):
    """Lightweight stand-in that has the two attributes the helper reads."""
    return SimpleNamespace(status=status, deleted_at=deleted_at)


@pytest.mark.parametrize("terminal", sorted(s.value for s in TERMINAL_STATUSES))
def test_terminal_status_sets_deleted_at(terminal):
    """Every value in TERMINAL_STATUSES triggers the soft-delete."""
    instance = _instance(status=terminal)
    kwargs: dict = {}

    applied = apply_terminal_soft_delete(instance, kwargs)

    assert applied is True
    assert instance.deleted_at is not None
    assert "update_fields" not in kwargs  # nothing to patch when not provided


def test_non_terminal_status_does_nothing():
    """Active / pending statuses leave deleted_at alone."""
    instance = _instance(status=ResourceStatus.PENDING.value)
    kwargs: dict = {}

    applied = apply_terminal_soft_delete(instance, kwargs)

    assert applied is False
    assert instance.deleted_at is None


def test_unrecognised_status_does_not_raise():
    """Status strings outside the enum are ignored, never raised."""
    instance = _instance(status="some-future-status-not-in-enum")
    kwargs: dict = {}

    applied = apply_terminal_soft_delete(instance, kwargs)

    assert applied is False
    assert instance.deleted_at is None


def test_already_deleted_is_not_overwritten():
    """If deleted_at is already set, the helper does not touch it."""
    fixed = timezone.now()
    instance = _instance(status=_FIRST_TERMINAL, deleted_at=fixed)
    kwargs: dict = {}

    applied = apply_terminal_soft_delete(instance, kwargs)

    assert applied is False
    assert instance.deleted_at == fixed


def test_update_fields_is_patched_when_specified():
    """If callers pass update_fields, deleted_at is appended so it persists."""
    instance = _instance(status=_FIRST_TERMINAL)
    kwargs: dict = {"update_fields": ["status"]}

    applied = apply_terminal_soft_delete(instance, kwargs)

    assert applied is True
    assert "deleted_at" in kwargs["update_fields"]
    assert "status" in kwargs["update_fields"]


def test_update_fields_unchanged_when_already_present():
    """If update_fields already contains deleted_at, it is not duplicated."""
    instance = _instance(status=_FIRST_TERMINAL)
    kwargs: dict = {"update_fields": ["status", "deleted_at"]}

    applied = apply_terminal_soft_delete(instance, kwargs)

    assert applied is True
    assert kwargs["update_fields"].count("deleted_at") == 1
