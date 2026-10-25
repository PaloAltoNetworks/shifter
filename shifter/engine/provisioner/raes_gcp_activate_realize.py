"""Live GCE realization of a claimant's fresh access at warm activation (#28).

The claimed generation's infrastructure is already realized; activation replaces
only the *access* surface for the claimant. It reuses the exact apply realization
path -- ``raes_gcp_apply.realize_access_on_existing_cell`` -- whose instance ensure
is idempotent, so no infrastructure is recreated: the guest account credentials are
re-established freshly (the caller scrubbed the pre-claim secrets first) and the
claimant's participant access is published. The bounded member/access rows the
Engine applier persists are projected from the realized instance outputs (secret
*references* only, never credential values).

When the claimant's range holds an OpenVPN capability, activation adds the pool
firewall rule and mints the claimant's generation-fenced profile (#2480). The
pre-claim generation never held one, and the scrub step deleted any residue.

This module performs live GCE work; its efficacy is verified on a real range (the
repository's verification norm for provisioner cloud effects). It fails closed: any
realization error raises and the orchestrator retires the generation rather than
hand it over.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from uuid import UUID

from shared.raes.completion_evidence import build_completion_evidence
from shared.warm_pool.activation_input import ActivationInput

from cloud.exceptions import CloudError
from config import GCERangeCellConfig
from raes_gce_image import registry_image_resolver
from raes_gcp_activate import ActivationResult
from raes_gcp_apply import RaesGceApplyOptions, realize_access_on_existing_cell
from raes_gcp_apply_types import RaesGceOpenVpn
from raes_plan import parse_plan
from raes_range_ops import _realized_members
from raes_snapshot import snapshot_resources

logger = logging.getLogger(__name__)


class ActivationRealizationError(CloudError):
    """The claimant's fresh access could not be realized on the claimed generation."""


def realize_claimant_access_on_cell(
    activation: ActivationInput,
    activate_generation: UUID,
    *,
    config: GCERangeCellConfig | None = None,
    allocated_network_cidrs: Sequence[tuple[str, str]] | None = None,
    openvpn: RaesGceOpenVpn | None = None,
) -> ActivationResult:
    """Rotate credentials and realize the claimant's participant access; return members.

    Fails closed (raising :class:`ActivationRealizationError`) on any realization
    error so a claimant is never handed a range whose access could not be fully
    re-established for them.
    """
    operation_input = activation.raes_input
    raes_plan = parse_plan(operation_input.plan)
    try:
        result = realize_access_on_existing_cell(
            str(activate_generation),
            activation.legacy_range_id,
            raes_plan,
            registry_image_resolver(operation_input),
            options=RaesGceApplyOptions(
                config=config,
                egress_mode=operation_input.egress_mode,
                allocated_network_cidrs=allocated_network_cidrs,
                openvpn=openvpn,
            ),
            access_bindings=operation_input.access_binding_transport(),
            delivery_bindings=operation_input.binding_transport(),
        )
        verified = result["composition_verified_addresses"]
        if not isinstance(verified, list) or any(not isinstance(address, str) for address in verified):
            raise ActivationRealizationError("warm activation verification addresses are invalid")
        resources = snapshot_resources(raes_plan, set(verified))
        completion = build_completion_evidence(
            operation_input.plan,
            resources=resources,
            operating_systems=result["operating_systems"],
            compute_substrates=result["compute_substrates"],
            generation_id=str(activate_generation),
        )
        vpn_access = result.get("vpn_access")
        if vpn_access is not None and not isinstance(vpn_access, dict):
            raise ActivationRealizationError("warm activation OpenVPN realization is invalid")
    except Exception as exc:
        raise ActivationRealizationError(
            f"warm activation could not realize claimant access: {type(exc).__name__}"
        ) from None
    return ActivationResult(members=_realized_members(result), completion=completion, vpn_access=vpn_access)
