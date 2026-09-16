"""Warm GCE activation realization and fresh completion observations."""

from collections.abc import Callable
from typing import Any

from config import GCERangeImageProfile
from gcp_range_cell_types import GceEgressPolicy, ResourceDict
from raes_access import join_participant_access
from raes_composition_verification import assert_composition_is_verifiable
from raes_content_delivery import RaesContentDeliveryOps, realize_raes_content_delivery
from raes_gcp_apply import (
    RaesGceApplyOptions,
    _access_by_node,
    _accounts_by_node,
    _apply_runtime,
    _assert_content_delivery_bindings_complete,
    _bootstrap_by_node,
    _provision_raes_resources,
    _realize_directory,
)
from raes_gcp_plan import RaesGcePlanOptions, build_raes_range_cell_plan
from raes_operating_system import validate_operating_systems
from raes_plan import RaesPlan, RaesPlanNode
from raes_snapshot import snapshot_resources


def realize_existing_cell(
    request_uuid: str,
    range_id: int,
    raes_plan: RaesPlan,
    resolve_image: Callable[[RaesPlanNode], GCERangeImageProfile],
    options: RaesGceApplyOptions | None,
    access_bindings: list[dict[str, Any]] | None,
    delivery_bindings: list[dict[str, Any]] | None,
) -> ResourceDict:
    """Reconcile warm access and return fresh completion observations."""
    resolved_options = options or RaesGceApplyOptions()
    runtime = _apply_runtime(resolved_options)
    realized_access = join_participant_access(access_bindings or (), raes_plan)
    _assert_content_delivery_bindings_complete(raes_plan, delivery_bindings)
    assert_composition_is_verifiable(raes_plan)
    plan = build_raes_range_cell_plan(
        request_uuid,
        range_id,
        raes_plan,
        resolve_image,
        RaesGcePlanOptions(
            config=runtime.config,
            access_bindings=realized_access,
            egress_policy=GceEgressPolicy(mode=resolved_options.egress_mode),
            allocated_network_cidr=runtime.allocated_network_cidr,
        ),
    )
    outputs = _provision_raes_resources(
        plan,
        runtime,
        _bootstrap_by_node(raes_plan),
        _accounts_by_node(raes_plan),
        _access_by_node(realized_access),
    )
    verified = set(_realize_directory(plan, raes_plan, outputs, runtime))
    realize_raes_content_delivery(
        raes_plan=raes_plan,
        instance_outputs=outputs,
        delivery_bindings=delivery_bindings,
        ops=RaesContentDeliveryOps(verify_only=True),
    )
    verified.update(item.address for item in raes_plan.content if item.source_name)
    verified.update(feature.address for feature in raes_plan.features)
    verified.update(runtime.composition_verifier(raes_plan, outputs))
    operating_systems = runtime.operating_system_observer(raes_plan, outputs)
    validate_operating_systems(raes_plan, operating_systems)
    compute_substrates = runtime.substrate_observer(plan, runtime.clients)
    snapshot_resources(raes_plan, verified)
    return {
        "instances": outputs,
        "composition_verified_addresses": sorted(verified),
        "operating_systems": operating_systems,
        "compute_substrates": compute_substrates,
    }
