"""NetworkPolicy coverage scanning for the ADR-006-R3 check.

Split out of ``k8s_security.py`` to keep each module under the file-length
limit; every public name here is re-imported by that module so the package
surface is unchanged.
"""
from __future__ import annotations

from pathlib import Path

from .._common import (
    Violation,
    _repo_relative,
)
from ._k8s_security_manifests import (
    HELM_VALUES_FILES,
    K8S_BASE_DEPLOYMENT_DIR,
    _iter_yaml_documents,
    _render_chart_for_validation,
)


def _network_policy_violation(path: str, message: str) -> Violation:
    """Shorthand: ADR-006-R3 violation builder for the NetworkPolicy check."""
    return Violation(
        "k8s-network-policy-coverage",
        "ADR-006-R3",
        path,
        message,
    )


def _as_network_policy_violations(violations: list[Violation]) -> list[Violation]:
    """Re-stamp violations raised by shared manifest helpers onto ADR-006-R3."""
    return [_network_policy_violation(violation.path, violation.message) for violation in violations]


def _is_shifter_namespace(name: object) -> bool:
    """True for a `shifter-` prefixed namespace name."""
    return isinstance(name, str) and name.startswith("shifter-")


def _document_namespace(doc: object) -> str | None:
    """Return a manifest document's `metadata.namespace`, or None when absent."""
    if not isinstance(doc, dict):
        return None
    metadata = doc.get("metadata")
    if not isinstance(metadata, dict):
        return None
    namespace = metadata.get("namespace")
    return namespace if isinstance(namespace, str) else None


def _collect_shifter_namespaces(docs: list[object]) -> set[str]:
    """Return every Shifter namespace declared or referenced by the documents."""
    namespaces: set[str] = set()
    for doc in docs:
        if not isinstance(doc, dict):
            continue
        metadata = doc.get("metadata")
        if not isinstance(metadata, dict):
            continue
        if doc.get("kind") == "Namespace":
            name = metadata.get("name")
            if _is_shifter_namespace(name):
                namespaces.add(name)
        namespace = metadata.get("namespace")
        if _is_shifter_namespace(namespace):
            namespaces.add(namespace)
    return namespaces


def _is_default_deny_network_policy(doc: dict[str, object]) -> bool:
    """True for a NetworkPolicy that denies all ingress and egress for every pod."""
    spec = doc.get("spec")
    if not isinstance(spec, dict):
        return False
    policy_types = spec.get("policyTypes")
    covers_both_directions = isinstance(policy_types, list) and {"Ingress", "Egress"}.issubset(set(policy_types))
    return (
        covers_both_directions
        and spec.get("podSelector") == {}
        and spec.get("ingress", []) == []
        and spec.get("egress", []) == []
    )


def _network_policy_name(doc: dict[str, object]) -> str:
    """Return the policy's `metadata.name`, or a placeholder when unnamed."""
    metadata = doc.get("metadata")
    if isinstance(metadata, dict) and isinstance(metadata.get("name"), str):
        return metadata["name"]
    return "<unnamed>"


def _shifter_network_policy_docs(docs: list[object]) -> list[tuple[dict[str, object], str]]:
    """Return (policy document, namespace) pairs for NetworkPolicies in Shifter namespaces."""
    policies: list[tuple[dict[str, object], str]] = []
    for doc in docs:
        if not isinstance(doc, dict) or doc.get("kind") != "NetworkPolicy":
            continue
        namespace = _document_namespace(doc)
        if not _is_shifter_namespace(namespace):
            continue
        policies.append((doc, namespace))
    return policies


def _default_deny_network_policy_namespaces(
    policies: list[tuple[dict[str, object], str]],
) -> set[str]:
    """Return the namespaces covered by a default-deny NetworkPolicy."""
    return {namespace for doc, namespace in policies if _is_default_deny_network_policy(doc)}


def _iter_egress_destinations(doc: dict[str, object]) -> list[tuple[int, object]]:
    """Return (rule index, destination) pairs for every `spec.egress[].to[]` entry."""
    spec = doc.get("spec")
    if not isinstance(spec, dict):
        return []
    egress_rules = spec.get("egress", [])
    if not isinstance(egress_rules, list):
        return []

    destinations: list[tuple[int, object]] = []
    for rule_index, rule in enumerate(egress_rules):
        if not isinstance(rule, dict) or not isinstance(rule.get("to"), list):
            continue
        destinations.extend((rule_index, destination) for destination in rule["to"])
    return destinations


def _destination_ip_block_cidr(destination: object) -> object:
    """Return an egress destination's `ipBlock.cidr`, or None when it has none."""
    if not isinstance(destination, dict):
        return None
    ip_block = destination.get("ipBlock")
    if not isinstance(ip_block, dict):
        return None
    return ip_block.get("cidr")


def _broad_egress_network_policy_violations(
    policies: list[tuple[dict[str, object], str]], rel: str
) -> list[Violation]:
    """Flag egress rules that allow an unrestricted IPv4/IPv6 CIDR (ADR-006-R3)."""
    violations: list[Violation] = []
    broad_cidrs = {"0.0.0.0/0", "::/0"}
    for doc, namespace in policies:
        for rule_index, destination in _iter_egress_destinations(doc):
            cidr = _destination_ip_block_cidr(destination)
            if cidr not in broad_cidrs:
                continue
            violations.append(
                _network_policy_violation(
                    rel,
                    f"NetworkPolicy {namespace}/{_network_policy_name(doc)} "
                    f"egress rule {rule_index} allows broad CIDR {cidr}; "
                    "ADR-006-R3 requires explicit service ranges",
                )
            )
    return violations


def _missing_default_deny_network_policy_violations(
    namespaces: set[str], default_deny_namespaces: set[str], rel: str
) -> list[Violation]:
    """Flag every Shifter namespace with no default-deny NetworkPolicy."""
    return [
        _network_policy_violation(
            rel,
            f"namespace {namespace} lacks a default-deny NetworkPolicy covering both ingress and egress",
        )
        for namespace in sorted(namespaces - default_deny_namespaces)
    ]


def _validate_network_policy_documents(docs: list[object], rel: str) -> list[Violation]:
    """Apply the ADR-006-R3 NetworkPolicy rules to a parsed document set."""
    namespaces = _collect_shifter_namespaces(docs)
    policies = _shifter_network_policy_docs(docs)
    default_deny_namespaces = _default_deny_network_policy_namespaces(policies)
    return [
        *_broad_egress_network_policy_violations(policies, rel),
        *_missing_default_deny_network_policy_violations(namespaces, default_deny_namespaces, rel),
    ]


def _validate_network_policy_base_files(repo_root: Path, base_files: list[Path]) -> list[Violation]:
    """Validate NetworkPolicy coverage across the base manifest snapshots."""
    violations: list[Violation] = []
    docs: list[object] = []
    for path in base_files:
        rel = _repo_relative(path, repo_root)
        parsed, parse_violations = _iter_yaml_documents(path.read_text(encoding="utf-8"), rel)
        docs.extend(parsed)
        violations.extend(_as_network_policy_violations(parse_violations))
    if base_files:
        violations.extend(_validate_network_policy_documents(docs, K8S_BASE_DEPLOYMENT_DIR))
    return violations


def _validate_network_policy_chart_renders(repo_root: Path) -> list[Violation]:
    """Validate NetworkPolicy coverage across every rendered chart output."""
    violations: list[Violation] = []
    rendered, render_violations = _render_chart_for_validation(repo_root, HELM_VALUES_FILES)
    violations.extend(_as_network_policy_violations(render_violations))
    for docs, label in rendered:
        violations.extend(_validate_network_policy_documents(docs, label))
    return violations


__all__ = [
    "_as_network_policy_violations",
    "_broad_egress_network_policy_violations",
    "_collect_shifter_namespaces",
    "_default_deny_network_policy_namespaces",
    "_destination_ip_block_cidr",
    "_document_namespace",
    "_is_default_deny_network_policy",
    "_is_shifter_namespace",
    "_iter_egress_destinations",
    "_missing_default_deny_network_policy_violations",
    "_network_policy_name",
    "_network_policy_violation",
    "_shifter_network_policy_docs",
    "_validate_network_policy_base_files",
    "_validate_network_policy_chart_renders",
    "_validate_network_policy_documents",
]
