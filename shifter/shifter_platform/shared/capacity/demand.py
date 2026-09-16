"""Demand derivation: declared event intent to per-metric and per-image amounts (PLAT-201).

An event declaration says how many concurrent ranges are expected and what shape
they have. This module turns that into the two things admission needs:

- **Per-metric amounts**, using deployment-declared cost coefficients. Shifter
  does not guess that a range costs four vCPU; the catalog says so, because the
  answer depends on instance types the deployment chose.
- **Per-image counts**, which is the pre-bake planning half of the requirement:
  image identity times the number of concurrent ranges that need it.

Deliberately stdlib-only and free of any RAES or Django import. The projection
that reads a hydrated legacy ``RangeSpec`` or an RAES ``ProvisioningPlan`` into
``ImageCount`` values lives in the Engine, so this arithmetic stays testable and
importable from the standalone provisioner.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field


@dataclass(frozen=True, order=True)
class ImageCount:
    """How many instances of one image identity a scope needs.

    Identity mirrors ``shared.raes.realizability.ImageDemand`` so the RAES
    projection maps across without inventing a second vocabulary. Only identity
    and count cross this boundary -- never authored node payloads.
    """

    source_name: str
    source_version: str
    os_family: str
    count: int


@dataclass(frozen=True)
class CapacityDemand:
    """What one event is expected to consume in one partition."""

    partition_name: str
    amounts: Mapping[str, float] = field(default_factory=dict)
    image_counts: tuple[ImageCount, ...] = ()


def build_demand(
    *,
    partition_name: str,
    expected_concurrent_ranges: int,
    nodes_per_range: int,
    per_range_costs: Mapping[str, float],
    per_node_costs: Mapping[str, float],
    images_per_range: tuple[ImageCount, ...] = (),
    shared_images: tuple[ImageCount, ...] = (),
) -> CapacityDemand:
    """Scale one range's declared shape up to the whole event.

    A metric with no declared cost is absent from the result rather than present
    at zero: "nobody costed this" and "this costs nothing" are different claims,
    and only the second should read as satisfied headroom.

    Raises ``ValueError`` on negative counts -- a negative range or node count is
    a derivation bug, and silently clamping it would understate demand.
    """
    if expected_concurrent_ranges < 0 or nodes_per_range < 0:
        raise ValueError("expected_concurrent_ranges and nodes_per_range must be non-negative")

    total_nodes = expected_concurrent_ranges * nodes_per_range

    amounts: dict[str, float] = {}
    for metric_name, cost in per_range_costs.items():
        amounts[metric_name] = amounts.get(metric_name, 0.0) + (expected_concurrent_ranges * float(cost))
    for metric_name, cost in per_node_costs.items():
        amounts[metric_name] = amounts.get(metric_name, 0.0) + (total_nodes * float(cost))

    # Per-range images scale with the cohort; event-shared images are realized
    # once no matter how many ranges run, so scaling them would overstate
    # pre-bake demand by roughly the size of the cohort.
    tally: dict[tuple[str, str, str], int] = {}
    for image in images_per_range:
        key = (image.source_name, image.source_version, image.os_family)
        tally[key] = tally.get(key, 0) + (image.count * expected_concurrent_ranges)
    for image in shared_images:
        key = (image.source_name, image.source_version, image.os_family)
        tally[key] = tally.get(key, 0) + image.count

    image_counts = tuple(
        sorted(
            ImageCount(source_name=name, source_version=version, os_family=os_family, count=count)
            for (name, version, os_family), count in tally.items()
        )
    )

    return CapacityDemand(
        partition_name=partition_name,
        amounts=amounts,
        image_counts=image_counts,
    )
