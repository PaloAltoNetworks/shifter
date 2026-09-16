"""Spare-pool capacity declaration ordering (PLAT-201, #680).

``provision_event_spares`` declared capacity *before* persisting the new spare
target, so the declaration -- and any capacity assessment reading it -- saw the
previous pool size. Growing a pool from 0 to 20 therefore declared the old
number and understated peak concurrent ranges by exactly the growth.
"""

from __future__ import annotations

import pytest

from engine.models import CapacityDeclaration

pytestmark = pytest.mark.django_db


class TestSpareDeclarationOrdering:
    def test_declaration_reflects_the_new_spare_target(self, ctf_event):
        from ctf.services.range.spares import provision_event_spares

        ctf_event.spare_range_count = 0
        ctf_event.save(update_fields=["spare_range_count", "updated_at"])

        provision_event_spares(ctf_event.pk, 7)

        declaration = CapacityDeclaration.objects.filter(event_ref=ctf_event.pk).order_by("-declared_at").first()
        assert declaration is not None
        # cohort (0 participants) + the newly declared spare target.
        assert declaration.expected_concurrent_ranges == 7

    def test_shrinking_the_pool_also_declares_the_new_target(self, ctf_event):
        from ctf.services.range.spares import provision_event_spares

        ctf_event.spare_range_count = 12
        ctf_event.save(update_fields=["spare_range_count", "updated_at"])

        provision_event_spares(ctf_event.pk, 3)

        declaration = CapacityDeclaration.objects.filter(event_ref=ctf_event.pk).order_by("-declared_at").first()
        assert declaration is not None
        assert declaration.expected_concurrent_ranges == 3


class TestImageProjectionReachesTheEngine:
    """Per-AMI pre-bake counts derive from the scenario, end to end."""

    def test_declaration_carries_the_scenario_image_shape(self, ctf_event):
        from ctf.services.range.capacity import build_event_capacity_signal

        signal = build_event_capacity_signal(ctf_event)

        images = signal["resource_hints"]["images"]
        assert set(images) == {"resolved", "per_range", "shared"}

    def test_engine_scales_per_range_images_by_concurrency(self, ctf_event, monkeypatch):
        """Twenty ranges each needing one kali is twenty kali images to pre-bake."""
        from engine.services._capacity_plan import _demand_from_declaration
        from shared.capacity.catalog import load_catalog

        class _Declaration:
            expected_concurrent_ranges = 20
            resource_hints = {
                "agents_by_os": {"windows": 1},
                "images": {
                    "resolved": True,
                    "per_range": [
                        {"source_name": "kali", "source_version": "", "os_family": "kali", "count": 1},
                    ],
                    "shared": [
                        {"source_name": "scoreboard", "source_version": "", "os_family": "ubuntu", "count": 1},
                    ],
                },
            }

        catalog = load_catalog(
            {
                "partitions": [
                    {
                        "name": "p",
                        "provider": "aws",
                        "account": "111122223333",
                        "region": "us-east-2",
                        "backend": "ecs",
                    }
                ],
                "metrics": [],
            }
        )

        demand = _demand_from_declaration(_Declaration(), catalog, "p")

        counts = {image.source_name: image.count for image in demand.image_counts}
        assert counts == {"kali": 20, "scoreboard": 1}

    def test_malformed_image_hint_entries_are_dropped(self, ctf_event):
        """The hint travels through a JSONField, so entries are shape-checked."""
        from engine.services._capacity_plan import _demand_from_declaration
        from shared.capacity.catalog import load_catalog

        class _Declaration:
            expected_concurrent_ranges = 5
            resource_hints = {
                "images": {
                    "per_range": [
                        {"source_name": "kali", "count": 1},
                        {"source_name": "bad", "count": -3},
                        {"source_name": "worse", "count": "many"},
                        "not-a-dict",
                    ]
                }
            }

        catalog = load_catalog({"partitions": [], "metrics": []})

        demand = _demand_from_declaration(_Declaration(), catalog, "p")

        assert {image.source_name for image in demand.image_counts} == {"kali"}
