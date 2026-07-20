"""Shared catalog namespace guard for legacy scenarios and ACES packs (#1578).

Legacy scenarios and ACES package sources live in separate stores, so no
cross-table database constraint can make their shared ``scenario_id`` namespace
unique. Every mutation boundary therefore calls :func:`ensure_scenario_id_available`:
pack registration rejects active legacy owners, while legacy model saves reject
registered pack owners. The registry retains its fail-closed projection check as
race and historical-data defense in depth.

This lives in its own module rather than in ``cms.scenarios.registry`` so the
registry stays focused on the unified catalog projection; the no-shadow set is a
distinct, small concern consumed by both mutation directions.
"""

from __future__ import annotations

from typing import Literal

from cms.scenarios.loader import get_all_scenarios as get_yaml_scenarios


class ScenarioIdCollisionError(ValueError):
    """Raised when one catalog kind tries to claim another kind's active id."""


def active_legacy_scenario_ids() -> set[str]:
    """Return the active YAML-default and DB-custom scenario ids (the no-shadow set).

    A ``scenario_id`` is "taken" the moment a legacy scenario uses it, so the set
    is every YAML default id plus every active DB ``Scenario`` id (soft-deleted
    rows are excluded by the model's default manager). Both surfaces enforce a
    unique id, so a pack reusing any of them would shadow live content.
    """
    from cms.models import Scenario

    yaml_ids = {template.id for template in get_yaml_scenarios()}
    db_ids = set(Scenario.objects.values_list("scenario_id", flat=True))
    return yaml_ids | db_ids


def ensure_scenario_id_available(scenario_id: str, *, registering: Literal["legacy", "pack"]) -> None:
    """Reject a cross-store namespace collision for one catalog mutation.

    Same-kind uniqueness remains owned by each store's database constraint.
    This guard owns only the otherwise-unenforceable legacy-versus-pack seam.
    """
    if registering == "pack":
        if scenario_id in active_legacy_scenario_ids():
            raise ScenarioIdCollisionError(f"pack id '{scenario_id}' shadows an active legacy scenario")
        return

    if registering == "legacy":
        from cms.models import AcesPackageSource

        if AcesPackageSource.objects.filter(scenario_id=scenario_id).exists():
            raise ScenarioIdCollisionError(f"legacy scenario id '{scenario_id}' shadows a registered ACES pack")
        return

    raise ValueError("registering must be 'legacy' or 'pack'")
