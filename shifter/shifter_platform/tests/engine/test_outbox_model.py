"""Tests for engine.models.RangeEventOutbox.

Phase 1 (#476): lightweight model-level checks for field defaults, choices,
and db_table. No DB is required — these validate ORM metadata only.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.django_db(databases=["default"])


class TestRangeEventOutboxDefaults:
    """Field-level defaults match the spec."""

    def test_status_default_is_pending(self):
        from engine.models import RangeEventOutbox

        obj = RangeEventOutbox()
        assert obj.status == "PENDING"

    def test_attempts_default_is_zero(self):
        from engine.models import RangeEventOutbox

        obj = RangeEventOutbox()
        assert obj.attempts == 0

    def test_max_attempts_default_is_ten(self):
        from engine.models import RangeEventOutbox

        obj = RangeEventOutbox()
        assert obj.max_attempts == 10

    def test_last_error_default_is_empty_string(self):
        from engine.models import RangeEventOutbox

        obj = RangeEventOutbox()
        assert obj.last_error == ""

    def test_published_at_default_is_none(self):
        from engine.models import RangeEventOutbox

        obj = RangeEventOutbox()
        assert obj.published_at is None


class TestRangeEventOutboxChoices:
    """Status field uses a TextChoices enum with the four expected values."""

    def test_choices_include_pending(self):
        from engine.models import RangeEventOutbox

        status_field = RangeEventOutbox._meta.get_field("status")
        values = [c[0] for c in status_field.choices]
        assert "PENDING" in values

    def test_choices_include_published(self):
        from engine.models import RangeEventOutbox

        status_field = RangeEventOutbox._meta.get_field("status")
        values = [c[0] for c in status_field.choices]
        assert "PUBLISHED" in values

    def test_choices_include_failed(self):
        from engine.models import RangeEventOutbox

        status_field = RangeEventOutbox._meta.get_field("status")
        values = [c[0] for c in status_field.choices]
        assert "FAILED" in values

    def test_choices_include_dlq(self):
        from engine.models import RangeEventOutbox

        status_field = RangeEventOutbox._meta.get_field("status")
        values = [c[0] for c in status_field.choices]
        assert "DLQ" in values


class TestRangeEventOutboxMeta:
    """Model Meta attributes."""

    def test_db_table_is_engine_range_event_outbox(self):
        from engine.models import RangeEventOutbox

        assert RangeEventOutbox._meta.db_table == "engine_range_event_outbox"

    def test_has_composite_index_on_status_and_next_attempt_at(self):
        from engine.models import RangeEventOutbox

        index_field_sets = [tuple(idx.fields) for idx in RangeEventOutbox._meta.indexes]
        assert ("status", "next_attempt_at") in index_field_sets
