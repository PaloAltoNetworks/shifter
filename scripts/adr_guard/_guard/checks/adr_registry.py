"""ADR registry integrity checks."""

from __future__ import annotations

from pathlib import Path

from .._common import (
    Violation,
    _load_json_yaml,
    load_adr_exceptions,
    validate_adr_exceptions,
)
from .adr_registry_contract_support import REQUIRED_INTERFACE_CONTRACTS
from .adr_registry_contracts import validate_interface_contract

REQUIRED_ADR_KEYS = {
    "id",
    "title",
    "status",
    "scope",
    "decision",
    "rules",
    "exceptions",
    "enforcement",
    "evidence",
}
_ADR_INDEX_PATH = "docs/adr/index.yaml"
_ADR_EXCEPTIONS_PATH = "docs/adr/exceptions.yaml"


def load_adr_registry(repo_root: Path) -> list[dict[str, object]]:
    """Load and validate the ADR registry shape."""
    data = _load_json_yaml(repo_root / "docs" / "adr" / "index.yaml")
    if not isinstance(data, list):
        raise ValueError(f"{_ADR_INDEX_PATH} must contain a top-level list")
    return data


def _registry_violation(path: str, message: str) -> Violation:
    """Build an adr-registry / ADR-REGISTRY violation at ``path``."""
    return Violation("adr-registry", "ADR-REGISTRY", path, message)


def _check_adr_entry(
    entry: dict[str, object],
    adr_ids: set[str],
    rule_ids: set[str],
    violations: list[Violation],
) -> None:
    """Validate one registry entry and collect its ADR and rule identifiers."""
    missing = REQUIRED_ADR_KEYS - set(entry)
    if missing:
        violations.append(
            _registry_violation(
                _ADR_INDEX_PATH,
                f"ADR entry {entry.get('id', '<missing-id>')} is missing keys: {sorted(missing)}",
            )
        )
        return
    adr_id = entry["id"]
    if adr_id in adr_ids:
        violations.append(
            _registry_violation(_ADR_INDEX_PATH, f"Duplicate ADR id: {adr_id}")
        )
    adr_ids.add(adr_id)
    interface_contract = entry.get("interface_contract")
    if adr_id in REQUIRED_INTERFACE_CONTRACTS and interface_contract is None:
        violations.append(
            _registry_violation(
                _ADR_INDEX_PATH,
                f"{adr_id} must define interface_contract kind {REQUIRED_INTERFACE_CONTRACTS[adr_id]!r}",
            )
        )
    elif interface_contract is not None:
        for error in validate_interface_contract(interface_contract, adr_id):
            violations.append(_registry_violation(_ADR_INDEX_PATH, error))
    rules = entry.get("rules", [])
    if not isinstance(rules, list):
        violations.append(
            _registry_violation(_ADR_INDEX_PATH, f"{adr_id} rules must be a list")
        )
        return
    for rule in rules:
        rule_id = rule.get("id")
        if not rule_id:
            violations.append(
                _registry_violation(
                    _ADR_INDEX_PATH, f"{adr_id} has a rule without an id"
                )
            )
            continue
        if rule_id in rule_ids:
            violations.append(
                _registry_violation(_ADR_INDEX_PATH, f"Duplicate rule id: {rule_id}")
            )
        rule_ids.add(rule_id)


def check_adr_registry(repo_root: Path, files: list[str] | None) -> list[Violation]:
    """Validate the ADR registry and exception references."""
    del files
    violations: list[Violation] = []
    try:
        registry = load_adr_registry(repo_root)
        exceptions = load_adr_exceptions(repo_root)
    except (OSError, ValueError) as err:
        return [Violation("adr-registry", "ADR-REGISTRY", "docs/adr", str(err))]
    for error in validate_adr_exceptions(exceptions):
        violations.append(_registry_violation(_ADR_EXCEPTIONS_PATH, error))
    adr_ids: set[str] = set()
    rule_ids: set[str] = set()
    for entry in registry:
        _check_adr_entry(entry, adr_ids, rule_ids, violations)
    for exception in exceptions:
        rule_id = exception.get("rule_id")
        if not rule_id or rule_id not in rule_ids:
            violations.append(
                _registry_violation(
                    _ADR_EXCEPTIONS_PATH,
                    f"Exception references unknown rule id: {rule_id!r}",
                )
            )
    return violations
