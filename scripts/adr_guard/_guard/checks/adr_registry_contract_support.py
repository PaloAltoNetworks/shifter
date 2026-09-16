"""Shared validators for executable ADR interface contracts."""

from __future__ import annotations

REQUIRED_INTERFACE_CONTRACTS = {
    "ADR-032": "raes-plan-accessor-boundary/v1",
    "ADR-039": "range-substrate/v1",
    "ADR-051": "ctf-communications/v1",
    "ADR-054": "dedicated-customer-authority/v1",
    "ADR-055": "accessibility-enforcement/v1",
}
RANGE_SUBSTRATE_OPERATIONS = frozenset({"provision", "destroy", "pause", "resume"})
RANGE_SUBSTRATE_RESOURCES = frozenset({"network", "instance", "ngfw", "remote-access"})
RANGE_SUBSTRATE_INITIAL_ADAPTERS = frozenset({"aws-terraform", "gcp-gce", "gcp-gdc"})
RANGE_SUBSTRATE_DEFERRED_ADAPTERS = frozenset({"azure"})
RANGE_SUBSTRATE_ISSUE_REFERENCES = frozenset({"283", "478", "265", "277"})


def validate_exact_string_members(
    value: object, expected: frozenset[str], field: str
) -> list[str]:
    """Validate one closed interface-contract string collection."""
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        return [f"{field} must be a list of strings"]
    actual = set(value)
    if len(value) != len(actual):
        message = f"{field} must not contain duplicates"
    elif actual != expected:
        message = (
            f"{field} must contain exactly {sorted(expected)}; got {sorted(actual)}"
        )
    else:
        return []
    return [message]


def interface_contract_kind_error(
    contract: dict[str, object], adr_id: str
) -> str | None:
    """Return the contract kind error, or None when the declared kind is supported."""
    expected_kind = REQUIRED_INTERFACE_CONTRACTS.get(adr_id)
    kind = contract.get("kind")
    if expected_kind is not None and kind != expected_kind:
        return f"{adr_id} interface_contract kind must be {expected_kind!r}"
    if kind not in frozenset(REQUIRED_INTERFACE_CONTRACTS.values()):
        return f"{adr_id} interface_contract has unsupported kind {kind!r}"
    return None


def validate_contract_conformance(
    contract: dict[str, object], adr_id: str
) -> list[str]:
    """Validate the conformance obligations declared by an interface contract."""
    conformance = contract.get("conformance")
    if not isinstance(conformance, dict):
        return [f"{adr_id} interface_contract.conformance must be an object"]
    return [
        f"{adr_id} interface_contract.conformance.{obligation} must be true"
        for obligation in ("shared_black_box_suite", "real_provider_promotion_evidence")
        if conformance.get(obligation) is not True
    ]


def validate_contract_adapters(contract: dict[str, object], adr_id: str) -> list[str]:
    """Validate the initial and deferred adapter sets declared by a contract."""
    adapters = contract.get("adapters")
    if not isinstance(adapters, dict):
        return [f"{adr_id} interface_contract.adapters must be an object"]
    errors = validate_exact_string_members(
        adapters.get("initial"),
        RANGE_SUBSTRATE_INITIAL_ADAPTERS,
        f"{adr_id} interface_contract.adapters.initial",
    )
    errors.extend(
        validate_exact_string_members(
            adapters.get("deferred"),
            RANGE_SUBSTRATE_DEFERRED_ADAPTERS,
            f"{adr_id} interface_contract.adapters.deferred",
        )
    )
    return errors


def _is_declared_operation_list(operations: object) -> bool:
    """True for a non-empty, duplicate-free list of declared substrate operations."""
    if not isinstance(operations, list) or not operations:
        return False
    if not all(isinstance(operation, str) for operation in operations):
        return False
    return set(operations).issubset(RANGE_SUBSTRATE_OPERATIONS) and len(
        operations
    ) == len(set(operations))


def _issue_reference_mapping_is_valid(mapping: dict[str, object]) -> bool:
    """True when a mapping is out-of-scope or maps exclusively to declared operations."""
    mapping_fields = set(mapping)
    if mapping_fields == {"disposition"} and mapping["disposition"] == "out-of-scope":
        return True
    return mapping_fields == {"operations"} and _is_declared_operation_list(
        mapping.get("operations")
    )


def _issue_reference_error(
    mapping: object, reference: object, adr_id: str
) -> str | None:
    """Return the error for one issue-reference mapping, or None when it is valid."""
    if not isinstance(mapping, dict):
        return f"{adr_id} issue reference {reference} mapping must be an object"
    if _issue_reference_mapping_is_valid(mapping):
        return None
    return (
        f"{adr_id} issue reference {reference} must exclusively map to a "
        "non-empty, duplicate-free list of declared operations or have only "
        "disposition 'out-of-scope'"
    )


def validate_contract_issue_references(
    contract: dict[str, object], adr_id: str
) -> list[str]:
    """Validate the issue-reference map declared by an interface contract."""
    references = contract.get("issue_references")
    if not isinstance(references, dict):
        return [f"{adr_id} interface_contract.issue_references must be an object"]
    errors: list[str] = []
    actual_references = set(references)
    if actual_references != RANGE_SUBSTRATE_ISSUE_REFERENCES:
        errors.append(
            f"{adr_id} interface_contract.issue_references must contain exactly "
            f"{sorted(RANGE_SUBSTRATE_ISSUE_REFERENCES)}; got {sorted(actual_references)}"
        )
    for reference, mapping in references.items():
        error = _issue_reference_error(mapping, reference, adr_id)
        if error is not None:
            errors.append(error)
    return errors


def validate_closed_mapping(
    value: object,
    field: str,
    *,
    fixed: dict[str, object],
    string_sets: dict[str, frozenset[str]] | None = None,
) -> list[str]:
    """Validate one exact-key mapping with typed fixed values and closed string sets."""
    if not isinstance(value, dict):
        return [f"{field} must be an object"]
    set_members = string_sets or {}
    expected_keys = set(fixed) | set(set_members)
    actual_keys = set(value)
    errors: list[str] = []
    if actual_keys != expected_keys:
        errors.append(
            f"{field} must contain exactly {sorted(expected_keys)}; got {sorted(actual_keys)}"
        )
    for key, expected in fixed.items():
        if key not in value:
            continue
        actual = value[key]
        if type(actual) is not type(expected) or actual != expected:
            errors.append(f"{field}.{key} must be {expected!r}; got {actual!r}")
    for key, expected in set_members.items():
        if key in value:
            errors.extend(
                validate_exact_string_members(value[key], expected, f"{field}.{key}")
            )
    return errors
