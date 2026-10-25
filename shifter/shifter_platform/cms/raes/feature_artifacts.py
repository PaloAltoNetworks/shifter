"""Resolve unprojected feature sources to recipe-acquired artifacts at launch (ADR-034-R11, R12).

A scenario declares third-party software as an RAES ``artifact`` feature by name
and version only; no pack carries its bytes. At materialization this resolver
asks Engine for the backend-owned artifact (acquiring it once if needed, waiting
a bounded time) and turns it into the same byte-free feature delivery binding a
pack-projected artifact produces. Anything it cannot satisfy fails this range's
materialization; other ranges are unaffected.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

from django.conf import settings

from shared.raes.content_delivery import FEATURE_BINDING_VERSION, ContentDeliveryError, DeliveryBinding

if TYPE_CHECKING:
    from engine.services import StorageTarget
    from shared.raes.content_delivery_prep import ContentRef
    from shared.raes.realizability import FeatureArtifactDemand

logger = logging.getLogger(__name__)

# Guest platform of the backend's Linux range instances (x86_64, glibc). A backend
# realization fact, not authored intent: other node OS families have no platform
# with acquisition support yet and fail closed.
_GUEST_PLATFORMS = {"linux": "linux-x64-glibc"}
_ACQUIRABLE_MECHANISMS = {"exact-artifact", "backend-owned-artifact"}


def _resources(plan: Mapping[str, Any]) -> Mapping[str, Any]:
    """The compiled plan's resources by address (empty when malformed)."""
    resources = plan.get("resources")
    return resources if isinstance(resources, Mapping) else {}


def _mapping(value: object) -> Mapping[str, Any]:
    """``value`` when it is a mapping, else an empty one."""
    return value if isinstance(value, Mapping) else {}


def _payload(resource: object) -> Mapping[str, Any]:
    """A plan resource's payload mapping."""
    return _mapping(_mapping(resource).get("payload"))


def _guest_platform(plan: Mapping[str, Any], node_address: str) -> str:
    """Platform of the node a feature binds to, from its compiled OS family."""
    payload = _payload(_resources(plan).get(node_address))
    node = _mapping(_mapping(payload.get("spec")).get("node"))
    os_family = str(payload.get("os_family") or node.get("os") or "").lower()
    platform = _GUEST_PLATFORMS.get(os_family)
    if platform is None:
        raise ContentDeliveryError(f"feature artifacts are not acquirable for '{os_family or 'unknown'}' nodes")
    return platform


def _check_requirement(plan: Mapping[str, Any], resource_address: str, source_name: str) -> None:
    """Honor the authored RAES artifact requirement on the feature's source."""
    template = _mapping(_mapping(_payload(_resources(plan).get(resource_address)).get("spec")).get("template"))
    requirement = _mapping(template.get("source")).get("artifact_requirement")
    if not isinstance(requirement, Mapping):
        return
    if requirement.get("explicitness") == "constrained":
        raise ContentDeliveryError(f"feature '{source_name}': unsupported constrained realization")
    routes = requirement.get("permitted_routes") or []
    permitted = any(
        isinstance(route, Mapping)
        and isinstance(route.get("mechanism"), Mapping)
        and route["mechanism"].get("mechanism") in _ACQUIRABLE_MECHANISMS
        and route.get("acquisition") == "pull"
        for route in routes
    )
    if not permitted:
        raise ContentDeliveryError(
            f"feature '{source_name}': unsupported backend mechanism (acquisition not permitted)"
        )


def feature_artifact_resolver(
    plan: Mapping[str, Any], *, target: StorageTarget | None = None
) -> Callable[[ContentRef], DeliveryBinding]:
    """Return the ``acquire_feature`` resolver for one compiled plan.

    ``target`` (the delivery storage location) defaults to the deployment's.
    """

    def acquire(ref: ContentRef) -> DeliveryBinding:
        """Resolve one unprojected feature to its ready acquired artifact, or fail this range."""
        from engine.services import (
            ArtifactRequest,
            FeatureArtifactUnavailableError,
            await_ready,
            default_storage_target,
        )

        if ref.feature_type != "artifact":
            raise ContentDeliveryError(f"feature '{ref.source_name}': only artifact features are acquirable")
        _check_requirement(plan, ref.address, ref.source_name)
        request = ArtifactRequest(ref.source_name, ref.source_version, _guest_platform(plan, ref.target_address))
        try:
            row = await_ready(
                request,
                target=target or default_storage_target(),
                timeout=timedelta(seconds=settings.RAES_FEATURE_ARTIFACT_WAIT_SECONDS),
            )
        except FeatureArtifactUnavailableError as exc:
            raise ContentDeliveryError(f"feature artifact '{ref.source_name}' is unavailable: {exc}") from None
        if row.byte_count is None or not row.sha256:
            raise ContentDeliveryError(f"feature artifact '{ref.source_name}' has an incomplete inventory record")
        return DeliveryBinding(
            content_address=None,
            sha256=row.sha256,
            storage_key=row.storage_key,
            byte_count=row.byte_count,
            binding_version=FEATURE_BINDING_VERSION,
            resource_type="feature-binding",
            resource_address=ref.address,
            payload_kind=row.payload_kind,
            install_policy=row.install_policy,
        )

    return acquire


def acquisition_enabled() -> bool:
    """Whether this deployment runs acquisition Jobs (an image is configured)."""
    import os

    return bool(os.environ.get("FEATURE_ARTIFACT_JOB_IMAGE", ""))


def _pack_root(scenario_path: Path) -> Path | None:
    """The pack root containing ``scenario_path`` (the nearest ``pack.yaml``)."""
    for parent in scenario_path.parents:
        if (parent / "pack.yaml").is_file():
            return parent
    return None


def _projected(pack_root: Path | None, demand: FeatureArtifactDemand) -> bool:
    """Whether the pack itself projects (and therefore carries) this feature."""
    from shared.raes.content_delivery_prep import pack_projects_feature

    return pack_root is not None and pack_projects_feature(
        pack_root, source_name=demand.source_name, source_version=demand.source_version, feature_type="artifact"
    )


def request_pack_feature_artifacts(scenario_id: str, *, target: StorageTarget | None = None) -> int:
    """Claim acquisition for every unprojected artifact feature a registered pack declares.

    Runs before any range needs the artifacts (pack registration, deploy
    bootstrap). It never waits and never fails its caller: the launcher completes
    the attempts, and a launch that still finds an artifact unavailable fails
    only that range. Returns the number of acquisitions requested.
    """
    from cms.models import RaesPackageSource
    from cms.scenarios.realizability import _trusted_scenario_path

    source = RaesPackageSource.objects.filter(scenario_id=scenario_id).first() if acquisition_enabled() else None
    if source is None:
        return 0
    # The pack is read only inside the trusted staging context; claims need no files.
    with _trusted_scenario_path(source) as (scenario_path, _gap):
        demands = _unprojected_demands(Path(scenario_path)) if scenario_path is not None else []
    return sum(_request(demand, platform, target) for demand, platform in demands)


def _unprojected_demands(scenario_path: Path) -> list[tuple[FeatureArtifactDemand, str]]:
    """The scenario's artifact features on acquirable guests that its pack does not carry."""
    from shared.raes.realizability import assess_scenario_capability

    pack_root = _pack_root(scenario_path)
    demands: list[tuple[FeatureArtifactDemand, str]] = []
    for demand in assess_scenario_capability(scenario_path).feature_artifact_demands:
        platform = _GUEST_PLATFORMS.get(demand.os_family.lower())
        if platform is not None and not _projected(pack_root, demand):
            demands.append((demand, platform))
    return demands


def _request(demand: FeatureArtifactDemand, platform: str, target: StorageTarget | None) -> int:
    """Claim one acquisition; 1 if claimed, 0 when no platform recipe covers the source."""
    from engine.services import ArtifactRequest, default_storage_target, request_acquisition
    from shared.feature_artifacts.recipes import RecipeError

    try:
        request_acquisition(
            ArtifactRequest(demand.source_name, demand.source_version, platform),
            target=target or default_storage_target(),
        )
    except RecipeError:
        logger.info("feature artifact has no platform recipe source=%s", demand.source_name)
        return 0
    return 1
