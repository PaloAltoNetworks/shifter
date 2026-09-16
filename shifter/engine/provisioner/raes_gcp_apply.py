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
from gcp_range_cell_ops import _get_or_none, _wait_for_operation
from gcp_range_cell_outputs import InstanceCredentials, instance_output, subnet_outputs
from gcp_range_cell_resources import instance_resource
from gcp_range_cell_types import GceEgressPolicy, InstancePlan, RangeCellPlan, ResourceDict
from gcp_range_cells import (
    _ensure_address,
    _ensure_firewall,
    _ensure_network,
    _ensure_router_nat,
    _ensure_subnetwork,
    _host_public_key_from_instance,
)
from raes_access import RealizedAccessBinding, join_participant_access
from raes_account_credentials import (
    RaesAccountCredentialOps,
    default_account_credential_ops,
    install_instance_account_credentials,
)
from raes_active_directory import (
    RaesDirectorySecretOps,
    default_directory_secret_ops,
    realize_raes_active_directory,
)
from raes_composition_verification import (
    assert_composition_is_verifiable,
    verify_bootstrap_composition,
)
from raes_content_delivery import assert_content_delivery_bindings_complete, realize_raes_content_delivery
from raes_gcp_composition import node_bootstrap_script
from raes_gcp_destroy import RaesGceDestroyOptions, destroy_raes_range_cell
from raes_gcp_plan import RaesGcePlanError, RaesGcePlanOptions, build_raes_range_cell_plan
from raes_gcp_secret_ops import RaesGceSecretOps, _default_secret_ops
from raes_operating_system import observe_operating_systems, validate_operating_systems
from raes_plan import RaesPlan, RaesPlanAccount, RaesPlanNode
from raes_snapshot import snapshot_resources
from raes_substrate_observation import observe_gce_substrates, verify_prepared_source
from utils.crypto import generate_ssh_host_keypair

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RaesGceApplyOptions:
    """Optional infrastructure and credential bindings for an RAES apply."""

    config: GCERangeCellConfig | None = None
    clients: GCEClients | None = None
    secret_ops: RaesGceSecretOps | None = None
    # Effective range egress posture pinned at create (PLAT-238), carried here so
    # the apply seam stays within the parameter budget; a `none` range gets no
    # public-web/allow-CIDR firewall lane and no range-owned Cloud NAT.
    egress_mode: str = "status-quo"
    # Tenant-allocated subnet selected by the GCE adapter for open portable
    # network intent in shared-VPC mode.
    allocated_network_cidr: str | None = None
    account_secret_ops: RaesAccountCredentialOps | None = None
    credential_installer: Callable[..., dict[str, str]] = install_instance_account_credentials
    directory_secret_ops: RaesDirectorySecretOps | None = None
    directory_realizer: Callable[..., None] = realize_raes_active_directory
    content_delivery_realizer: Callable[..., None] = realize_raes_content_delivery
    composition_verifier: Callable[..., frozenset[str]] = verify_bootstrap_composition
    operating_system_observer: Callable[..., list[dict[str, str]]] = observe_operating_systems
    substrate_observer: Callable[..., list[dict[str, str]]] = observe_gce_substrates


@dataclass(frozen=True)
class _RaesGceApplyRuntime:
    """Resolved non-optional bindings shared by RAES resource realization."""

    config: GCERangeCellConfig
    clients: GCEClients
    secret_ops: RaesGceSecretOps
    account_secret_ops: RaesAccountCredentialOps
    credential_installer: Callable[..., dict[str, str]]
    directory_secret_ops: RaesDirectorySecretOps
    directory_realizer: Callable[..., None]
    content_delivery_realizer: Callable[..., None]
    composition_verifier: Callable[..., frozenset[str]]
    operating_system_observer: Callable[..., list[dict[str, str]]]
    substrate_observer: Callable[..., list[dict[str, str]]]
    allocated_network_cidr: str | None


def _apply_runtime(options: RaesGceApplyOptions) -> _RaesGceApplyRuntime:
    """Resolve optional apply bindings exactly once."""
    return _RaesGceApplyRuntime(
        config=options.config or load_gce_range_cell_config(),
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
        allocated_network_cidr=options.allocated_network_cidr,
    )


def _assert_composition_targets_resolve(raes_plan: RaesPlan) -> None:
    """Fail closed if any content/feature/account placement targets an unknown node."""
    node_addresses = {node.address for node in raes_plan.nodes}
    placements = (
        [(c.target_address, "content", c.name) for c in raes_plan.content]
        + [(a.target_address, "account", a.username) for a in raes_plan.accounts]
        + [(f.target_address, "feature", f.name) for f in raes_plan.features]
    )
    for target, kind, name in placements:
        if target not in node_addresses:
            raise RaesGcePlanError(f"{kind} placement {name!r} targets node {target!r} not present in this plan")


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
    secret_ref, public_key = secret_ops.ensure_ssh(plan["range_id"], instance["uuid"])
    if existing is not None:
        return secret_ref, public_key, _host_public_key_from_instance(existing)

    host_private_key, host_public_key = generate_ssh_host_keypair()
    host_private_key_b64 = base64.b64encode(host_private_key.encode()).decode("ascii")
    operation = clients.instances.insert(
        project=plan["project_id"],
        zone=plan["zone"],
        instance_resource=instance_resource(
            plan,
            instance,
            config,
            ssh_public_key=public_key,
            host_private_key_b64=host_private_key_b64,
            host_public_key=host_public_key,
            composition_script=bootstrap_by_node.get(_node_address_of(instance), ""),
        ),
    )
    _wait_for_operation(plan, clients, operation, "zone")
    return secret_ref, public_key, host_public_key


def _provision_raes_resources(
    plan: RangeCellPlan,
    runtime: _RaesGceApplyRuntime,
    bootstrap_by_node: dict[str, str],
    accounts_by_node: dict[str, tuple[RaesPlanAccount, ...]],
    access_by_node: dict[str, tuple[RealizedAccessBinding, ...]],
) -> list[ResourceDict]:
    """Create the network, subnets, firewalls, and instances for an RAES range.

    Participant credential references are published (#1710) only *after* the
    authored account credential installed and verified on the guest, so a
    declared endpoint never appears with a credential that was never realized.
    """
    if plan["manage_network"]:
        _ensure_network(plan, runtime.clients)
    for subnet in plan["subnets"]:
        _ensure_subnetwork(plan, runtime.clients, subnet)
    _ensure_router_nat(plan, runtime.clients)
    for firewall in plan["firewalls"]:
        _ensure_firewall(plan, runtime.clients, firewall)
    instance_outputs: list[ResourceDict] = []
    for instance in plan["instances"]:
        _ensure_address(plan, runtime.clients, instance)
        ssh_secret_ref, ssh_public_key, host_public_key = _ensure_raes_instance(
            plan,
            runtime.clients,
            runtime.config,
            instance,
            runtime.secret_ops,
            bootstrap_by_node,
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
        instance_outputs.append(output)
    return instance_outputs


def _publish_participant_access(
    output: ResourceDict,
    access_bindings: tuple[RealizedAccessBinding, ...],
    account_secret_refs: dict[str, str],
) -> None:
    """Attach the participant credential reference for each declared channel.

    The reference is the one the account realizer already minted and verified for
    the authored account; the reserved provisioner-management SSH secret is never
    brokered. A declared channel whose account produced no verified reference is
    a failed realization, not a silently credential-less endpoint.
    """
    for binding in access_bindings:
        secret_ref = account_secret_refs.get(binding.account_address, "")
        if not secret_ref:
            raise RaesGcePlanError(
                "declared participant access has no verified account credential: "
                f"{binding.target_address}/{binding.channel}"
            )
        field = "ssh_key_secret_arn" if binding.channel == "ssh" else "rdp_password_secret_arn"
        output[field] = secret_ref


def _access_by_node(
    access_bindings: tuple[RealizedAccessBinding, ...],
) -> dict[str, tuple[RealizedAccessBinding, ...]]:
    """Group joined participant access by target node address."""
    grouped: dict[str, list[RealizedAccessBinding]] = {}
    for binding in access_bindings:
        grouped.setdefault(binding.target_address, []).append(binding)
    return {address: tuple(bindings) for address, bindings in grouped.items()}


def _bootstrap_by_node(raes_plan: RaesPlan) -> dict[str, str]:
    """Render non-empty local composition bootstrap scripts by node."""
    return {node.address: script for node in raes_plan.nodes if (script := node_bootstrap_script(node, raes_plan))}


def _accounts_by_node(raes_plan: RaesPlan) -> dict[str, tuple[RaesPlanAccount, ...]]:
    """Return local-only guest accounts grouped by target node."""
    return {
        node.address: tuple(
            account
            for account in raes_plan.accounts
            if account.target_address == node.address and account.domain_ref is None and account.domain_id is None
        )
        for node in raes_plan.nodes
    }


def _realize_directory(
    plan: RangeCellPlan,
    raes_plan: RaesPlan,
    instance_outputs: list[ResourceDict],
    runtime: _RaesGceApplyRuntime,
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
    runtime: _RaesGceApplyRuntime,
) -> frozenset[str]:
    """Deliver every source-backed content item when the plan carries one (#1564)."""
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


def _cleanup_failed_apply(
    request_uuid: str,
    range_id: int,
    raes_plan: RaesPlan,
    runtime: _RaesGceApplyRuntime,
) -> None:
    """Run reconstructive cleanup using the apply pass's resolved clients."""
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
            allocated_network_cidr=runtime.allocated_network_cidr,
        ),
    )


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
    egress_mode = resolved_options.egress_mode
    runtime = _apply_runtime(resolved_options)
    realized_access = join_participant_access(access_bindings or (), raes_plan)
    _assert_composition_targets_resolve(raes_plan)
    _assert_content_delivery_bindings_complete(raes_plan, delivery_bindings)
    assert_composition_is_verifiable(raes_plan)
    expected_composition = {
        *[item.address for item in raes_plan.content],
        *[account.address for account in raes_plan.accounts],
        *[feature.address for feature in raes_plan.features],
    }
    # Build and size-check the complete sanitized evidence shape before cloud mutation.
    snapshot_resources(raes_plan, expected_composition)
    plan = build_raes_range_cell_plan(
        request_uuid,
        range_id,
        raes_plan,
        resolve_image,
        RaesGcePlanOptions(
            config=runtime.config,
            access_bindings=realized_access,
            egress_policy=GceEgressPolicy(mode=egress_mode),
            allocated_network_cidr=runtime.allocated_network_cidr,
        ),
    )
    try:
        instance_outputs = _provision_raes_resources(
            plan,
            runtime,
            _bootstrap_by_node(raes_plan),
            _accounts_by_node(raes_plan),
            _access_by_node(realized_access),
        )
        verified = set(_realize_directory(plan, raes_plan, instance_outputs, runtime))
        verified.update(_realize_content_delivery(raes_plan, instance_outputs, delivery_bindings, runtime))
        verified.update(runtime.composition_verifier(raes_plan, instance_outputs))
        operating_systems = runtime.operating_system_observer(raes_plan, instance_outputs)
        validate_operating_systems(raes_plan, operating_systems)
        compute_substrates = runtime.substrate_observer(plan, runtime.clients)
        snapshot_resources(raes_plan, verified)
    except Exception:
        logger.exception("RAES GCE range-cell apply failed; attempting cleanup request_id=%s", request_uuid)
        _cleanup_failed_apply(request_uuid, range_id, raes_plan, runtime)
        raise
    return {
        "subnets": subnet_outputs(plan),
        "instances": instance_outputs,
        "composition_verified_addresses": sorted(verified),
        "operating_systems": operating_systems,
        "compute_substrates": compute_substrates,
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
