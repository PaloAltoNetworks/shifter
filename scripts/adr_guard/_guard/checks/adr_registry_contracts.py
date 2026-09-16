"""Executable ADR interface-contract dispatch and range/RAES validation."""

from __future__ import annotations

from .adr_registry_contract_support import (
    RANGE_SUBSTRATE_OPERATIONS,
    RANGE_SUBSTRATE_RESOURCES,
    interface_contract_kind_error,
    validate_closed_mapping,
    validate_contract_adapters,
    validate_contract_conformance,
    validate_contract_issue_references,
    validate_exact_string_members,
)
from .adr_registry_special_contracts import (
    validate_accessibility_enforcement_contract,
    validate_ctf_communications_contract,
    validate_dedicated_customer_authority_contract,
)


def validate_raes_plan_accessor_boundary_contract(
    contract: dict[str, object], adr_id: str
) -> list[str]:
    """Validate ADR-032's cross-process plan-accessor boundary."""
    expected_keys = {
        "kind",
        "transport",
        "ownership",
        "failure_policy",
        "naming",
        "compatibility",
        "delivery",
    }
    errors: list[str] = []
    if set(contract) != expected_keys:
        errors.append(
            f"{adr_id} interface_contract must contain exactly {sorted(expected_keys)}; got {sorted(contract)}"
        )
    prefix = f"{adr_id} interface_contract"
    errors.extend(
        validate_closed_mapping(
            contract.get("transport"),
            f"{prefix}.transport",
            fixed={
                "input": "serialized-raes-provisioning-plan",
                "owner": "shifter",
                "producer": "shared.raes",
                "consumer": "standalone-provisioner-plain-data-reader",
                "provisioner_imports_raes": False,
                "competing_projection": False,
            },
        )
    )
    errors.extend(
        validate_closed_mapping(
            contract.get("ownership"),
            f"{prefix}.ownership",
            fixed={
                "semantics": "raes",
                "producer_validation": "shared.raes",
                "serialization": "shared.raes.runtime_target",
                "cross_process_validation": "shifter.engine.provisioner.raes_plan",
                "payload_access": "standalone-versioned-reader",
                "backend_policy": "shifter-provider-realization",
            },
        )
    )
    errors.extend(
        validate_closed_mapping(
            contract.get("failure_policy"),
            f"{prefix}.failure_policy",
            fixed={
                "compatibility_selection": "before-payload-access",
                "missing_required": "reject-before-provider-mutation",
                "malformed_present": "reject-before-provider-mutation",
                "wrong_resource_or_domain": "reject-before-provider-mutation",
                "unsupported_version": "reject-before-provider-mutation",
                "unresolved_reference": "reject-before-provider-mutation",
                "missing_optional": "absent-only-when-contract-declares-optional",
            },
        )
    )
    errors.extend(
        validate_closed_mapping(
            contract.get("naming"),
            f"{prefix}.naming",
            fixed={
                "neutral_fallback": "full-canonical-planned-address",
                "provider_safe_conversion": "backend-naming-boundary",
                "stable_identity": "compiled-resource-address",
            },
        )
    )
    errors.extend(
        validate_closed_mapping(
            contract.get("compatibility"),
            f"{prefix}.compatibility",
            fixed={
                "typed_oracle": "released-public-plannedresource-accessors",
                "accessor_first_release": "raes-3.3.0",
                "wire_oracle": "public-compiler-conformance-and-exact-pin-serialized-fixtures",
                "private_backend_helpers": False,
                "exact_pin_required": True,
            },
        )
    )
    errors.extend(
        validate_closed_mapping(
            contract.get("delivery"),
            f"{prefix}.delivery",
            fixed={
                "decision_issue": 1937,
                "implementation_issue": 2082,
                "behavior_change_in_decision_issue": False,
            },
        )
    )
    return errors


def _validate_range_substrate_contract(
    contract: dict[str, object], adr_id: str
) -> list[str]:
    """Validate the generic range-substrate interface contract."""
    errors = validate_exact_string_members(
        contract.get("operations"),
        RANGE_SUBSTRATE_OPERATIONS,
        f"{adr_id} interface_contract.operations",
    )
    errors.extend(
        validate_exact_string_members(
            contract.get("resources"),
            RANGE_SUBSTRATE_RESOURCES,
            f"{adr_id} interface_contract.resources",
        )
    )
    errors.extend(validate_contract_conformance(contract, adr_id))
    errors.extend(validate_contract_adapters(contract, adr_id))
    errors.extend(validate_contract_issue_references(contract, adr_id))
    return errors


def validate_interface_contract(contract: object, adr_id: str) -> list[str]:
    """Validate executable invariants declared by a typed ADR interface contract."""
    if not isinstance(contract, dict):
        return [f"{adr_id} interface_contract must be an object"]
    kind_error = interface_contract_kind_error(contract, adr_id)
    if kind_error is not None:
        return [kind_error]
    typed_validators = {
        "raes-plan-accessor-boundary/v1": validate_raes_plan_accessor_boundary_contract,
        "ctf-communications/v1": validate_ctf_communications_contract,
        "dedicated-customer-authority/v1": validate_dedicated_customer_authority_contract,
        "accessibility-enforcement/v1": validate_accessibility_enforcement_contract,
    }
    validator = typed_validators.get(contract["kind"])
    return (
        validator(contract, adr_id)
        if validator is not None
        else _validate_range_substrate_contract(contract, adr_id)
    )
