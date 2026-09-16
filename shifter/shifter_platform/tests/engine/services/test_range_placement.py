"""Multi-region range-cell placement selection (#2029).

The pure pool parser/selector used at range creation to pick each range's zone
from ``RANGE_NETWORK_ZONES``. The realized zone is stored on the range and the
provisioner reads it back (never recomputes), so this selection runs exactly once
per range. Read-back binding is tested provisioner-side in
``engine/provisioner/tests/test_range_cell_zone_pool.py``.
"""

from __future__ import annotations

from collections import Counter

import pytest

from engine.services._range_placement import range_zone_pool, select_placement_zone


class TestRangeZonePool:
    def test_empty_when_unset(self, monkeypatch):
        monkeypatch.delenv("RANGE_NETWORK_ZONES", raising=False)
        assert range_zone_pool() == ()

    def test_parses_trims_and_preserves_order(self, monkeypatch):
        monkeypatch.setenv("RANGE_NETWORK_ZONES", " us-east4-a , us-central1-a ,, us-east1-b ")
        # Order is significant (placement is slot % len); it must not be sorted.
        assert range_zone_pool() == ("us-east4-a", "us-central1-a", "us-east1-b")

    def test_rejects_a_malformed_zone(self, monkeypatch):
        monkeypatch.setenv("RANGE_NETWORK_ZONES", "us-central1-a,us-central1")
        with pytest.raises(RuntimeError, match=r"entry 1 .*not a fully-qualified GCE zone"):
            range_zone_pool()

    def test_rejects_a_duplicate_zone(self, monkeypatch):
        monkeypatch.setenv("RANGE_NETWORK_ZONES", "us-central1-a,us-east4-a,us-central1-a")
        with pytest.raises(RuntimeError, match=r"entry 2 .*duplicate"):
            range_zone_pool()


class TestSelectPlacementZone:
    def test_no_pool_selects_nothing(self, monkeypatch):
        monkeypatch.delenv("RANGE_NETWORK_ZONES", raising=False)
        assert select_placement_zone(7) == ""

    def test_no_slot_selects_nothing(self, monkeypatch):
        monkeypatch.setenv("RANGE_NETWORK_ZONES", "us-central1-a,us-east4-a")
        assert select_placement_zone(None) == ""

    def test_slot_selects_the_pooled_zone(self, monkeypatch):
        monkeypatch.setenv("RANGE_NETWORK_ZONES", "us-central1-a,us-east4-a,us-east1-b")
        assert [select_placement_zone(s) for s in range(4)] == [
            "us-central1-a",
            "us-east4-a",
            "us-east1-b",
            "us-central1-a",
        ]

    def test_spreads_a_fleet_evenly_across_the_pool(self, monkeypatch):
        """300 ranges over 3 zones is 100 each -- the property the quota split relies on."""
        monkeypatch.setenv("RANGE_NETWORK_ZONES", "us-central1-a,us-east4-a,us-east1-b")
        spread = Counter(select_placement_zone(s) for s in range(300))
        assert spread == {"us-central1-a": 100, "us-east4-a": 100, "us-east1-b": 100}
