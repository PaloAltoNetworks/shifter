"""Catalog-model run-capability projection for RAES packs (#1579, ADR-034).

ADR-034 requires that parameterized experiment runs be representable in the
*catalog* model as well as the realizability model. This module is the bounded,
read-only catalog-side seam: given a registered RAES ``scenario_id`` it reports
whether the pack's scenario declares parameterized runs (RAES SDL ``variables``)
and their bounded declaration schema.

It is a *detail* projection, deliberately kept off the hot ``list_all_scenarios``
path (which is DB-only) so listing the catalog never pays pack-file IO. Access,
launchability, and the base projection stay in :mod:`cms.scenarios.registry`;
this seam only adds run-capability metadata.

Boundaries:

- **Provenance-only persistence is unchanged.** ``RaesPackageSource`` is not
  widened; the run schema is read live from the pack's SDL, never stored.
- **Repo packs only.** Object-backed packs have no containment-checked local
  resolution until #1567, so they report ``resolvable: False`` rather than being
  parsed. Legacy YAML/DB scenarios have no RAES pack and return ``None``.
- **Fail-soft and pure.** A catalog read never raises on pack IO and never
  executes tooling: SDL parsing is pure Python. Any resolution/parse failure
  degrades to ``resolvable: False``.
- **Bounded, body-free.** Only parameter *declarations* (names/types/counts)
  cross the boundary through :mod:`shared.raes.runs`; never SDL bodies, defaults,
  allowed-value enumerations, per-run values, or secrets.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from django.conf import settings

from shared.log_sanitize import safe_log_value

if TYPE_CHECKING:
    from shared.raes.runs import RunParameter

logger = logging.getLogger(__name__)

_OBJECT_SOURCE_KIND = "object"

__all__ = ["get_run_capability"]


def get_run_capability(scenario_id: str) -> dict[str, Any] | None:
    """Return the bounded run-capability projection for an RAES catalog entry.

    Args:
        scenario_id: The catalog id to project.

    Returns:
        ``None`` when no RAES package is registered for ``scenario_id`` (unknown
        id or a non-RAES legacy scenario). Otherwise a bounded dict:

        - ``scenario_id`` / ``source_kind``: identity;
        - ``resolvable``: whether the pack's SDL entry could be read;
        - ``parameterized``: whether the scenario declares run variables;
        - ``parameters``: bounded declaration dicts (empty when not parameterized
          or not resolvable).
    """
    from cms.models import RaesPackageSource

    source = RaesPackageSource.objects.filter(scenario_id=scenario_id).first()
    if source is None:
        return None

    projection: dict[str, Any] = {
        "scenario_id": source.scenario_id,
        "source_kind": source.source_kind,
        "resolvable": False,
        "parameterized": False,
        "parameters": [],
    }
    # Object-backed packs have no containment-checked local resolution until #1567,
    # so they stay non-resolvable rather than being parsed. Repo packs read their
    # declared run parameters; a resolution/parse failure degrades soft (None).
    if source.source_kind != _OBJECT_SOURCE_KIND:
        parameters = _read_repo_pack_parameters(source.package_ref)
        if parameters is not None:
            projection["resolvable"] = True
            projection["parameterized"] = len(parameters) > 0
            projection["parameters"] = [_parameter_projection(parameter) for parameter in parameters]
    return projection


def _read_repo_pack_parameters(package_ref: str) -> tuple[RunParameter, ...] | None:
    """Resolve a repo pack and read its declared run parameters.

    Returns the (possibly empty) declared-parameter tuple, or ``None`` when the
    pack cannot be resolved or its SDL cannot be read (fail-soft: a catalog read
    must not raise on pack IO).
    """
    from shared.raes.package_loader import (
        RaesPackageError,
        resolve_pack_root,
        resolve_pack_scenario_path,
    )
    from shared.raes.runs import RunRepresentationError, read_run_parameters

    try:
        pack_root = resolve_pack_root(package_ref, package_root=Path(settings.RAES_PACKAGE_ROOT))
        scenario_path = resolve_pack_scenario_path(pack_root)
        return read_run_parameters(scenario_path)
    except (RaesPackageError, RunRepresentationError) as exc:
        logger.info(
            "get_run_capability: pack not resolvable package_ref=%s reason=%s",
            safe_log_value(package_ref),
            type(exc).__name__,
        )
        return None


def _parameter_projection(parameter: RunParameter) -> dict[str, Any]:
    """Project one declared run parameter to a bounded, body-free dict."""
    return {
        "name": parameter.name,
        "type": parameter.type,
        "required": parameter.required,
        "has_default": parameter.has_default,
        "allowed_value_count": parameter.allowed_value_count,
    }
