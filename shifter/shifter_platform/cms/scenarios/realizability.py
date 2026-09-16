"""Catalog-side backend realizability projection for the Scenario Editor (ADR-034-R3).

ADR-034-R3 requires ingestion to validate realizability against the backend
manifest and surface non-realizability to the author without creating loopholes.
This module is the bounded, read-only catalog seam the editor renders: given a
registered RAES catalog entry it reports whether the server-selected backend can
realize the pack, and if not, which specific gaps stand in the way.

Two independent contributors produce one ordered answer:

- **Capability** -- does the declared envelope admit the compiled plan
  (:mod:`shared.raes.realizability`, which runs the real RAES compile/plan/
  validate path and never dispatches);
- **Backend supply** -- does the tenant image registry actually offer a concrete
  image for every node, resolved through the one shared matching policy the
  provisioner executes at realization (:mod:`shared.raes.image_policy`).

Boundaries:

- **Detail seam, not the hot path.** ``list_all_scenarios`` stays DB-only; this
  reads pack files and compiles SDL, so it is called for one entry (or a bounded
  set), never fanned out across catalog list rendering. The registry read is one
  bulk query for every demanded name, never one query per node.
- **Derived data.** Nothing is persisted. Realizability is recomputed from
  package identity, target identity, and the current registry, so there is no
  truth column, JSON blob, or migration that could go stale and authorize a
  publication it should not.
- **Fail closed, but honestly.** Inability to assess (untrusted pack, unreadable
  SDL, unsupported target) is ``indeterminate`` -- distinct from a proven
  ``not_realizable`` and never rendered as realizable. Legacy YAML/DB scenarios
  have no RAES pack and are ``not_applicable``; this module never translates a
  legacy definition into RAES to produce a greener answer.
- **Bounded output.** Gaps carry a stable code, category, resource address, and a
  safe message. Never SDL bodies, authored values, parameter or account values,
  provider payloads, credentials, or local filesystem paths.

Editor feedback never replaces the launch-time digest, plan, image, admission, or
provisioner checks; it runs in front of them.
"""

from __future__ import annotations

import logging
from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

from django.conf import settings

from cms.scenarios.catalog_presentation import RAES_SCENARIO_TYPE
from cms.scenarios.registry import get_catalog_entry
from shared.log_sanitize import safe_log_value
from shared.raes.artifact_inventory import ArtifactSupply, BackendArtifact, build_artifact_supply
from shared.raes.image_policy import is_concrete_image_ref, resolve_from_candidates
from shared.raes.realizability import (
    GapCategory,
    RealizabilityGap,
    RealizabilityOutcome,
    assess_scenario_capability,
    worst_outcome,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
    from contextlib import AbstractContextManager

    from cms.models import RaesPackageSource
    from shared.raes.realizability import ImageDemand

logger = logging.getLogger(__name__)

__all__ = ["get_scenario_realizability"]

#: Registry provider key for the only implemented RAES realization adapter.
_GCE_TARGET = "gce"

#: Cloud backend whose RAES realization adapter exists today.
_GCP_PROVIDER = "gcp"

_OBJECT_SOURCE_KIND = "object"
_PLAN_ADDRESS = "plan"

# Stable gap codes. Clients switch on these, never on prose.
_NO_TARGET_ADAPTER = "shifter-realizability.no-target-adapter"
_PACK_UNTRUSTED = "shifter-realizability.pack-untrusted"
_PACK_UNRESOLVABLE = "shifter-realizability.pack-unresolvable"
_MISSING_IMAGE_MAPPING = "shifter-realizability.missing-image-mapping"
_MISSING_SOURCE_IDENTITY = "shifter-realizability.missing-image-identity"


def get_scenario_realizability(scenario_id: str) -> dict[str, Any] | None:
    """Return the bounded realizability projection for one catalog entry.

    Args:
        scenario_id: The catalog id to assess.

    Returns:
        ``None`` when ``scenario_id`` is not a catalog entry. Otherwise a bounded
        dict of ``scenario_id``, ``target_id``, ``outcome``, and ``gaps``.
    """
    entry = get_catalog_entry(scenario_id)
    if entry is None:
        return None
    if entry.get("scenario_type") != RAES_SCENARIO_TYPE:
        return _result(scenario_id, "", RealizabilityOutcome.NOT_APPLICABLE, ())
    return _assess_raes_entry(scenario_id)


def _assess_raes_entry(scenario_id: str) -> dict[str, Any]:
    """Assess a catalog entry already known to be RAES-backed.

    Resolves the registered package source and the server-selected target before
    handing off to the pack assessment; either being unavailable is
    ``indeterminate``, never realizable.
    """
    source = _package_source(scenario_id)
    if source is None:
        return _result(scenario_id, "", RealizabilityOutcome.INDETERMINATE, (_gap_pack_unresolvable(),))

    target_id = _resolve_target_id()
    if not target_id:
        return _result(scenario_id, "", RealizabilityOutcome.INDETERMINATE, (_gap_no_target(),))
    return _assess_registered_pack(scenario_id, source, target_id)


def _assess_registered_pack(scenario_id: str, source: RaesPackageSource, target_id: str) -> dict[str, Any]:
    """Assess a registered RAES pack against ``target_id``.

    The whole assessment runs inside the pack-root context because an
    object-backed pack lives in private temporary staging that is torn down on
    exit -- the SDL must be compiled before that happens.
    """
    with _trusted_scenario_path(source) as (scenario_path, trust_gap):
        if scenario_path is None:
            return _result(scenario_id, target_id, RealizabilityOutcome.INDETERMINATE, (trust_gap,))
        return _assess_trusted_path(scenario_id, scenario_path, target_id)


def _assess_trusted_path(scenario_id: str, scenario_path: Path, target_id: str) -> dict[str, Any]:
    """Combine capability and backend-supply contributors into one ordered answer."""
    capability = assess_scenario_capability(
        scenario_path, artifact_availability_provider=_availability_provider(target_id)
    )
    supply_gaps = _supply_gaps(capability.image_demands, target_id=target_id)
    supply_outcome = RealizabilityOutcome.NOT_REALIZABLE if supply_gaps else RealizabilityOutcome.REALIZABLE

    gaps = tuple(sorted({*capability.gaps, *supply_gaps}))
    outcome = worst_outcome((capability.outcome, supply_outcome))
    logger.info(
        "raes realizability assessed",
        extra={
            "scenario_id": safe_log_value(scenario_id),
            "target_id": target_id,
            "outcome": str(outcome),
            "gap_codes": sorted({gap.code for gap in gaps}),
            "gap_count": len(gaps),
        },
    )
    return _result(scenario_id, target_id, outcome, gaps)


def _package_source(scenario_id: str) -> RaesPackageSource | None:
    """Return the registered RAES package-source row for ``scenario_id``, or None."""
    from cms.models import RaesPackageSource

    return RaesPackageSource.objects.filter(scenario_id=scenario_id).first()


def _resolve_target_id() -> str:
    """Return the stable id of the server-selected RAES realization target.

    Derived only from validated deployment configuration -- never from the
    request. Mirrors the incumbent live-fire admission gate in
    ``cms.services._range_backend_admission`` so assessment and launch agree on
    which backend is admitted. Returns an empty string when the configured
    backend has no RAES realization adapter, which fails closed rather than
    implying an adapter (notably an AWS one) exists.
    """
    if str(getattr(settings, "CLOUD_PROVIDER", "")).strip().lower() != _GCP_PROVIDER:
        return ""
    return _GCE_TARGET if _gcp_backend_admitted() else ""


def _gcp_backend_admitted() -> bool:
    """Return whether the configured GCP range backend admits a live-fire launch."""
    import os

    from shared.range_instantiation_policy import InstantiationPurpose, evaluate_gcp_backend_admission

    admission = evaluate_gcp_backend_admission(
        os.environ.get("GCP_RANGE_BACKEND"),
        os.environ.get("GCP_RANGE_PLANE"),
        InstantiationPurpose.LIVE_FIRE,
    )
    return bool(admission.admitted)


@contextmanager
def _trusted_scenario_path(source: RaesPackageSource) -> Iterator[tuple[Path | None, RealizabilityGap]]:
    """Yield the pack's SDL path after the same trust gates launch applies.

    Yields ``(path, gap)`` where ``path`` is None when the pack could not be
    resolved or its persisted digest no longer matches its bytes; the gap is
    meaningless when a path is yielded. This is a context manager because an
    object-backed pack is staged into a private temporary directory that must be
    cleaned up whether or not assessment succeeds.
    """
    if source.source_kind != _OBJECT_SOURCE_KIND:
        yield _repo_scenario_path(source)
        return

    # ExitStack owns the staging teardown, and the staging helper catches only
    # the staging failure -- a failure inside the assessment body propagates out
    # of the yield below rather than being re-yielded.
    with ExitStack() as stack:
        yield _staged_object_scenario_path(stack, source)


def _staged_object_scenario_path(stack: ExitStack, source: RaesPackageSource) -> tuple[Path | None, RealizabilityGap]:
    """Stage the object pack into ``stack`` and resolve its verified SDL path."""
    try:
        pack_root = stack.enter_context(_stage_object_pack(source))
    except Exception as exc:
        logger.info("raes realizability could not stage object pack (%s)", type(exc).__name__)
        return None, _gap_pack_unresolvable()
    return _verified_object_scenario_path(pack_root, source)


def _repo_scenario_path(source: RaesPackageSource) -> tuple[Path | None, RealizabilityGap]:
    """Resolve and digest-verify a repo-backed pack, exactly as launch does."""
    from cms.scenarios.pack_validation import verify_pack_digest
    from shared.raes.package_loader import resolve_pack_root, resolve_pack_scenario_path

    try:
        pack_root = resolve_pack_root(source.package_ref, package_root=Path(settings.RAES_PACKAGE_ROOT))
        if source.package_digest and not verify_pack_digest(pack_root, source.package_digest):
            return None, _gap_untrusted()
        return resolve_pack_scenario_path(pack_root), _gap_untrusted()
    except Exception as exc:
        # Any resolution failure means "cannot assess", never "realizable". Only
        # the failure class is surfaced: RAES/pack errors embed absolute paths.
        logger.info("raes realizability could not resolve pack (%s)", type(exc).__name__)
        return None, _gap_pack_unresolvable()


def _stage_object_pack(source: RaesPackageSource) -> AbstractContextManager[Path]:
    """Stage the immutable object archive named by ``package_ref``.

    Reuses the launch-side bounded download / safe-extraction path
    (``shared.raes.object_source``) with the configured bucket, prefix, and size
    bounds. The request never supplies a bucket, key, root, or credential.
    """
    from shared.cloud import get_object_storage
    from shared.raes.object_source import stage_object_pack

    bucket = str(getattr(settings, "RAES_PACKAGE_BUCKET", "") or "").strip()
    if not bucket:
        raise RuntimeError("no RAES package bucket is configured")

    prefix = str(getattr(settings, "RAES_PACKAGE_PREFIX", "") or "").strip().strip("/")
    ref = source.package_ref.strip().lstrip("/")
    return stage_object_pack(
        storage=get_object_storage(),
        bucket=bucket,
        key=f"{prefix}/{ref}" if prefix else ref,
        max_archive_bytes=settings.RAES_PACKAGE_MAX_ARCHIVE_BYTES,
        max_uncompressed_bytes=settings.RAES_PACKAGE_MAX_UNCOMPRESSED_BYTES,
        max_entries=settings.RAES_PACKAGE_MAX_ENTRIES,
        expected_pack_name=source.scenario_id,
    )


def _verified_object_scenario_path(pack_root: Path, source: RaesPackageSource) -> tuple[Path | None, RealizabilityGap]:
    """Give a staged object pack the identity guarantees repo packs get.

    Object rows are registered without content validation or digest binding
    (#1578), so assessment re-runs the upstream contract validation, asserts the
    pack identity matches the registered scenario, and verifies the canonical
    digest before anything is compiled (ADR-034-R5).
    """
    from cms.scenarios.pack_validation import validate_pack, verify_pack_digest
    from shared.raes.package_loader import resolve_pack_scenario_path

    try:
        trusted = validate_pack(pack_root) == source.scenario_id and (
            not source.package_digest or verify_pack_digest(pack_root, source.package_digest)
        )
        if not trusted:
            return None, _gap_untrusted()
        return resolve_pack_scenario_path(pack_root), _gap_untrusted()
    except Exception as exc:
        logger.info("raes realizability could not verify object pack (%s)", type(exc).__name__)
        return None, _gap_pack_unresolvable()


def _supply_gaps(demands: Sequence[ImageDemand], *, target_id: str) -> tuple[RealizabilityGap, ...]:
    """Return a gap for every node the tenant image registry cannot supply.

    Mirrors realization exactly: the authored ``source.name`` keys the lookup, a
    source-less node falls back to its ``os_family`` for a base-OS image, and an
    already-concrete provider reference passes through without a mapping.
    """
    candidates = _registry_candidates({_lookup_name(demand) for demand in demands}, target_id=target_id)
    gaps = [gap for demand in demands if (gap := _supply_gap(demand, candidates, target_id)) is not None]
    return tuple(sorted(set(gaps)))


def _supply_gap(
    demand: ImageDemand, candidates: dict[str, list[dict[str, Any]]], target_id: str
) -> RealizabilityGap | None:
    """Return the supply gap for one demand, or None when the registry satisfies it."""
    name = _lookup_name(demand)
    if not name:
        return _gap(
            _MISSING_SOURCE_IDENTITY,
            demand.address,
            GapCategory.IMAGE_SUPPLY,
            "node declares neither an image source nor an os_family, so no backend image can be selected",
        )
    # An unpinned authored source and a base-OS fallback both take the
    # any-version default row; a pinned source must match exactly.
    version = demand.source_version if demand.source_name else None
    supplied = resolve_from_candidates(candidates.get(name, []), version=version) is not None or bool(
        demand.source_name and is_concrete_image_ref(demand.source_name, provider=target_id)
    )
    if supplied:
        return None
    return _gap(
        _MISSING_IMAGE_MAPPING,
        demand.address,
        GapCategory.IMAGE_SUPPLY,
        _missing_mapping_message(demand, name, target_id),
    )


def _missing_mapping_message(demand: ImageDemand, name: str, target_id: str) -> str:
    """Explain which registry mapping is missing, naming identity only."""
    if demand.source_name:
        pinned = demand.source_version or "*"
        return (
            f"no enabled {target_id} image mapping for source '{name}' (version {pinned}); "
            "register an RAES image mapping for it"
        )
    return (
        f"no enabled {target_id} base-OS image mapping for os_family '{name}'; "
        "a node without an authored image source still needs a base image"
    )


def _registry_candidates(names: set[str], *, target_id: str) -> dict[str, list[dict[str, Any]]]:
    """Read the enabled registry rows once, grouped by source name.

    Goes through the ``engine.services`` seam rather than ``engine.models``
    (ADR-001-R1/R2): CMS owns the catalog, Engine owns the image registry. One
    provider-filtered read serves every node, so assessment never issues a query
    per node.
    """
    from engine.services import list_raes_image_mappings

    wanted = {name for name in names if name}
    if not wanted:
        return {}

    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in list_raes_image_mappings(provider=target_id, include_disabled=False):
        if row.source_name not in wanted:
            continue
        grouped.setdefault(row.source_name, []).append(
            {
                "source_version": row.source_version,
                "image_ref": row.image_ref,
                "machine_type": row.machine_type,
                "disk_size_gb": row.disk_size_gb,
                "disk_type": row.disk_type,
            }
        )
    return grouped


def _availability_provider(target_id: str) -> Callable[[Mapping[str, Any]], ArtifactSupply]:
    """Return a provider that answers artifact availability from the tenant registry.

    Injected into :func:`assess_scenario_capability` so the artifact-resolution
    seam sees the backend-owned inventory without ``shared.raes`` ever reaching
    into the engine registry (the catalog layer owns that read, exactly like the
    image-supply contributor). The provider is typed with boundary-safe ``Any`` so
    this catalog layer never has to name upstream RAES contract types (ADR-031-R1).
    """

    def provider(requirements: Mapping[str, Any]) -> ArtifactSupply:
        """Answer per-requirement artifact availability for ``requirements`` from the registry."""
        return build_artifact_supply(requirements, _backend_inventory(target_id))

    return provider


def _backend_inventory(target_id: str) -> list[BackendArtifact]:
    """Read the backend-owned portable artifacts for ``target_id`` from the registry.

    Delegates to the one shared projection (``engine.services.list_backend_artifacts``)
    so the editor realizability contributor and the launch-time fencing resolver
    agree on exactly what the backend owns.
    """
    from engine.services import list_backend_artifacts

    return list_backend_artifacts(provider=target_id)


def _lookup_name(demand: ImageDemand) -> str:
    """Return the registry key for a demand: authored source name, else os_family."""
    return demand.source_name or demand.os_family


def _result(
    scenario_id: str, target_id: str, outcome: RealizabilityOutcome, gaps: Iterable[RealizabilityGap]
) -> dict[str, Any]:
    """Build the bounded projection dict rendered by the API and the editor."""
    return {
        "scenario_id": scenario_id,
        "target_id": target_id,
        "outcome": outcome,
        "gaps": [
            {"code": gap.code, "address": gap.address, "category": gap.category, "message": gap.message} for gap in gaps
        ],
    }


def _gap(code: str, address: str, category: GapCategory, message: str) -> RealizabilityGap:
    """Build a bounded gap."""
    return RealizabilityGap(code=code, address=address, category=category, message=message)


def _gap_no_target() -> RealizabilityGap:
    """Gap for a deployment whose configured backend has no RAES realization adapter."""
    return _gap(
        _NO_TARGET_ADAPTER,
        _PLAN_ADDRESS,
        GapCategory.TARGET,
        "the configured range backend has no RAES realization adapter, so realizability cannot be assessed",
    )


def _gap_untrusted() -> RealizabilityGap:
    """Gap for a pack whose bytes no longer match its registered digest."""
    return _gap(
        _PACK_UNTRUSTED,
        _PLAN_ADDRESS,
        GapCategory.SOURCE_INTEGRITY,
        "the pack's contents no longer match the digest recorded at registration; re-register the pack",
    )


def _gap_pack_unresolvable() -> RealizabilityGap:
    """Gap for a pack that could not be located or read at all."""
    return _gap(
        _PACK_UNRESOLVABLE,
        _PLAN_ADDRESS,
        GapCategory.SOURCE_INTEGRITY,
        "the registered pack could not be resolved, so realizability cannot be assessed",
    )
