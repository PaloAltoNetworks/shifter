"""Native EC2 realization of immutable RAES plans through generic guest seams."""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from botocore.client import BaseClient

from ec2_guest_instance import Ec2GuestPlan, ensure_ec2_guest, observe_ec2_guest
from ec2_guest_secrets import Ec2GuestSecrets
from ec2_network_apply import Ec2NetworkResources, ensure_ec2_network
from ec2_range_cleanup import Ec2CleanupScope, destroy_ec2_resources
from ec2_range_network import Ec2NetworkConfig, Ec2NetworkPlan, allocation_networks, plan_ec2_network
from executors.factory import GuestExecutionContext, build_guest_execution_context
from raes_access import RealizedAccessBinding, join_participant_access
from raes_account_credentials import delete_instance_account_credentials, install_instance_account_credentials
from raes_active_directory import delete_raes_directory_secrets, realize_raes_active_directory
from raes_composition_verification import assert_composition_is_verifiable, verify_bootstrap_composition
from raes_content_delivery import assert_content_delivery_bindings_complete, realize_raes_content_delivery
from raes_ec2_image import (
    Ec2ImageProfile,
    VerifiedEc2Image,
    assert_image_contract_matches_node,
    verify_ec2_image,
)
from raes_gcp_composition import node_bootstrap_script
from raes_guest_plan import (
    _access_by_node,
    _accounts_by_node,
    _assert_composition_targets_resolve,
    _publish_participant_access,
    assert_management_login_separate,
)
from raes_operating_system import observe_operating_systems, validate_operating_systems
from raes_participant_host_keys import observe_participant_host_keys
from raes_plan import RaesPlan, RaesPlanNode
from raes_preconfigured_host_readiness import verify_preconfigured_hosts
from raes_snapshot import snapshot_resources


@dataclass(frozen=True)
class RaesEc2ApplyOptions:
    """Deployment and operation coordinates, with injectable external boundaries."""

    config: Ec2NetworkConfig
    generation: UUID
    ec2: BaseClient
    secrets: Ec2GuestSecrets
    allocated_cidrs: dict[str, str]
    egress_mode: str = "deny-all"
    execution_builder: Callable[..., GuestExecutionContext] = build_guest_execution_context
    credential_installer: Callable[..., dict[str, str]] = install_instance_account_credentials
    directory_realizer: Callable[..., None] = realize_raes_active_directory
    content_delivery_realizer: Callable[..., None] = realize_raes_content_delivery
    composition_verifier: Callable[..., frozenset[str]] = verify_bootstrap_composition
    operating_system_observer: Callable[..., list[dict[str, str]]] = observe_operating_systems
    runtime_plugin: Callable[..., None] | None = None
    model_enrollment: Callable[..., None] | None = None
    host_readiness_verifier: Callable[..., None] = verify_preconfigured_hosts


def _scope(request_id: str, range_id: int, options: RaesEc2ApplyOptions) -> Ec2CleanupScope:
    """Recover original ownership coordinates for native cleanup."""
    return Ec2CleanupScope(
        options.config.environment,
        options.config.region,
        options.config.vpc_id,
        UUID(request_id),
        options.generation,
        range_id,
    )


def destroy_raes_ec2_range(
    request_id: str, range_id: int, plan: RaesPlan, options: RaesEc2ApplyOptions
) -> dict[str, Any]:
    """Remove owned resources before retiring their management/account identities."""
    result = destroy_ec2_resources(_scope(request_id, range_id, options), options.ec2)
    if result["outcome"] == "VERIFIED_ABSENT":
        delete_ec2_guest_credentials(range_id, plan, options.secrets)
    return result


def delete_ec2_guest_credentials(range_id: int, plan: RaesPlan, secrets: Ec2GuestSecrets) -> None:
    """Retire deterministic identities only after independent resource absence."""
    accounts = _accounts_by_node(plan)
    for node in plan.nodes:
        for index in range(node.count):
            key = f"{node.address}#{index}"
            secrets.delete(range_id, "host-ssh", (key,))
            secrets.delete(range_id, "host-identity", (key,))
            delete_instance_account_credentials(range_id, key, accounts[node.address], secrets.account_ops())
    delete_raes_directory_secrets(range_id, plan, secrets.directory_ops())


def _bootstrap(node: RaesPlanNode, plan: RaesPlan, output: dict[str, Any], options: RaesEc2ApplyOptions) -> None:
    """Run authored bootstrap through the trusted guest transport."""
    script = node_bootstrap_script(node, plan)
    if not script:
        return
    context = options.execution_builder(output, os_type=node.os_family)
    try:
        if not context.wait_for_ready(600):
            raise RuntimeError("EC2 management transport is unavailable")
        preamble = "$ErrorActionPreference = 'Stop'\n" if node.os_family == "windows" else "set -eu\n"
        result = context.executor.run_command(
            context.target, preamble + script, timeout_seconds=600, document_name=context.document_name
        )
        if not result.success or result.exit_code != 0:
            raise RuntimeError("EC2 guest composition bootstrap failed")
    finally:
        context.close()


def _guests(
    network: Ec2NetworkPlan,
    plan: RaesPlan,
    images: dict[str, VerifiedEc2Image],
    access: tuple[RealizedAccessBinding, ...],
    options: RaesEc2ApplyOptions,
) -> tuple[list[dict[str, Any]], list[Ec2GuestPlan], Ec2NetworkResources]:
    """Realize admitted guests and publish their management transport identities."""
    resources = ensure_ec2_network(network, options.ec2)
    nodes = {node.address: node for node in plan.nodes}
    accounts = _accounts_by_node(plan)
    bindings = _access_by_node(access)
    # The realized member projection requires each guest's authored subnet name
    # (#1710); map the placement's network address back to the authored name so
    # the terminal-ready result parses (GCP sets this from its subnet outputs).
    subnet_names = {network_intent.address: network_intent.name for network_intent in allocation_networks(plan)}
    outputs, guests = [], []
    for placement in network.guests:
        node = nodes[placement.node_address]
        guest = Ec2GuestPlan(
            environment=network.config.environment,
            request_id=network.request_id,
            generation=network.generation,
            range_id=network.range_id,
            instance_key=placement.instance_key,
            name=node.name,
            os_family=node.os_family or "linux",
            subnet_id=resources.subnets[placement.subnet_address],
            private_ip=placement.private_ip,
            security_group_id=resources.groups[node.address],
            image=images[node.address],
        )
        output = ensure_ec2_guest(guest, options.ec2, options.secrets)
        _bootstrap(node, plan, output, options)
        refs = (
            options.credential_installer(
                range_id=network.range_id,
                instance_key=placement.instance_key,
                platform=node.os_family,
                instance_output=output,
                accounts=accounts[node.address],
                secret_ops=options.secrets.account_ops(),
            )
            if accounts[node.address]
            else {}
        )
        node_access = bindings.get(node.address, ())
        _publish_participant_access(output, node_access, refs)
        output["participant_access_channels"] = [binding.channel for binding in node_access]
        output["participant_access_usernames"] = {binding.channel: binding.username for binding in node_access}
        output["subnet_name"] = subnet_names.get(placement.subnet_address, "")
        outputs.append(output)
        guests.append(guest)
    return outputs, guests, resources


def _verify(
    plan: RaesPlan,
    outputs: list[dict[str, Any]],
    guests: list[Ec2GuestPlan],
    options: RaesEc2ApplyOptions,
    delivery_bindings: list[dict[str, Any]] | None,
    range_id: int,
) -> dict[str, Any]:
    """Verify operating systems, participant access and compiled composition."""
    verified: set[str] = set()
    if plan.domains:
        options.directory_realizer(
            range_id=range_id, raes_plan=plan, instance_outputs=outputs, secret_ops=options.secrets.directory_ops()
        )
        verified.update(account.address for account in plan.accounts if account.domain_ref or account.domain_id)
    if any(item.source_name for item in plan.content) or plan.features:
        options.content_delivery_realizer(raes_plan=plan, instance_outputs=outputs, delivery_bindings=delivery_bindings)
        verified.update(item.address for item in plan.content if item.source_name)
        verified.update(feature.address for feature in plan.features)
    if options.model_enrollment:
        options.model_enrollment(plan, outputs)
    if options.runtime_plugin:
        options.runtime_plugin(plan, outputs)
    # Preconfigured hosts become ready only once the runtime plugin has brought
    # the participant container up; the canary then gates participant access.
    options.host_readiness_verifier(outputs, execution_builder=options.execution_builder)
    observe_participant_host_keys(outputs, execution_builder=options.execution_builder)
    verified.update(options.composition_verifier(plan, outputs))
    operating_systems = options.operating_system_observer(plan, outputs)
    validate_operating_systems(plan, operating_systems)
    substrates = []
    for guest, output in zip(guests, outputs, strict=True):
        observe_ec2_guest(guest, options.ec2, output["instance_id"])
        substrates.append({"instance_key": guest.instance_key, "value": "virtual-machine"})
    snapshot_resources(plan, verified)
    return {
        "instances": outputs,
        "composition_verified_addresses": sorted(verified),
        "operating_systems": operating_systems,
        "compute_substrates": substrates,
    }


def apply_raes_ec2_range(
    request_id: str,
    range_id: int,
    plan: RaesPlan,
    resolve_image: Callable[[RaesPlanNode], Ec2ImageProfile],
    options: RaesEc2ApplyOptions,
    delivery_bindings: list[dict[str, Any]] | None = None,
    access_bindings: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Preflight full intent; only publish success after independent readback."""
    scope = _scope(request_id, range_id, options)
    access = join_participant_access(access_bindings or (), plan)
    _assert_composition_targets_resolve(plan)
    assert_content_delivery_bindings_complete(plan, delivery_bindings)
    assert_composition_is_verifiable(plan)
    snapshot_resources(
        plan,
        {
            *[item.address for item in plan.content],
            *[item.address for item in plan.accounts],
            *[item.address for item in plan.features],
        },
    )
    images = {node.address: verify_ec2_image(node, resolve_image(node), options.ec2) for node in plan.nodes}
    for node in plan.nodes:
        assert_image_contract_matches_node(node, images[node.address])
        username = images[node.address].management_ssh_username or (
            "Administrator" if node.os_family == "windows" else "raes"
        )
        assert_management_login_separate(plan, node.address, username)
    network = plan_ec2_network(
        plan,
        config=options.config,
        scope=scope,
        allocated_cidrs=options.allocated_cidrs,
        images=images,
        participant_channels={
            address: tuple(item.channel for item in bindings) for address, bindings in _access_by_node(access).items()
        },
        egress_mode=options.egress_mode,
    )
    try:
        outputs, guests, resources = _guests(network, plan, images, access, options)
        result = _verify(plan, outputs, guests, options, delivery_bindings, range_id)
        result["subnets"] = {
            subnet.address: {
                "uuid": subnet.address,
                "subnet_cidr": subnet.cidr,
                "subnet_id": resources.subnets[subnet.address],
            }
            for subnet in network.subnets
        }
        return result
    except Exception:
        # Compensate the failed launch, but never let a teardown failure mask the
        # original provision error (a `raise ... from None` in the cleanup path
        # otherwise suppresses it). The cleanup failure still surfaces on the
        # explicit destroy path; the original error is what must propagate here.
        with contextlib.suppress(Exception):
            destroy_raes_ec2_range(request_id, range_id, plan, options)
        raise
