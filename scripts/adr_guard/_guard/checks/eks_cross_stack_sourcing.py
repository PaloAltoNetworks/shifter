"""ADR-044-R6: the AWS EKS Terraform roots compose over the existing data plane.

The EKS control plane reuses the portal and range data plane and sources
cross-stack values through native AWS data sources and SSM Parameter Store.
``terraform_remote_state`` is prohibited in the EKS roots because it tightly
couples the consumer to another stack's whole state file; native data sources
and SSM parameters return only the values the consumer needs and keep the
stacks loosely coupled.
"""
from __future__ import annotations

import re
from pathlib import Path

from .._common import (
    Violation,
    is_guard_source_path,
)

_CHECK = "eks-cross-stack-sourcing"
_RULE = "ADR-044-R6"
_EKS_ROOT_PREFIX = "platform/terraform/environments/"
_EKS_ROOT_MARKER = "/eks/"
# Match a `data "terraform_remote_state"` block header, tolerating any
# run of whitespace between the keyword and the quoted type.
_REMOTE_STATE = re.compile(r'data\s+"terraform_remote_state"')


def _is_eks_root_tf(path: str) -> bool:
    """True for a Terraform file under any environments/<env>/eks root."""
    return path.startswith(_EKS_ROOT_PREFIX) and _EKS_ROOT_MARKER in path and path.endswith(".tf")


def check_eks_cross_stack_sourcing(repo_root: Path, files: list[str] | None) -> list[Violation]:
    """Reject terraform_remote_state in the AWS EKS Terraform roots (ADR-044-R6).

    The EKS roots must read the existing portal/range data plane through native
    AWS data sources and SSM Parameter Store, never another stack's remote state.
    """
    if files is not None and not any(_is_eks_root_tf(path) or is_guard_source_path(path) for path in files):
        return []

    environments = repo_root / "platform" / "terraform" / "environments"
    violations: list[Violation] = []
    for tf_path in sorted(environments.glob("*/eks/**/*.tf")):
        if not _REMOTE_STATE.search(tf_path.read_text(encoding="utf-8")):
            continue
        rel = tf_path.resolve().relative_to(repo_root.resolve()).as_posix()
        violations.append(
            Violation(
                _CHECK,
                _RULE,
                rel,
                "EKS Terraform roots must source cross-stack values via native AWS data "
                "sources and SSM Parameter Store, not terraform_remote_state (ADR-044-R6): "
                "remove the terraform_remote_state data source.",
            )
        )
    return violations
