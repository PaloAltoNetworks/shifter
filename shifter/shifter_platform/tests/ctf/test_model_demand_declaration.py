"""Typed organizer model demand in the CTF-908 declaration (PLAT-202, #2119)."""

from __future__ import annotations

import pytest

from ctf.services.range.capacity import build_event_capacity_signal, parse_event_model_demand
from shared.model_access import AllocationStrategy
from shared.model_access.admission import EventModelDemand

pytestmark = pytest.mark.django_db


def _demand(workload="participant", strategy="fixed-v1") -> dict:
    return {
        "workload_role": workload,
        "expected_concurrency": 4,
        "per_participant_requests": 100,
        "per_participant_input_tokens": 4_000,
        "per_participant_output_tokens": 1_000,
        "allowed_strategy": strategy,
    }


def test_parse_returns_typed_demand_and_drops_malformed(ctf_event):
    ctf_event.model_demand = [_demand(), {"workload_role": "spare", "expected_concurrency": 0}]
    ctf_event.save(update_fields=["model_demand", "updated_at"])

    parsed = parse_event_model_demand(ctf_event)

    assert len(parsed) == 1
    assert isinstance(parsed[0], EventModelDemand)
    assert parsed[0].workload_role == "participant"
    assert parsed[0].allowed_strategy is AllocationStrategy.FIXED_V1


def test_valid_demand_is_carried_in_the_declaration(ctf_event):
    ctf_event.model_demand = [_demand()]
    ctf_event.save(update_fields=["model_demand", "updated_at"])

    signal = build_event_capacity_signal(ctf_event)

    carried = signal["resource_hints"]["model_demand"]
    assert len(carried) == 1
    assert carried[0]["workload_role"] == "participant"


def test_absent_demand_leaves_declaration_without_the_key(ctf_event):
    signal = build_event_capacity_signal(ctf_event)
    assert "model_demand" not in signal["resource_hints"]
