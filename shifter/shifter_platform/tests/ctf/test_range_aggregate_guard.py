"""Tests for the CTF domain-owned range aggregate guard (PLAT-237, #1944).

The guard authoritatively identifies which ranges belong to a CTF event so the
Mission Control workspace-scope admin refuses to move them, keyed on CTF's own
rows rather than a provenance label.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from ctf.enums import SpareRangeStatus
from ctf.models import CTFSpareRange
from ctf.services.range.aggregate import ctf_range_aggregate_guard

pytestmark = pytest.mark.django_db


class TestCtfRangeAggregateGuard:
    def test_participant_live_range_is_bound(self, ctf_participant):
        ctf_participant.range_instance_id = 4242
        ctf_participant.save(update_fields=["range_instance_id"])

        bound = ctf_range_aggregate_guard([(uuid4(), 4242), (uuid4(), 9999)])

        assert bound == {4242}

    def test_spare_range_is_bound_by_range_id(self, ctf_event):
        CTFSpareRange.objects.create(event=ctf_event, range_instance_id=555, status=SpareRangeStatus.READY.value)

        bound = ctf_range_aggregate_guard([(uuid4(), 555)])

        assert bound == {555}

    def test_spare_range_is_bound_by_request_id(self, ctf_event):
        request_id = uuid4()
        CTFSpareRange.objects.create(
            event=ctf_event, request_id=request_id, range_instance_id=None, status=SpareRangeStatus.PROVISIONING.value
        )

        # The spare has no resolved range id yet; the guard maps the matching
        # request id back to the caller's range instance id.
        bound = ctf_range_aggregate_guard([(request_id, 777)])

        assert bound == {777}

    def test_unreferenced_range_is_not_bound(self, ctf_event):
        bound = ctf_range_aggregate_guard([(uuid4(), 12345)])

        assert bound == set()
