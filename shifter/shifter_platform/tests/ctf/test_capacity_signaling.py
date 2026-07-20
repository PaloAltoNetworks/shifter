"""CTF→engine event-capacity declaration flow (CTF-908, #621)."""

from __future__ import annotations

import pytest
from django.utils import timezone

from ctf.models import CTFParticipant
from ctf.services.range.capacity import build_event_capacity_signal, declare_event_capacity
from engine.models import CapacityDeclaration
from engine.services import EventCapacitySignal, record_capacity_declaration

pytestmark = pytest.mark.django_db


def _register(event, name):
    return CTFParticipant.objects.create(
        event=event,
        email=f"{name}@test.com",
        name=name,
        status="active",
        registered_at=timezone.now(),
    )


class TestSignalBuild:
    def test_counts_and_hints(self, ctf_event):
        _register(ctf_event, "one")
        _register(ctf_event, "two")
        ctf_event.spare_range_count = 3
        ctf_event.range_config = {"agents_by_os": {"windows": 1}, "ngfw_enabled": True}
        ctf_event.capacity_hints = {"llm_provider_class": "bedrock-claude", "per_participant_rpm": 6}
        ctf_event.save(update_fields=["spare_range_count", "range_config", "capacity_hints", "updated_at"])

        signal = build_event_capacity_signal(ctf_event)

        assert signal["cohort_size"] == 2
        assert signal["expected_concurrent_ranges"] == 5
        assert signal["resource_hints"]["ngfw_enabled"] is True
        assert signal["resource_hints"]["agents_by_os"] == {"windows": 1}
        assert signal["resource_hints"]["organizer"]["llm_provider_class"] == "bedrock-claude"
        assert signal["window_start"] < signal["window_end"]


class TestDeclarationRecording:
    def test_end_to_end_declaration(self, ctf_event):
        _register(ctf_event, "solo")
        assert declare_event_capacity(ctf_event.pk, source="test") is True

        row = CapacityDeclaration.objects.get(event_ref=ctf_event.pk)
        assert row.cohort_size == 1
        assert row.event_name == ctf_event.name
        assert row.source == "ctf"

    def test_identical_redeclaration_is_idempotent(self, ctf_event):
        _register(ctf_event, "solo")
        declare_event_capacity(ctf_event.pk, source="test")
        declare_event_capacity(ctf_event.pk, source="test")
        assert CapacityDeclaration.objects.filter(event_ref=ctf_event.pk).count() == 1

        _register(ctf_event, "another")
        declare_event_capacity(ctf_event.pk, source="test")
        assert CapacityDeclaration.objects.filter(event_ref=ctf_event.pk).count() == 2

    def test_declaration_failure_never_raises(self, ctf_event, monkeypatch):
        def boom(**_kwargs):
            raise RuntimeError("engine down")

        monkeypatch.setattr("ctf.bridges.cms_declare_event_capacity", boom)
        assert declare_event_capacity(ctf_event.pk, source="test") is False

    def test_engine_record_content_dedupe(self, ctf_event):
        signal = EventCapacitySignal(
            event_ref=ctf_event.pk,
            expected_concurrent_ranges=10,
            cohort_size=8,
            event_name="X",
        )
        first = record_capacity_declaration(signal)
        second = record_capacity_declaration(signal)
        assert first.pk == second.pk


class TestProvisioningDeclares:
    def test_throttled_batch_declares_before_spinup(self, ctf_event_active):
        from ctf.services.range.batch import provision_event_ranges_throttled

        # No eligible participants: the loop is a no-op, but the declaration
        # must still be recorded before spinup would have begun.
        provision_event_ranges_throttled(ctf_event_active.pk, 60)
        assert CapacityDeclaration.objects.filter(event_ref=ctf_event_active.pk).exists()
