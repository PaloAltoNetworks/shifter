"""Kubernetes deployment security-context and network-policy coverage checks."""
from __future__ import annotations

from pathlib import Path

from .._common import (
    Violation,
    _ADR_GUARD_PATH,
    _repo_relative,
)
from ._k8s_security_manifests import (
    HELM_CHART_DIR,
    HELM_VALUES_FILES,
    K8S_BASE_DEPLOYMENT_DIR,
    _check_container_basic_fields,
    _check_container_capabilities,
    _check_container_identity,
    _check_container_seccomp,
    _check_k8s_container_security,
    _check_k8s_pod_security,
    _coerce_container_sc,
    _effective_field,
    _is_real_int,
    _iter_yaml_documents,
    _mapping_level,
    _render_chart_for_validation,
    _resolve_pod_sc,
    _resolve_pod_spec,
    _scan_targets,
    _v,
    _validate_base_files,
    _validate_chart_renders,
    _validate_containers_list,
    _validate_deployment_documents,
)
from ._k8s_security_network_policy import (
    _as_network_policy_violations,
    _broad_egress_network_policy_violations,
    _collect_shifter_namespaces,
    _default_deny_network_policy_namespaces,
    _destination_ip_block_cidr,
    _document_namespace,
    _is_default_deny_network_policy,
    _is_shifter_namespace,
    _iter_egress_destinations,
    _missing_default_deny_network_policy_violations,
    _network_policy_name,
    _network_policy_violation,
    _shifter_network_policy_docs,
    _validate_network_policy_base_files,
    _validate_network_policy_chart_renders,
    _validate_network_policy_documents,
)


def check_k8s_deployment_security_context(repo_root: Path, files: list[str] | None) -> list[Violation]:
    """Verify pod, container, and init-container securityContext on Deployments (ADR-006-R2).

    Two enforcement sources are scanned per ADR-006-R2 and ADR-007:

    1. **Base manifest snapshots** under `platform/k8s/gcp/base/` (recursive):
       every YAML document with `kind: Deployment` is validated regardless of
       filename or extension.
    2. **Helm chart rendered output**: the chart at
       `platform/charts/shifter` is rendered via `helm template` for each
       supported values file in `HELM_VALUES_FILES`, and every Deployment
       document in the rendered output is validated. Per ADR-007 the chart is
       the authoritative deployment contract; this catches regressions where
       a chart template or values file removes a required securityContext
       field even if the base snapshots remain compliant.

    Honors pod-level securityContext inheritance for runAsNonRoot, runAsUser,
    and runAsGroup (Kubernetes lets these be set on the pod and inherited by
    containers unless overridden).

    Per Deployment:
    - pod-level seccompProfile.type == 'RuntimeDefault'
    - every container AND initContainer (effective context after pod-level
      inheritance):
      - allowPrivilegeEscalation: false (container-only)
      - capabilities.drop: ['ALL'] AND no capabilities.add (container-only)
      - readOnlyRootFilesystem: true (container-only)
      - privileged: not true (container-only)
      - container-level seccompProfile.type, when set, equals 'RuntimeDefault'
      - runAsNonRoot: true (effective)
      - runAsUser, runAsGroup are positive integers (effective; booleans rejected)
    """
    scan_base, scan_chart, base_files = _scan_targets(repo_root, files)
    if not (scan_base or scan_chart):
        return []

    violations: list[Violation] = []
    if scan_base:
        violations.extend(_validate_base_files(repo_root, base_files))
    if scan_chart:
        violations.extend(_validate_chart_renders(repo_root))
    return violations


def check_k8s_network_policy_coverage(repo_root: Path, files: list[str] | None) -> list[Violation]:
    """Verify Shifter namespaces are isolated by default-deny NetworkPolicies."""
    scan_base, scan_chart, base_files = _scan_targets(repo_root, files)
    if not (scan_base or scan_chart):
        return []

    violations: list[Violation] = []
    if scan_base:
        violations.extend(_validate_network_policy_base_files(repo_root, base_files))
    if scan_chart:
        violations.extend(_validate_network_policy_chart_renders(repo_root))
    return violations


# The check helpers live in the two private sibling modules above; they are
# re-exported here so `_guard.checks.k8s_security` keeps the single, stable
# import-time surface that `adr_guard.py` copies and the tests reach through.
__all__ = [
    "HELM_CHART_DIR",
    "HELM_VALUES_FILES",
    "K8S_BASE_DEPLOYMENT_DIR",
    "_ADR_GUARD_PATH",
    "_as_network_policy_violations",
    "_broad_egress_network_policy_violations",
    "_check_container_basic_fields",
    "_check_container_capabilities",
    "_check_container_identity",
    "_check_container_seccomp",
    "_check_k8s_container_security",
    "_check_k8s_pod_security",
    "_coerce_container_sc",
    "_collect_shifter_namespaces",
    "_default_deny_network_policy_namespaces",
    "_destination_ip_block_cidr",
    "_document_namespace",
    "_effective_field",
    "_is_default_deny_network_policy",
    "_is_real_int",
    "_is_shifter_namespace",
    "_iter_egress_destinations",
    "_iter_yaml_documents",
    "_mapping_level",
    "_missing_default_deny_network_policy_violations",
    "_network_policy_name",
    "_network_policy_violation",
    "_render_chart_for_validation",
    "_repo_relative",
    "_resolve_pod_sc",
    "_resolve_pod_spec",
    "_scan_targets",
    "_shifter_network_policy_docs",
    "_v",
    "_validate_base_files",
    "_validate_chart_renders",
    "_validate_containers_list",
    "_validate_deployment_documents",
    "_validate_network_policy_base_files",
    "_validate_network_policy_chart_renders",
    "_validate_network_policy_documents",
    "check_k8s_deployment_security_context",
    "check_k8s_network_policy_coverage",
]
