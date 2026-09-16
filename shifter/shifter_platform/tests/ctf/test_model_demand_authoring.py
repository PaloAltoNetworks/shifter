"""Organizer authoring boundary for typed model demand (PLAT-202, #2119).

The CTF-908 model demand must be settable and validated through the event write
surfaces, not only via a direct model save.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from ctf.api.serializers.organizer import EventWriteSerializer
from ctf.services.event import create_event
from ctf.services.range.capacity import parse_event_model_demand

pytestmark = pytest.mark.django_db


def _demand() -> dict:
    return {
        "workload_role": "participant",
        "expected_concurrency": 4,
        "per_participant_requests": 100,
        "per_participant_input_tokens": 4_000,
        "per_participant_output_tokens": 1_000,
        "allowed_strategy": "fixed-v1",
    }


def _event_body(**overrides) -> dict:
    now = timezone.now()
    body = {
        "name": "Model Demand Event",
        "event_start": now + timedelta(days=1),
        "event_end": now + timedelta(days=2),
    }
    body.update(overrides)
    return body


def test_write_serializer_accepts_valid_model_demand():
    serializer = EventWriteSerializer(data=_event_body(model_demand=[_demand()]))
    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data["model_demand"] == [_demand()]


def test_write_serializer_rejects_malformed_model_demand():
    bad = {"workload_role": "participant", "expected_concurrency": 0}
    serializer = EventWriteSerializer(data=_event_body(model_demand=[bad]))
    assert not serializer.is_valid()
    assert "model_demand" in serializer.errors


def test_create_event_persists_model_demand(django_user_model):
    user = django_user_model.objects.create_user(username="organizer", email="o@test.com")
    event = create_event(user, _event_body(model_demand=[_demand()]))

    event.refresh_from_db()
    parsed = parse_event_model_demand(event)
    assert len(parsed) == 1
    assert parsed[0].workload_role == "participant"
