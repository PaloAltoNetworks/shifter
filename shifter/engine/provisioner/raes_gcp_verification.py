"""Post-provisioning RAES guest realization and evidence checks on GCE."""

from __future__ import annotations

from typing import Any

from gcp_range_cell_types import RangeCellPlan, ResourceDict
from raes_gcp_apply_types import RaesGceApplyRuntime
from raes_operating_system import validate_operating_systems
from raes_participant_host_keys import observe_participant_host_keys
from raes_plan import RaesPlan
from raes_snapshot import snapshot_resources


def _realize_directory(
    plan: RangeCellPlan,
    raes_plan: RaesPlan,
    instance_outputs: list[ResourceDict],
    runtime: RaesGceApplyRuntime,
) -> frozenset[str]:
    """Realize admitted directory topology when the plan carries a domain."""
    if raes_plan.domains:
        runtime.directory_realizer(
            range_id=plan["range_id"],
            raes_plan=raes_plan,
            instance_outputs=instance_outputs,
            secret_ops=runtime.directory_secret_ops,
        )
        return frozenset(
            account.address
            for account in raes_plan.accounts
            if account.domain_ref is not None or account.domain_id is not None
        )
    return frozenset()


def _realize_content_delivery(
    raes_plan: RaesPlan,
    instance_outputs: list[ResourceDict],
    delivery_bindings: list[dict[str, Any]] | None,
    runtime: RaesGceApplyRuntime,
) -> frozenset[str]:
    """Deliver every source-backed content item when the plan carries one."""
    if any(item.source_name for item in raes_plan.content) or bool(raes_plan.features):
        runtime.content_delivery_realizer(
            raes_plan=raes_plan,
            instance_outputs=instance_outputs,
            delivery_bindings=delivery_bindings,
        )
        return frozenset(
            [item.address for item in raes_plan.content if item.source_name]
            + [feature.address for feature in raes_plan.features]
        )
    return frozenset()


def _verify_raes_apply(
    plan: RangeCellPlan,
    raes_plan: RaesPlan,
    instance_outputs: list[ResourceDict],
    delivery_bindings: list[dict[str, Any]] | None,
    runtime: RaesGceApplyRuntime,
) -> ResourceDict:
    """Complete guest realization and return verified range observations."""
    verified = set(_realize_directory(plan, raes_plan, instance_outputs, runtime))
    verified.update(_realize_content_delivery(raes_plan, instance_outputs, delivery_bindings, runtime))
    if runtime.model_enrollment is not None:
        runtime.model_enrollment(raes_plan, instance_outputs)
    if runtime.runtime_plugin is not None:
        runtime.runtime_plugin(raes_plan, instance_outputs)
    runtime.host_readiness_verifier(instance_outputs)
    observe_participant_host_keys(instance_outputs)
    verified.update(runtime.composition_verifier(raes_plan, instance_outputs))
    operating_systems = runtime.operating_system_observer(raes_plan, instance_outputs)
    validate_operating_systems(raes_plan, operating_systems)
    compute_substrates = runtime.substrate_observer(plan, runtime.clients)
    snapshot_resources(raes_plan, verified)
    return {
        "composition_verified_addresses": sorted(verified),
        "operating_systems": operating_systems,
        "compute_substrates": compute_substrates,
    }
