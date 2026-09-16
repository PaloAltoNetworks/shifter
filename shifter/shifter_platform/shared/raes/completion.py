"""Admit independently observed completion through the public RAE boundary."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from pydantic import TypeAdapter
from raes_contracts.bounded_domains import scalar_in_domain
from raes_contracts.contracts import RealizationEnvelopeIdentityModel
from raes_contracts.planning import PlannedResource, ProvisioningPlan, RuntimeDomain
from raes_contracts.realization_envelope import (
    BackendRealizationEnvelopeModel,
    realization_envelope_digest,
)
from raes_contracts.realization_observation import ObservedOperatingSystemIdentity
from raes_contracts.runtime_state import RealizationObservationDisclosure, RuntimeSnapshot, SnapshotEntry
from raes_contracts.vocabulary import ObservationStrength, RealizationVerificationScope
from raes_processor.planner import realization_authority_disclosure

from shared.raes.completion_evidence import plan_digest, validate_completion_evidence


def _authoritative_completion_plan(
    plan: ProvisioningPlan,
    serialized_plan: Mapping[str, Any] | None,
    value: Mapping[str, Any],
    generation_id: str | None,
) -> ProvisioningPlan:
    """Handle authoritative completion plan."""
    if serialized_plan is None:
        raise ValueError("completion requires the immutable serialized plan")
    authoritative_plan = load_serialized_plan(serialized_plan)
    if plan != authoritative_plan:
        raise ValueError("completion plan does not match the immutable serialized plan")
    if value["generation_id"] != (generation_id or authoritative_plan.operation_id):
        raise ValueError("completion belongs to another execution generation")
    if value["operation_id"] != authoritative_plan.operation_id or value["plan_digest"] != plan_digest(serialized_plan):
        raise ValueError("completion belongs to another plan or operation")
    return authoritative_plan


def _selected_carrier(plan: ProvisioningPlan, serialized_plan: Mapping[str, Any]) -> BackendRealizationEnvelopeModel:
    """Handle selected carrier."""
    try:
        carrier = BackendRealizationEnvelopeModel.model_validate(serialized_plan.get("backend_realization_envelope"))
    except Exception as exc:
        raise ValueError("completion has no valid selected realization configuration") from exc
    if realization_envelope_digest(carrier) != carrier.digest or plan.realization_envelope != carrier.identity:
        raise ValueError("completion uses an unqualified realization configuration")
    return carrier


def _verified_resources(plan: ProvisioningPlan, value: Mapping[str, Any]) -> dict[str, PlannedResource]:
    """Handle verified resources."""
    resources = {
        address: resource
        for address, resource in plan.resources.items()
        if resource.domain is RuntimeDomain.PROVISIONING
    }
    proved = {row["address"]: row for row in value["resources"]}
    required = {
        address: resource
        for address, resource in resources.items()
        if resource.resource_type != "domain-controller-placement"
    }
    if set(proved) != set(required):
        raise ValueError("completion resource coverage is incomplete")
    _validate_verified_resource_rows(required, proved)
    return resources


def _validate_verified_resource_rows(
    required: Mapping[str, PlannedResource], proved: Mapping[str, Mapping[str, Any]]
) -> None:
    """Validate each completion row against its planned resource and status."""
    for address, resource in required.items():
        expected_status = "provisioned" if resource.resource_type in {"node", "network"} else "verified"
        matches_plan = all(
            (
                proved[address]["resource_type"] == resource.resource_type,
                proved[address]["status"] == expected_status,
            )
        )
        if not matches_plan:
            raise ValueError("completion resource verification is invalid")


def load_serialized_plan(value: Mapping[str, Any]) -> ProvisioningPlan:
    """Reconstruct the public contract only inside shared.raes."""
    from shared.raes.contracts import RAES_PROVISIONING_PLAN_CONTRACT_VERSION

    if (
        value.get("kind") != "raes_provisioning_plan"
        or value.get("contract_version") != RAES_PROVISIONING_PLAN_CONTRACT_VERSION
        or value.get("raes_version") != "3.5.0"
    ):
        raise ValueError("unsupported completed plan version")
    adapter = TypeAdapter(ProvisioningPlan)
    adapter.rebuild(_types_namespace={"RealizationEnvelopeIdentityModel": RealizationEnvelopeIdentityModel})
    fields = {
        "resources",
        "operations",
        "realization_authority",
        "realization_envelope",
        "realization_constraints",
        "operation_id",
    }
    return adapter.validate_python({key: item for key, item in value.items() if key in fields})


def completed_snapshot(
    plan: ProvisioningPlan,
    evidence: Mapping[str, Any],
    *,
    baseline: RuntimeSnapshot | None = None,
    generation_id: str | None = None,
    serialized_plan: Mapping[str, Any] | None = None,
) -> RuntimeSnapshot:
    """Gate exact input, complete readback coverage and upstream realization semantics."""
    from shared.raes.manifest import create_shifter_backend_manifest

    value = validate_completion_evidence(dict(evidence))
    plan = _authoritative_completion_plan(plan, serialized_plan, value, generation_id)
    assert serialized_plan is not None
    carrier = _selected_carrier(plan, serialized_plan)
    manifest = create_shifter_backend_manifest(realization_envelope=carrier)
    resources = _verified_resources(plan, value)
    nodes = {address: resource for address, resource in resources.items() if resource.resource_type == "node"}
    observations = _node_observations(plan, nodes, value, carrier.identity)
    snapshot = deepcopy(baseline) if baseline is not None else RuntimeSnapshot()
    # Composition is projected only after its exact guest verification coverage
    # succeeded. OS/substrate are carried separately as actual observed values.
    snapshot.entries.update(
        {
            address: SnapshotEntry(
                address=address,
                domain=resource.domain,
                resource_type=resource.resource_type,
                payload=deepcopy(resource.payload),
                status="ready",
            )
            for address, resource in resources.items()
        }
    )
    snapshot.realization_envelope = carrier.identity
    snapshot.realization_observations = tuple(observations)
    diagnostics, provenance = realization_authority_disclosure(plan, snapshot, manifest=manifest)
    if any(item.is_error for item in diagnostics):
        raise ValueError("completed state does not satisfy the admitted realization contract")
    snapshot.realization_provenance = provenance
    return snapshot


def _node_observations(
    plan: ProvisioningPlan,
    nodes: Mapping[str, PlannedResource],
    value: Mapping[str, list[dict[str, Any]]],
    identity: RealizationEnvelopeIdentityModel,
) -> list[RealizationObservationDisclosure]:
    """Handle node observations."""
    counts = {address: resource.payload.get("count") for address, resource in nodes.items()}
    counts = {address: 1 if count is None else count for address, count in counts.items()}
    if any(type(count) is not int or not 1 <= count <= 512 for count in counts.values()):
        raise ValueError("invalid completed instance count")
    expected = {f"{address}#{index}" for address, count in counts.items() for index in range(count)}
    os_rows, _substrates = _verified_guest_rows(value, expected)
    result: list[RealizationObservationDisclosure] = []
    for address in nodes:
        result.extend(_node_observation_rows(plan, address, counts[address], os_rows, identity, len(result) + 1))
    return result


def _node_observation_rows(
    plan: ProvisioningPlan,
    address: str,
    count: int,
    os_rows: Mapping[str, Mapping[str, Any]],
    identity: RealizationEnvelopeIdentityModel,
    first_sequence: int,
) -> list[RealizationObservationDisclosure]:
    """Build the verified OS and optional substrate observations for one node."""
    operating_system = _observed_operating_system(address, count, os_rows)
    fields = {
        entry.requirement_kind: entry.field_path for entry in plan.realization_authority if entry.address == address
    }
    constraint = next((item for item in plan.realization_constraints if item.address == address), None)
    if (
        constraint is not None
        and constraint.value_domain is not None
        and not scalar_in_domain("virtual-machine", constraint.value_domain)
    ):
        raise ValueError("observed substrate does not satisfy the declared constraint")
    common = {
        "address": address,
        "domain": "runtime-realization",
        "verification_scope": RealizationVerificationScope.CONFIGURATION,
        "operation_id": plan.operation_id,
        "envelope_digest": identity.digest,
        "configuration_digest": identity.configuration_digest,
        "observer_version": "shifter-gce-readback-v1",
        "binding_verified": True,
    }
    rows = [
        RealizationObservationDisclosure(
            **common,
            field_path=fields.get("os-family", address),
            requirement_kind="operating-system",
            observation_strength=ObservationStrength.GUEST_OBSERVED,
            operating_system=operating_system,
            sequence=first_sequence,
        )
    ]
    if constraint is not None:
        rows.append(
            RealizationObservationDisclosure(
                **common,
                field_path=constraint.field_path,
                requirement_kind="compute-substrate",
                observation_strength=ObservationStrength.DAEMON_OBSERVED,
                observed_value="virtual-machine",
                sequence=first_sequence + 1,
            )
        )
    return rows


def _verified_guest_rows(
    value: Mapping[str, list[dict[str, Any]]], expected: set[str]
) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    """Handle verified guest rows."""
    os_rows = {row["instance_key"]: row for row in value["operating_systems"]}
    substrates = {row["instance_key"]: row["value"] for row in value["compute_substrates"]}
    if (
        set(os_rows) != expected
        or set(substrates) != expected
        or any(value != "virtual-machine" for value in substrates.values())
    ):
        raise ValueError("completion guest or substrate coverage is invalid")
    return os_rows, substrates


def _observed_operating_system(
    address: str, count: int, os_rows: Mapping[str, Mapping[str, Any]]
) -> ObservedOperatingSystemIdentity:
    """Handle observed operating system."""
    identities = {
        (
            os_rows[f"{address}#{index}"]["family"],
            os_rows[f"{address}#{index}"]["distribution"],
            os_rows[f"{address}#{index}"]["version"],
        )
        for index in range(count)
    }
    if len(identities) != 1:
        raise ValueError("replicas do not share one observed OS identity")
    return ObservedOperatingSystemIdentity(*next(iter(identities)))
