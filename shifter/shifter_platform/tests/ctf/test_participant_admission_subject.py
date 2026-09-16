"""Authoritative participant membership subject for model admission (PLAT-202, #2119).

A replacement launch must resolve the realized range reference (matching the
published #2139/#2140 membership) rather than always the draw reference, so a
range-scoped sharing restriction cannot be bypassed by rebuild/reprovision.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from django.utils import timezone

from ctf.models import CTFParticipant
from ctf.services.model_access_sharing import ModelAccessSelectorError, participant_model_admission_subject
from shared.model_access import OwnedReference

pytestmark = pytest.mark.django_db


def _participant(event, *, range_instance_id=None):
    return CTFParticipant.objects.create(
        event=event,
        email="p@test.com",
        name="p",
        status="active",
        registered_at=timezone.now(),
        range_instance_id=range_instance_id,
    )


def test_participant_without_range_uses_draw_reference(ctf_event):
    participant = _participant(ctf_event)
    subject = participant_model_admission_subject(participant)
    assert subject == OwnedReference(owner="ctf", reference=f"draw:{participant.pk}")


def test_participant_with_realized_range_uses_range_reference(ctf_event, monkeypatch):
    participant = _participant(ctf_event, range_instance_id=42)
    range_ref = OwnedReference(owner="cms", reference="range:abc")
    monkeypatch.setattr(
        "ctf.bridges.cms_resolve_model_access_range_instances",
        lambda ids: (SimpleNamespace(range_ref=range_ref),) if ids == (42,) else (),
    )

    assert participant_model_admission_subject(participant) == range_ref


def test_unresolvable_realized_range_fails_closed(ctf_event, monkeypatch):
    # A realized range that cannot be resolved fails closed (raises) rather than
    # substituting the draw identity, which would drop a published range-scoped
    # restriction. The recovery flow captures this subject before teardown, so an
    # active range resolves normally.
    participant = _participant(ctf_event, range_instance_id=42)
    monkeypatch.setattr("ctf.bridges.cms_resolve_model_access_range_instances", lambda _ids: ())

    with pytest.raises(ModelAccessSelectorError):
        participant_model_admission_subject(participant)
