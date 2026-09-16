"""Closed contracts for platform-owned GCP VM range-cell lifecycle operations.

Scenario deployment content crosses this boundary only as an existing persisted
artifact.  The platform contract owns admission, network bindings, lifecycle,
membership, and logical access; it deliberately has no role, operating-system,
image, or scenario-topology taxonomy.

This module stays dependency-light because the standalone provisioner image
imports it without loading Django or the platform schema graph.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
from copy import deepcopy
from typing import Any

from shared.exceptions import ValidationError as RangeCellContractError
from shared.persisted_envelope import PAYLOAD_KEY, SPEC_SCHEMA_KEY, SPEC_VERSION, SPEC_VERSION_KEY
from shared.remote_access import parse_openvpn_capability

CONTRACT_KEY = "shifter.gcp-vm-range-cell"
CONTRACT_VERSION = "1"
CAPABILITY = "live-fire-vm-range-cell"
PROVIDER = "gcp"
BACKEND = "gce"

_DIGEST_KEY = "digest"
_PERSISTED_ENVELOPE_FIELD = "persisted scenario envelope"
_ARTIFACT_KEYS = frozenset({SPEC_SCHEMA_KEY, SPEC_VERSION_KEY, PAYLOAD_KEY, _DIGEST_KEY})
_ENVELOPE_KEYS = frozenset({SPEC_SCHEMA_KEY, SPEC_VERSION_KEY, PAYLOAD_KEY})
_REQUEST_KEYS = frozenset(
    {
        "contract",
        "contract_version",
        "capability",
        "operation",
        "admission",
        "scenario_artifact",
        "network_bindings",
        "access_declarations",
        "remote_access",
    }
)
_RESULT_KEYS = frozenset({"contract", "contract_version", "capability", "operation", "cell", "members", "access"})

# Closed range egress vocabulary, mirrored inline from
# ``installation.range_egress.RangeEgressMode`` so the provisioner bundle need not
# load the installation/pydantic machinery (same pattern as
# ``shared.raes.operation_input``). ``egress_mode`` is an optional operation field
# for rolling-deploy compatibility (PLAT-238); absence resolves to ``status-quo``.
_VALID_EGRESS_MODES = frozenset({"status-quo", "deny-all", "allowlist", "none"})
_DEFAULT_EGRESS_MODE = "status-quo"
_LIFECYCLE_STATES = frozenset({"pending", "provisioning", "ready", "destroying", "destroyed", "failed"})
_ACCESS_CHANNELS = frozenset({"ssh", "rdp"})
_MAX_NETWORK_BINDING_ADDRESSES = 1 << 16

ContractDict = dict[str, Any]


def _require_dict(value: object, field: str) -> ContractDict:
    """Return a mapping or raise a field-specific contract error."""
    if not isinstance(value, dict):
        raise RangeCellContractError(f"{field} must be an object")
    return value


def _require_list(value: object, field: str) -> list[object]:
    """Return a list or raise a field-specific contract error."""
    if not isinstance(value, list):
        raise RangeCellContractError(f"{field} must be a list")
    return value


def _require_exact_keys(value: ContractDict, expected: frozenset[str], field: str) -> None:
    """Require a closed object with exactly the declared field names."""
    actual = frozenset(value)
    unexpected = sorted(actual - expected)
    if unexpected:
        raise RangeCellContractError(f"{field} has unexpected field(s): {', '.join(unexpected)}")
    missing = sorted(expected - actual)
    if missing:
        raise RangeCellContractError(f"{field} is missing field(s): {', '.join(missing)}")


def _require_text(value: object, field: str) -> str:
    """Return normalized non-empty text or raise a contract error."""
    if not isinstance(value, str) or not value.strip():
        raise RangeCellContractError(f"{field} must be a non-empty string")
    return value.strip()


def _require_range_id(value: object) -> int:
    """Return a positive range identifier, excluding booleans."""
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise RangeCellContractError("operation.range_id must be a positive integer")
    return value


def _canonical_json(value: object, field: str) -> bytes:
    """Serialize JSON data deterministically for digest calculation."""
    try:
        serialized = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise RangeCellContractError(f"{field} must be canonical JSON data") from exc
    return serialized.encode()


def _artifact_digest(envelope: ContractDict) -> str:
    """Return the versioned SHA-256 digest for a canonical envelope."""
    return f"sha256:{hashlib.sha256(_canonical_json(envelope, 'scenario artifact')).hexdigest()}"


def build_scenario_artifact(envelope: dict[str, object], *, expected_schema: str = "range_spec") -> ContractDict:
    """Canonically validate and bind a persisted scenario envelope to a digest.

    The full owning schema is imported only by this producer-side builder.  A
    standalone lifecycle consumer uses :func:`validate_scenario_artifact`, which
    remains dependency-light and verifies the already-minted digest without
    importing the scenario schema graph.
    """
    source = deepcopy(_require_dict(envelope, _PERSISTED_ENVELOPE_FIELD))
    _require_exact_keys(source, _ENVELOPE_KEYS, _PERSISTED_ENVELOPE_FIELD)
    schema = _require_text(source[SPEC_SCHEMA_KEY], f"{_PERSISTED_ENVELOPE_FIELD}.{SPEC_SCHEMA_KEY}")
    if schema != expected_schema:
        raise RangeCellContractError(f"spec_schema mismatch: expected {expected_schema}, got {schema}")
    version = _require_text(source[SPEC_VERSION_KEY], f"{_PERSISTED_ENVELOPE_FIELD}.{SPEC_VERSION_KEY}")
    if version != SPEC_VERSION:
        raise RangeCellContractError(f"Unsupported spec_version: {version}")
    _require_dict(source[PAYLOAD_KEY], f"{_PERSISTED_ENVELOPE_FIELD}.{PAYLOAD_KEY}")
    try:
        from shared.schemas.persistence import validate_persisted_spec

        validated = validate_persisted_spec(source, expected_schema)
    except (LookupError, TypeError, ValueError) as exc:
        raise RangeCellContractError("persisted scenario envelope failed canonical validation") from exc
    # Digest the owning contract's normalized JSON representation.  This drops
    # fields ignored by legacy Pydantic defaults instead of blessing an
    # unvalidated extension bag as scenario intent.
    source[PAYLOAD_KEY] = validated.model_dump(mode="json")
    _canonical_json(source, _PERSISTED_ENVELOPE_FIELD)
    return source | {_DIGEST_KEY: _artifact_digest(source)}


def validate_scenario_artifact(artifact: object, *, expected_schema: str = "range_spec") -> ContractDict:
    """Return a defensive copy of a valid digest-bound scenario artifact."""
    candidate = deepcopy(_require_dict(artifact, "scenario_artifact"))
    _require_exact_keys(candidate, _ARTIFACT_KEYS, "scenario_artifact")
    schema = _require_text(candidate[SPEC_SCHEMA_KEY], f"scenario_artifact.{SPEC_SCHEMA_KEY}")
    if schema != expected_schema:
        raise RangeCellContractError(f"spec_schema mismatch: expected {expected_schema}, got {schema}")
    version = _require_text(candidate[SPEC_VERSION_KEY], f"scenario_artifact.{SPEC_VERSION_KEY}")
    if version != SPEC_VERSION:
        raise RangeCellContractError(f"Unsupported spec_version: {version}")
    _require_dict(candidate[PAYLOAD_KEY], f"scenario_artifact.{PAYLOAD_KEY}")
    supplied_digest = _require_text(candidate[_DIGEST_KEY], f"scenario_artifact.{_DIGEST_KEY}")
    envelope = {key: candidate[key] for key in (SPEC_SCHEMA_KEY, SPEC_VERSION_KEY, PAYLOAD_KEY)}
    expected_digest = _artifact_digest(envelope)
    if not hmac.compare_digest(supplied_digest, expected_digest):
        raise RangeCellContractError("scenario artifact digest mismatch")
    return candidate


def _validate_operation(value: object) -> ContractDict:
    """Validate and normalize operation correlation fields.

    ``egress_mode`` is an optional field (PLAT-238): a newer producer always emits
    the pinned effective posture, while an older request without it resolves to the
    compatibility ``status-quo`` (never a silent weakening, because ``none`` is
    always explicit). A present but unrecognized value fails closed at the wire.
    """
    operation = deepcopy(_require_dict(value, "operation"))
    egress_mode = operation.pop("egress_mode", _DEFAULT_EGRESS_MODE)
    _require_exact_keys(operation, frozenset({"request_id", "range_id"}), "operation")
    operation["request_id"] = _require_text(operation["request_id"], "operation.request_id")
    operation["range_id"] = _require_range_id(operation["range_id"])
    if not isinstance(egress_mode, str) or egress_mode not in _VALID_EGRESS_MODES:
        raise RangeCellContractError("operation.egress_mode is not a closed egress vocabulary value")
    operation["egress_mode"] = egress_mode
    return operation


def _validate_admission(value: object) -> ContractDict:
    """Validate the closed provider/backend admission selector."""
    admission = deepcopy(_require_dict(value, "admission"))
    _require_exact_keys(admission, frozenset({"provider", "backend"}), "admission")
    provider = _require_text(admission["provider"], "admission.provider")
    backend = _require_text(admission["backend"], "admission.backend")
    if provider != PROVIDER:
        raise RangeCellContractError(f"provider must be {PROVIDER!r}, got {provider!r}")
    if backend != BACKEND:
        raise RangeCellContractError(f"backend must be {BACKEND!r}, got {backend!r}")
    return admission


def _validate_network_bindings(value: object) -> list[ContractDict]:
    """Validate unique authored-subnet to IPv4 network bindings."""
    bindings: list[ContractDict] = []
    seen_refs: set[str] = set()
    for index, raw_binding in enumerate(_require_list(value, "network_bindings")):
        binding = deepcopy(_require_dict(raw_binding, f"network_bindings[{index}]"))
        _require_exact_keys(binding, frozenset({"subnet_ref", "cidr"}), f"network_bindings[{index}]")
        subnet_ref = _require_text(binding["subnet_ref"], f"network_bindings[{index}].subnet_ref")
        if subnet_ref in seen_refs:
            raise RangeCellContractError(f"duplicate subnet_ref in network_bindings: {subnet_ref}")
        seen_refs.add(subnet_ref)
        cidr = _require_text(binding["cidr"], f"network_bindings[{index}].cidr")
        try:
            network = ipaddress.ip_network(cidr, strict=True)
        except ValueError as exc:
            raise RangeCellContractError(f"network_bindings[{index}].cidr is not a network") from exc
        if not isinstance(network, ipaddress.IPv4Network):
            raise RangeCellContractError(f"network_bindings[{index}].cidr must be IPv4")
        if network.num_addresses > _MAX_NETWORK_BINDING_ADDRESSES:
            raise RangeCellContractError(f"network_bindings[{index}].cidr is larger than /16")
        for existing in bindings:
            existing_network = ipaddress.ip_network(existing["cidr"])
            if network.overlaps(existing_network):
                raise RangeCellContractError(
                    f"network_bindings[{index}].cidr overlaps network binding for {existing['subnet_ref']}"
                )
        bindings.append({"subnet_ref": subnet_ref, "cidr": str(network)})
    return bindings


def _validate_access_declarations(value: object) -> list[ContractDict]:
    """Validate scenario-authorized participant target/channel pairs."""
    declarations: list[ContractDict] = []
    seen: set[tuple[str, str]] = set()
    expected = frozenset({"target_ref", "channel"})
    for index, raw_declaration in enumerate(_require_list(value, "access_declarations")):
        declaration = deepcopy(_require_dict(raw_declaration, f"access_declarations[{index}]"))
        _require_exact_keys(declaration, expected, f"access_declarations[{index}]")
        target_ref = _require_text(declaration["target_ref"], f"access_declarations[{index}].target_ref")
        channel = _require_text(declaration["channel"], f"access_declarations[{index}].channel")
        if channel not in _ACCESS_CHANNELS:
            raise RangeCellContractError(f"access_declarations[{index}].channel is unsupported: {channel}")
        key = (target_ref, channel)
        if key in seen:
            raise RangeCellContractError(f"duplicate access declaration: {target_ref}/{channel}")
        seen.add(key)
        declarations.append({"target_ref": target_ref, "channel": channel})
    return declarations


def build_gcp_vm_range_cell_request(
    *,
    request_id: str,
    range_id: int,
    scenario_artifact: dict[str, object],
    network_bindings: list[dict[str, object]],
    access_declarations: list[dict[str, object]] | None = None,
    remote_access: dict[str, object] | None = None,
    egress_mode: str = _DEFAULT_EGRESS_MODE,
) -> ContractDict:
    """Build the only request shape accepted by the GCP VM-cell backend.

    ``egress_mode`` is the effective range egress posture pinned on the range
    (PLAT-238); it rides in the operation block so the cyberscript GCE cell plan
    realizes it (firewall + range-owned NAT) exactly like the RAES path.
    """
    return validate_gcp_vm_range_cell_request(
        {
            "contract": CONTRACT_KEY,
            "contract_version": CONTRACT_VERSION,
            "capability": CAPABILITY,
            "operation": {"request_id": request_id, "range_id": range_id, "egress_mode": egress_mode},
            "admission": {"provider": PROVIDER, "backend": BACKEND},
            "scenario_artifact": scenario_artifact,
            "network_bindings": network_bindings,
            "access_declarations": access_declarations or [],
            "remote_access": remote_access,
        }
    )


def validate_gcp_vm_range_cell_request(value: object) -> ContractDict:
    """Validate and normalize a GCP VM range-cell request without side effects."""
    request = deepcopy(_require_dict(value, "range-cell request"))
    _require_exact_keys(request, _REQUEST_KEYS, "range-cell request")
    if request["contract"] != CONTRACT_KEY:
        raise RangeCellContractError(f"contract must be {CONTRACT_KEY!r}")
    if request["contract_version"] != CONTRACT_VERSION:
        raise RangeCellContractError(f"Unsupported contract_version: {request['contract_version']}")
    if request["capability"] != CAPABILITY:
        raise RangeCellContractError(f"capability must be {CAPABILITY!r}")
    request["operation"] = _validate_operation(request["operation"])
    request["admission"] = _validate_admission(request["admission"])
    request["scenario_artifact"] = validate_scenario_artifact(request["scenario_artifact"])
    request["network_bindings"] = _validate_network_bindings(request["network_bindings"])
    request["access_declarations"] = _validate_access_declarations(request["access_declarations"])
    request["remote_access"] = (
        parse_openvpn_capability(request["remote_access"]).as_dict() if request["remote_access"] is not None else None
    )
    return request


def is_gcp_vm_range_cell_request(value: object) -> bool:
    """Return whether ``value`` declares the GCP VM range-cell contract."""
    return isinstance(value, dict) and value.get("contract") == CONTRACT_KEY


def _validate_cell(value: object) -> ContractDict:
    """Validate lifecycle state and membership scope for a range cell."""
    cell = deepcopy(_require_dict(value, "cell"))
    expected = frozenset({"cell_id", "provider", "backend", "lifecycle_state", "subnet_refs"})
    _require_exact_keys(cell, expected, "cell")
    cell["cell_id"] = _require_text(cell["cell_id"], "cell.cell_id")
    _validate_admission({"provider": cell["provider"], "backend": cell["backend"]})
    state = _require_text(cell["lifecycle_state"], "cell.lifecycle_state")
    if state not in _LIFECYCLE_STATES:
        raise RangeCellContractError(f"cell.lifecycle_state is unsupported: {state}")
    subnet_refs = [
        _require_text(item, "cell.subnet_refs[]") for item in _require_list(cell["subnet_refs"], "cell.subnet_refs")
    ]
    if len(subnet_refs) != len(set(subnet_refs)):
        raise RangeCellContractError("cell.subnet_refs contains duplicates")
    cell["subnet_refs"] = subnet_refs
    return cell


def _validate_members(value: object, subnet_refs: set[str]) -> list[ContractDict]:
    """Validate realized members against the cell's authored subnet set."""
    members: list[ContractDict] = []
    authored_refs: set[str] = set()
    resource_ids: set[str] = set()
    expected = frozenset({"authored_ref", "resource_id", "subnet_ref", "lifecycle_state"})
    for index, raw_member in enumerate(_require_list(value, "members")):
        member = deepcopy(_require_dict(raw_member, f"members[{index}]"))
        _require_exact_keys(member, expected, f"members[{index}]")
        authored_ref = _require_text(member["authored_ref"], f"members[{index}].authored_ref")
        resource_id = _require_text(member["resource_id"], f"members[{index}].resource_id")
        subnet_ref = _require_text(member["subnet_ref"], f"members[{index}].subnet_ref")
        state = _require_text(member["lifecycle_state"], f"members[{index}].lifecycle_state")
        if authored_ref in authored_refs:
            raise RangeCellContractError(f"duplicate authored_ref in members: {authored_ref}")
        if resource_id in resource_ids:
            raise RangeCellContractError(f"duplicate resource_id in members: {resource_id}")
        if subnet_ref not in subnet_refs:
            raise RangeCellContractError(f"foreign subnet_ref in members: {subnet_ref}")
        if state not in _LIFECYCLE_STATES:
            raise RangeCellContractError(f"members[{index}].lifecycle_state is unsupported: {state}")
        authored_refs.add(authored_ref)
        resource_ids.add(resource_id)
        members.append(
            {
                "authored_ref": authored_ref,
                "resource_id": resource_id,
                "subnet_ref": subnet_ref,
                "lifecycle_state": state,
            }
        )
    return members


def _validate_access(value: object, member_refs: set[str]) -> list[ContractDict]:
    """Validate resolved participant access for realized cell members."""
    access_records: list[ContractDict] = []
    expected = frozenset({"target_ref", "channel", "address", "port", "credential_ref"})
    seen: set[tuple[str, str]] = set()
    for index, raw_access in enumerate(_require_list(value, "access")):
        access = deepcopy(_require_dict(raw_access, f"access[{index}]"))
        _require_exact_keys(access, expected, f"access[{index}]")
        target_ref = _require_text(access["target_ref"], f"access[{index}].target_ref")
        if target_ref not in member_refs:
            raise RangeCellContractError(f"dangling target_ref in access: {target_ref}")
        channel = _require_text(access["channel"], f"access[{index}].channel")
        if channel not in _ACCESS_CHANNELS:
            raise RangeCellContractError(f"access[{index}].channel is unsupported: {channel}")
        key = (target_ref, channel)
        if key in seen:
            raise RangeCellContractError(f"duplicate access target/channel: {target_ref}/{channel}")
        seen.add(key)
        address = _require_text(access["address"], f"access[{index}].address")
        try:
            ipaddress.ip_address(address)
        except ValueError as exc:
            raise RangeCellContractError(f"access[{index}].address must be a resolved IP address") from exc
        port = access["port"]
        if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
            raise RangeCellContractError(f"access[{index}].port must be between 1 and 65535")
        credential_ref = _require_text(access["credential_ref"], f"access[{index}].credential_ref")
        if not (credential_ref.startswith("projects/") and "/secrets/" in credential_ref):
            raise RangeCellContractError(f"access[{index}].credential_ref must be a GCP Secret Manager reference")
        access_records.append(
            {
                "target_ref": target_ref,
                "channel": channel,
                "address": address,
                "port": port,
                "credential_ref": credential_ref,
            }
        )
    return access_records


def build_gcp_vm_range_cell_result(
    request: dict[str, object],
    *,
    cell_id: str,
    members: list[dict[str, object]],
    access: list[dict[str, object]],
    lifecycle_state: str = "ready",
) -> ContractDict:
    """Build a closed cell result without scenario semantics or secret values."""
    validated_request = validate_gcp_vm_range_cell_request(request)
    subnet_refs = [binding["subnet_ref"] for binding in validated_request["network_bindings"]]
    result = validate_gcp_vm_range_cell_result(
        {
            "contract": CONTRACT_KEY,
            "contract_version": CONTRACT_VERSION,
            "capability": CAPABILITY,
            "operation": validated_request["operation"],
            "cell": {
                "cell_id": cell_id,
                "provider": PROVIDER,
                "backend": BACKEND,
                "lifecycle_state": lifecycle_state,
                "subnet_refs": subnet_refs,
            },
            "members": members,
            "access": access,
        }
    )
    declared = {
        (declaration["target_ref"], declaration["channel"]) for declaration in validated_request["access_declarations"]
    }
    emitted = {(record["target_ref"], record["channel"]) for record in result["access"]}
    if emitted != declared:
        raise RangeCellContractError("range-cell result access does not match declared participant access")
    return result


def validate_gcp_vm_range_cell_result(value: object) -> ContractDict:
    """Validate and normalize range-cell lifecycle, membership, and access output."""
    result = deepcopy(_require_dict(value, "range-cell result"))
    _require_exact_keys(result, _RESULT_KEYS, "range-cell result")
    if result["contract"] != CONTRACT_KEY:
        raise RangeCellContractError(f"contract must be {CONTRACT_KEY!r}")
    if result["contract_version"] != CONTRACT_VERSION:
        raise RangeCellContractError(f"Unsupported contract_version: {result['contract_version']}")
    if result["capability"] != CAPABILITY:
        raise RangeCellContractError(f"capability must be {CAPABILITY!r}")
    result["operation"] = _validate_operation(result["operation"])
    result["cell"] = _validate_cell(result["cell"])
    result["members"] = _validate_members(result["members"], set(result["cell"]["subnet_refs"]))
    member_refs = {member["authored_ref"] for member in result["members"]}
    result["access"] = _validate_access(result["access"], member_refs)
    return result


__all__ = [
    "BACKEND",
    "CAPABILITY",
    "CONTRACT_KEY",
    "CONTRACT_VERSION",
    "PROVIDER",
    "RangeCellContractError",
    "build_gcp_vm_range_cell_request",
    "build_gcp_vm_range_cell_result",
    "build_scenario_artifact",
    "is_gcp_vm_range_cell_request",
    "validate_gcp_vm_range_cell_request",
    "validate_gcp_vm_range_cell_result",
    "validate_scenario_artifact",
]
