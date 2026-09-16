"""RAES scenario image projection for capacity pre-bake planning (PLAT-201).

CMS resolves the digest-bound package source and projects only RAES VM image
identities. The Engine consumes this bounded projection rather than parsing SDL
or maintaining a second image model.

Only identity and counts cross this boundary: never authored services, flags,
data seeds, domain configuration, or any other scenario payload. A scenario
that cannot be read yields an empty, explicitly unresolved projection rather
than a fabricated one -- consistent with the rest of the capacity layer, where
"we could not determine this" is never rendered as a satisfied answer.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from django.conf import settings

from cms.models import RaesPackageSource
from cms.scenarios.pack_validation import verify_pack_digest
from shared.capacity import ImageCount
from shared.raes.package_loader import load_pack_scenario, resolve_pack_root

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ScenarioImageProjection:
    """Image identities one range needs, split by how they scale.

    ``per_range`` scales with the number of concurrent ranges. ``shared`` is
    realized once for the event regardless of cohort size. ``resolved`` is False
    when the scenario could not be read or carried no recognizable node shape.
    """

    per_range: tuple[ImageCount, ...] = ()
    shared: tuple[ImageCount, ...] = ()
    resolved: bool = False

    def as_hint(self) -> dict[str, Any]:
        """Return the JSON-safe form carried inside a capacity declaration."""
        return {
            "resolved": self.resolved,
            "per_range": [_as_entry(image) for image in self.per_range],
            "shared": [_as_entry(image) for image in self.shared],
        }


def _as_entry(image: ImageCount) -> dict[str, Any]:
    """Project one image count into its bounded wire form."""
    return {
        "source_name": image.source_name,
        "source_version": image.source_version,
        "os_family": image.os_family,
        "count": image.count,
    }


def project_scenario_images(scenario_id: str) -> ScenarioImageProjection:
    """Return the image identities one range of ``scenario_id`` needs.

    Never raises: an unknown or unreadable scenario yields an unresolved,
    empty projection so a capacity assessment degrades to "no per-image demand"
    rather than to a wrong pre-bake number.
    """
    try:
        source = RaesPackageSource.objects.get(scenario_id=scenario_id)
        pack_root = resolve_pack_root(source.package_ref, package_root=Path(settings.RAES_PACKAGE_ROOT))
        if not verify_pack_digest(pack_root, source.package_digest):
            raise ValueError("pack digest mismatch")
        scenario = load_pack_scenario(pack_root)
    except Exception:
        logger.warning("capacity: could not load scenario for image projection")
        return ScenarioImageProjection()

    tally: dict[tuple[str, str, str], int] = {}
    for node in scenario.nodes.values():
        if str(node.type.value) != "compute" or node.source is None:
            continue
        key = (node.source.name, node.source.version, str(node.os.value) if node.os is not None else "")
        tally[key] = tally.get(key, 0) + 1
    return ScenarioImageProjection(per_range=_to_counts(tally), resolved=bool(tally))


def _to_counts(tally: dict[tuple[str, str, str], int]) -> tuple[ImageCount, ...]:
    """Turn an identity tally into a stable, sorted tuple of image counts."""
    return tuple(
        sorted(
            ImageCount(source_name=name, source_version=version, os_family=os_family, count=count)
            for (name, version, os_family), count in tally.items()
        )
    )
