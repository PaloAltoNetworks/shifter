"""RAES-native GCE range-cell provisioning orchestration (ADR-031, ADR-032).

The RAES counterpart of ``gcp_range_cells.apply_range_cell``/``destroy_range_cell``.
It builds the neutral ``RangeCellPlan`` from a parsed serialized RAES plan
(:func:`raes_gcp_plan.build_raes_range_cell_plan`) and realizes it by reusing the
provenance-neutral GCE apply primitives (``_ensure_network``/``_ensure_subnetwork``/
``_ensure_firewall``/``_ensure_address``, ``_wait_for_operation``, ``GCEClients``,
the resource renderers, and the provisioner-issued host key).

It deliberately does NOT reuse the cyberscript ``_ensure_instance``/
``_provision_range_resources``: those branch on ``role == "dc"``, mint participant
SSH/RDP secrets keyed on a scenario ``instance["source"]``, and manage per-range
Vertex agent credentials -- all scenario/participant concerns. The RAES path is
provisioning-only: it mints one provisioner-managed SSH key per instance
(``ensure_raes_ssh_secret``) for range reachability, installs the injected host
key, and creates the guest. Participant access and scenario setup are later
participant-runtime concerns, not part of provisioning realization.

Destroy is reconstructive: the serialized plan yields deterministic resource
names, so teardown rebuilds the plan (with a default image profile, since only
names are needed) and deletes every owned resource -- no persisted output is
required.
"""

from __future__ import annotations

import base64
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from config import GCERangeCellConfig, GCERangeImageProfile, load_gce_range_cell_config
from gcp_range_cell_clients import GCEClients, _build_clients
from gcp_range_cell_host_binding import GCEInstanceBindingError
from gcp_range_cell_ops import _get_or_none
from gcp_range_cell_outputs import InstanceCredentials, instance_output, subnet_outputs
from gcp_range_cell_resources import instance_resource
from gcp_range_cell_shared_nat import assert_shared_nat_capacity
from gcp_range_cell_types import GceEgressPolicy, InstancePlan, RangeCellPlan, ResourceDict
from gcp_range_cells import (
    _assert_preconfigured_host_binding,
    _ensure_address,
    _ensure_attached_disks_auto_delete,
    _ensure_firewall,
    _ensure_network,
    _ensure_router_nat,
    _ensure_subnetwork,
    _host_public_key_from_instance,
    _insert_instance,
)
from raes_access import RealizedAccessBinding, join_participant_access
from raes_account_credentials import default_account_credential_ops
from raes_active_directory import (
    default_directory_secret_ops,
)
from raes_composition_verification import (
    assert_composition_is_verifiable,
)
from raes_content_delivery import assert_content_delivery_bindings_complete
from raes_gcp_apply_types import RaesGceApplyOptions, RaesGceApplyRuntime
from raes_gcp_attempt_cleanup import _cleanup_created_resources
from raes_gcp_composition import node_bootstrap_script
from raes_gcp_destroy import RaesGceDestroyOptions, destroy_raes_range_cell
from raes_gcp_plan import RaesGcePlanOptions, build_raes_range_cell_plan
from raes_gcp_secret_ops import RaesGceSecretOps, _default_secret_ops
from raes_gcp_verification import _verify_raes_apply
from raes_gcp_vpn_apply import publish_vpn_access, vpn_access_plan
from raes_guest_plan import (
    _access_by_node,
    _accounts_by_node,
    _assert_composition_targets_resolve,
    _publish_participant_access,
    assert_management_login_separate,
)
from raes_plan import RaesPlan, RaesPlanAccount, RaesPlanNode
from raes_snapshot import snapshot_resources
from raes_substrate_observation import verify_prepared_source
from utils.crypto import generate_ssh_host_keypair

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class _ApplyBindings:
    """Optional content and participant access projections admitted for one apply."""

    delivery: list[dict[str, Any]] | None
    access: list[dict[str, Any]] | None


def _record_created(created: list[tuple[str, str]] | None, kind: str, name: str, was_created: bool) -> None:
    """Track only resources inserted by the current apply attempt."""

    if was_created and created is not None:
        created.append((kind, name))


def _apply_runtime(
    options: RaesGceApplyOptions,
    *,
    config: GCERangeCellConfig | None = None,
) -> RaesGceApplyRuntime:
    """Resolve optional apply bindings exactly once."""
    return RaesGceApplyRuntime(
        config=config or options.config or load_gce_range_cell_config(),
        clients=options.clients or _build_clients(),
        secret_ops=options.secret_ops or _default_secret_ops(),
        account_secret_ops=options.account_secret_ops or default_account_credential_ops(),
        credential_installer=options.credential_installer,
        directory_secret_ops=options.directory_secret_ops or default_directory_secret_ops(),
        directory_realizer=options.directory_realizer,
        content_delivery_realizer=options.content_delivery_realizer,
        composition_verifier=options.composition_verifier,
        operating_system_observer=options.operating_system_observer,
        substrate_observer=options.substrate_observer,
        host_readiness_verifier=options.host_readiness_verifier,
        allocated_network_cidrs=options.allocated_network_cidrs,
        runtime_plugin=options.runtime_plugin,
        model_enrollment=options.model_enrollment,
        openvpn=options.openvpn,
    )


def _assert_content_delivery_bindings_complete(
    raes_plan: RaesPlan, delivery_bindings: list[dict[str, Any]] | None
) -> None:
    """Fail closed unless every source-backed content item has exactly one binding.

    Delegates to ``raes_content_delivery.assert_content_delivery_bindings_complete``
    (#1564): a missing binding, an over-claiming extra binding, or an
    unsupported source-backed content_type all raise ``RaesGceCompositionError``
    before any cloud resource is planned or created -- the same early,
    no-cleanup-needed position as the sibling ``_assert_composition_targets_resolve``.
    """
    assert_content_delivery_bindings_complete(raes_plan, delivery_bindings)


def _node_address_of(instance: InstancePlan) -> str:
    """Return the RAES node address an instance belongs to (uuid = ``address#index``)."""
    return str(instance["uuid"]).rsplit("#", 1)[0]


def _ensure_raes_instance(
    plan: RangeCellPlan,
    clients: GCEClients,
    config: GCERangeCellConfig,
    instance: InstancePlan,
    secret_ops: RaesGceSecretOps,
    bootstrap_by_node: dict[str, str],
    created: list[tuple[str, str]] | None = None,
) -> tuple[str, str, str]:
    """Create one RAES range instance with a provisioner-managed SSH + host key.

    Returns ``(ssh_secret_ref, ssh_public_key, host_public_key)``. The provisioner
    mints the guest's SSH host keypair, injects the private half via the startup
    script, and keeps the public half so the setup runner can seed known_hosts
    (StrictHostKeyChecking against a trusted side-channel key). The node's
    composition bootstrap (content/features/accounts) is appended to that startup
    script. On reconcile the guest already serves the injected host key, so it is
    recovered from metadata.
    """
    name = instance["resource_name"]
    existing = _get_or_none(
        clients.instances.get,
        clients.google_exceptions,
        project=plan["project_id"],
        zone=plan["zone"],
        instance=name,
    )
    if existing is None:
        verify_prepared_source(plan, instance, clients)
    else:
        _assert_preconfigured_host_binding(existing, plan, instance)
    secret_ref, public_key = secret_ops.ensure_ssh(plan["range_id"], instance["uuid"])
    if existing is not None:
        if instance["profile"].bootstrap_capability == "preconfigured-machine-host":
            _ensure_attached_disks_auto_delete(plan, clients, name, existing)
        return secret_ref, public_key, _host_public_key_from_instance(existing)

    host_private_key, host_public_key = generate_ssh_host_keypair()
    host_private_key_b64 = base64.b64encode(host_private_key.encode()).decode("ascii")
    _insert_instance(
        plan,
        clients,
        instance,
        instance_resource(
            plan,
            instance,
            config,
            ssh_public_key=public_key,
            host_private_key_b64=host_private_key_b64,
            host_public_key=host_public_key,
            composition_script=bootstrap_by_node.get(_node_address_of(instance), ""),
        ),
    )
    if created is not None:
        created.append(("instance", name))
    return secret_ref, public_key, host_public_key


def _provision_raes_resources(
    plan: RangeCellPlan,
    runtime: RaesGceApplyRuntime,
    bootstrap_by_node: dict[str, str],
    accounts_by_node: dict[str, tuple[RaesPlanAccount, ...]],
    access_by_node: dict[str, tuple[RealizedAccessBinding, ...]],
    created: list[tuple[str, str]] | None = None,
) -> list[ResourceDict]:
    """Create the network, subnets, firewalls, and instances for an RAES range.

    Participant credential references are published (#1710) only *after* the
    authored account credential installed and verified on the guest, so a
    declared endpoint never appears with a credential that was never realized.
    """
    assert_shared_nat_capacity(plan, runtime.clients)
    if plan["manage_network"]:
        _record_created(created, "network", plan["network"]["name"], _ensure_network(plan, runtime.clients))
    for subnet in plan["subnets"]:
        _record_created(
            created, "subnetwork", subnet["resource_name"], _ensure_subnetwork(plan, runtime.clients, subnet)
        )
    if plan.get("shared_nat") is not None:
        _ensure_router_nat(plan, runtime.clients)
    if router_nat := plan.get("router_nat"):
        _record_created(created, "router", router_nat["router_name"], _ensure_router_nat(plan, runtime.clients))
    for firewall in plan["firewalls"]:
        _record_created(created, "firewall", firewall["name"], _ensure_firewall(plan, runtime.clients, firewall))
    return [
        _provision_raes_instance_output(
            plan, runtime, instance, bootstrap_by_node, accounts_by_node, access_by_node, created
        )
        for instance in plan["instances"]
    ]


def _provision_raes_instance_output(
    plan: RangeCellPlan,
    runtime: RaesGceApplyRuntime,
    instance: InstancePlan,
    bootstrap_by_node: dict[str, str],
    accounts_by_node: dict[str, tuple[RaesPlanAccount, ...]],
    access_by_node: dict[str, tuple[RealizedAccessBinding, ...]],
    created: list[tuple[str, str]] | None,
) -> ResourceDict:
    """Provision one RAES host and publish only realized participant access."""
    _record_created(created, "address", instance["address_name"], _ensure_address(plan, runtime.clients, instance))
    ssh_secret_ref, ssh_public_key, host_public_key = _ensure_raes_instance(
        plan,
        runtime.clients,
        runtime.config,
        instance,
        runtime.secret_ops,
        bootstrap_by_node,
        created,
    )
    output = instance_output(
        plan,
        instance,
        InstanceCredentials(
            host_ssh_secret_ref=ssh_secret_ref,
            participant_ssh_secret_ref=None,
            rdp_password_secret_ref=None,
            ssh_public_key=ssh_public_key,
            host_public_key=host_public_key,
        ),
        runtime.config,
    )
    node_address = _node_address_of(instance)
    accounts = accounts_by_node.get(node_address, ())
    account_secret_refs: dict[str, str] = {}
    if accounts:
        account_secret_refs = (
            runtime.credential_installer(
                range_id=plan["range_id"],
                instance_key=instance["uuid"],
                platform=instance["os_type"],
                instance_output=output,
                accounts=accounts,
                secret_ops=runtime.account_secret_ops,
            )
            or {}
        )
    _publish_participant_access(output, access_by_node.get(node_address, ()), account_secret_refs)
    return output


def _preflight_existing_hosts(plan: RangeCellPlan, clients: GCEClients) -> None:
    """Reject conflicting deterministic hosts before any network or secret mutation."""
    for instance in plan["instances"]:
        if instance["profile"].bootstrap_capability != "preconfigured-machine-host":
            continue
        existing = _get_or_none(
            clients.instances.get,
            clients.google_exceptions,
            project=plan["project_id"],
            zone=plan["zone"],
            instance=instance["resource_name"],
        )
        if existing is not None:
            _assert_preconfigured_host_binding(existing, plan, instance)


def _bootstrap_by_node(raes_plan: RaesPlan) -> dict[str, str]:
    """Render non-empty local composition bootstrap scripts by node."""
    return {node.address: script for node in raes_plan.nodes if (script := node_bootstrap_script(node, raes_plan))}


def _cleanup_failed_apply(
    request_uuid: str,
    range_id: int,
    raes_plan: RaesPlan,
    runtime: RaesGceApplyRuntime,
) -> None:
    """Run reconstructive cleanup using the apply pass's resolved clients."""
    # Teardown reconstructs the pool rule by name only.
    remote_access = runtime.openvpn.plan_access().names_only() if runtime.openvpn is not None else None
    destroy_raes_range_cell(
        request_uuid,
        range_id,
        raes_plan,
        RaesGceDestroyOptions(
            config=runtime.config,
            clients=runtime.clients,
            secret_ops=runtime.secret_ops,
            account_secret_ops=runtime.account_secret_ops,
            directory_secret_ops=runtime.directory_secret_ops,
            allocated_network_cidrs=runtime.allocated_network_cidrs,
            remote_access=remote_access,
        ),
    )


def _prepare_raes_apply(
    request_uuid: str,
    range_id: int,
    raes_plan: RaesPlan,
    resolve_image: Callable[[RaesPlanNode], GCERangeImageProfile],
    options: RaesGceApplyOptions,
    config: GCERangeCellConfig,
    bindings: _ApplyBindings,
) -> tuple[RangeCellPlan, tuple[RealizedAccessBinding, ...]]:
    """Validate and plan the complete range before provider mutation."""
    realized_access = join_participant_access(bindings.access or (), raes_plan)
    _assert_composition_targets_resolve(raes_plan)
    _assert_content_delivery_bindings_complete(raes_plan, bindings.delivery)
    assert_composition_is_verifiable(raes_plan)
    expected_composition = {
        *[item.address for item in raes_plan.content],
        *[account.address for account in raes_plan.accounts],
        *[feature.address for feature in raes_plan.features],
    }
    snapshot_resources(raes_plan, expected_composition)
    plan = build_raes_range_cell_plan(
        request_uuid,
        range_id,
        raes_plan,
        resolve_image,
        RaesGcePlanOptions(
            config=config,
            access_bindings=realized_access,
            egress_policy=GceEgressPolicy(mode=options.egress_mode, model_broker=options.model_broker),
            allocated_network_cidrs=options.allocated_network_cidrs,
            remote_access=vpn_access_plan(options),
        ),
    )
    for instance in plan["instances"]:
        assert_management_login_separate(raes_plan, _node_address_of(instance), instance["host_ssh_username"])
    return plan, realized_access


def _cleanup_conflicting_apply(
    plan: RangeCellPlan | None,
    raes_plan: RaesPlan,
    runtime: RaesGceApplyRuntime | None,
    created: list[tuple[str, str]],
    mutation_started: bool,
    options: RaesGceApplyOptions,
) -> None:
    """Keep a conflicting deterministic VM while removing only this attempt's resources."""
    if mutation_started and runtime is not None and plan is not None:
        _cleanup_created_resources(plan, raes_plan, runtime, created)
    if not mutation_started and options.on_pre_mutation_failure is not None:
        options.on_pre_mutation_failure()


def _cleanup_failed_apply_attempt(
    request_uuid: str,
    range_id: int,
    raes_plan: RaesPlan,
    runtime: RaesGceApplyRuntime | None,
    mutation_started: bool,
    options: RaesGceApplyOptions,
) -> None:
    """Reconstructively clean up after a provider mutation, or release preflight state."""
    if mutation_started and runtime is not None:
        logger.exception("RAES GCE range-cell apply failed; attempting cleanup request_id=%s", request_uuid)
        _cleanup_failed_apply(request_uuid, range_id, raes_plan, runtime)
    else:
        logger.exception("RAES GCE range-cell apply failed before provider mutation request_id=%s", request_uuid)
        if options.on_pre_mutation_failure is not None:
            options.on_pre_mutation_failure()


def apply_raes_range_cell(
    request_uuid: str,
    range_id: int,
    raes_plan: RaesPlan,
    resolve_image: Callable[[RaesPlanNode], GCERangeImageProfile],
    options: RaesGceApplyOptions | None = None,
    delivery_bindings: list[dict[str, Any]] | None = None,
    access_bindings: list[dict[str, Any]] | None = None,
) -> ResourceDict:
    """Provision an RAES GCE range cell and return provisioner outputs.

    ``delivery_bindings`` are the byte-free #1564 delivery bindings for the
    range, carried on the immutable operation-input projection (#1837);
    ``None``/empty is the common case of a plan with no source-backed content.

    ``access_bindings`` are the #1710 participant-access sidecar rows from the
    same projection. They are joined to the parsed plan -- and every unrealizable
    declaration rejected -- before any cloud or secret mutation.

    The effective egress posture (PLAT-238) rides on ``options.egress_mode``.
    """
    resolved_options = options or RaesGceApplyOptions()
    resolved_config = resolved_options.config or load_gce_range_cell_config()
    runtime: RaesGceApplyRuntime | None = None
    mutation_started = False
    created: list[tuple[str, str]] = []
    plan: RangeCellPlan | None = None
    try:
        plan, realized_access = _prepare_raes_apply(
            request_uuid,
            range_id,
            raes_plan,
            resolve_image,
            resolved_options,
            resolved_config,
            _ApplyBindings(delivery_bindings, access_bindings),
        )
        runtime = _apply_runtime(resolved_options, config=resolved_config)
        _preflight_existing_hosts(plan, runtime.clients)
        mutation_started = True
        instance_outputs = _provision_raes_resources(
            plan,
            runtime,
            _bootstrap_by_node(raes_plan),
            _accounts_by_node(raes_plan),
            _access_by_node(realized_access),
            created,
        )
        verified_observations = _verify_raes_apply(plan, raes_plan, instance_outputs, delivery_bindings, runtime)
        vpn_access = publish_vpn_access(runtime)
    except GCEInstanceBindingError:
        # A conflicting VM is not ours to delete, even if a race placed it
        # after the read-only preflight and some network resources were made.
        logger.exception("RAES GCE range-cell apply found a conflicting deterministic VM request_id=%s", request_uuid)
        _cleanup_conflicting_apply(plan, raes_plan, runtime, created, mutation_started, resolved_options)
        raise
    except Exception:
        _cleanup_failed_apply_attempt(request_uuid, range_id, raes_plan, runtime, mutation_started, resolved_options)
        raise
    return {
        "subnets": subnet_outputs(plan),
        "instances": instance_outputs,
        **verified_observations,
        **vpn_access,
    }


def realize_access_on_existing_cell(
    request_uuid: str,
    range_id: int,
    raes_plan: RaesPlan,
    resolve_image: Callable[[RaesPlanNode], GCERangeImageProfile],
    options: RaesGceApplyOptions | None = None,
    access_bindings: list[dict[str, Any]] | None = None,
    delivery_bindings: list[dict[str, Any]] | None = None,
) -> ResourceDict:
    """Rotate credentials and return fresh observations for an existing cell."""
    from raes_gcp_activation_apply import realize_existing_cell

    return realize_existing_cell(
        request_uuid, range_id, raes_plan, resolve_image, options, access_bindings, delivery_bindings
    )
