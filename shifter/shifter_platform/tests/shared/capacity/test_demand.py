"""Demand derivation from declared event intent (PLAT-201, #680).

Turns "this event expects N concurrent ranges of this shape" into per-metric
amounts and per-image counts. Pure arithmetic, kept stdlib-only so the
provisioner can import it: the RAES/legacy plan projection that feeds it lives
in the Engine, not here.
"""

from __future__ import annotations

import pytest

from shared.capacity import ImageCount
from shared.capacity.demand import build_demand


class TestMetricAmounts:
    def test_per_range_cost_scales_with_concurrent_ranges(self):
        demand = build_demand(
            partition_name="aws-dev-use2",
            expected_concurrent_ranges=25,
            nodes_per_range=0,
            per_range_costs={"ec2_vcpu": 4.0},
            per_node_costs={},
        )

        assert demand.amounts["ec2_vcpu"] == pytest.approx(100.0)

    def test_per_node_cost_scales_with_total_nodes(self):
        """Ten ranges of three nodes is thirty nodes, not three."""
        demand = build_demand(
            partition_name="aws-dev-use2",
            expected_concurrent_ranges=10,
            nodes_per_range=3,
            per_range_costs={},
            per_node_costs={"ec2_vcpu": 2.0},
        )

        assert demand.amounts["ec2_vcpu"] == pytest.approx(60.0)

    def test_range_and_node_costs_combine(self):
        demand = build_demand(
            partition_name="aws-dev-use2",
            expected_concurrent_ranges=10,
            nodes_per_range=2,
            per_range_costs={"ec2_vcpu": 1.0},
            per_node_costs={"ec2_vcpu": 2.0},
        )

        assert demand.amounts["ec2_vcpu"] == pytest.approx(10.0 + 40.0)

    def test_metrics_without_declared_cost_are_absent(self):
        """A metric nobody costed is not demanded -- not silently demanded at zero."""
        demand = build_demand(
            partition_name="aws-dev-use2",
            expected_concurrent_ranges=10,
            nodes_per_range=1,
            per_range_costs={"ec2_vcpu": 1.0},
            per_node_costs={},
        )

        assert "bedrock_tpm" not in demand.amounts

    def test_zero_concurrent_ranges_demands_nothing(self):
        demand = build_demand(
            partition_name="aws-dev-use2",
            expected_concurrent_ranges=0,
            nodes_per_range=4,
            per_range_costs={"ec2_vcpu": 4.0},
            per_node_costs={"ec2_vcpu": 2.0},
        )

        assert demand.amounts["ec2_vcpu"] == pytest.approx(0.0)

    def test_negative_inputs_are_rejected(self):
        with pytest.raises(ValueError):
            build_demand(
                partition_name="aws-dev-use2",
                expected_concurrent_ranges=-1,
                nodes_per_range=1,
                per_range_costs={},
                per_node_costs={},
            )


class TestImageCounts:
    """Per-AMI pre-bake counts: image identity times concurrent ranges."""

    def test_image_counts_scale_by_concurrent_ranges(self):
        demand = build_demand(
            partition_name="aws-dev-use2",
            expected_concurrent_ranges=50,
            nodes_per_range=2,
            per_range_costs={},
            per_node_costs={},
            images_per_range=(
                ImageCount(source_name="kali", source_version="2026.1", os_family="linux", count=1),
                ImageCount(source_name="win-dc", source_version="2022", os_family="windows", count=1),
            ),
        )

        counts = {image.source_name: image.count for image in demand.image_counts}
        assert counts == {"kali": 50, "win-dc": 50}

    def test_multiple_instances_of_one_image_multiply(self):
        demand = build_demand(
            partition_name="aws-dev-use2",
            expected_concurrent_ranges=10,
            nodes_per_range=3,
            per_range_costs={},
            per_node_costs={},
            images_per_range=(ImageCount(source_name="kali", source_version="", os_family="linux", count=3),),
        )

        assert demand.image_counts[0].count == 30

    def test_image_identity_is_preserved(self):
        demand = build_demand(
            partition_name="aws-dev-use2",
            expected_concurrent_ranges=2,
            nodes_per_range=1,
            per_range_costs={},
            per_node_costs={},
            images_per_range=(ImageCount(source_name="kali", source_version="2026.1", os_family="linux", count=1),),
        )

        image = demand.image_counts[0]
        assert (image.source_name, image.source_version, image.os_family) == ("kali", "2026.1", "linux")

    def test_no_images_is_empty_not_an_error(self):
        demand = build_demand(
            partition_name="aws-dev-use2",
            expected_concurrent_ranges=5,
            nodes_per_range=0,
            per_range_costs={},
            per_node_costs={},
        )

        assert demand.image_counts == ()


class TestSharedImages:
    """Event-shared images are realized once, not once per range."""

    def test_shared_images_are_not_scaled(self):
        demand = build_demand(
            partition_name="aws-dev-use2",
            expected_concurrent_ranges=100,
            nodes_per_range=1,
            per_range_costs={},
            per_node_costs={},
            images_per_range=(ImageCount(source_name="kali", source_version="", os_family="kali", count=1),),
            shared_images=(ImageCount(source_name="scoreboard", source_version="", os_family="ubuntu", count=1),),
        )

        counts = {image.source_name: image.count for image in demand.image_counts}
        assert counts == {"kali": 100, "scoreboard": 1}

    def test_shared_and_per_range_of_the_same_image_combine(self):
        """One shared instance plus one per participant across 10 ranges is 11."""
        demand = build_demand(
            partition_name="aws-dev-use2",
            expected_concurrent_ranges=10,
            nodes_per_range=1,
            per_range_costs={},
            per_node_costs={},
            images_per_range=(ImageCount(source_name="kali", source_version="", os_family="kali", count=1),),
            shared_images=(ImageCount(source_name="kali", source_version="", os_family="kali", count=1),),
        )

        assert len(demand.image_counts) == 1
        assert demand.image_counts[0].count == 11
