"""Tests for the ADR-044-R6 eks-cross-stack-sourcing guard.

The EKS control plane composes over the existing portal/range data plane and
must source cross-stack values through native AWS data sources and SSM Parameter
Store, never terraform_remote_state (which couples the consumer to another
stack's whole state file). The negative fixture is the load-bearing evidence:
it proves the guard fails closed when an EKS root reintroduces
terraform_remote_state.

Fixtures are synthetic filesystem repos under tempfile, matching the adr_guard
test idiom (no mocks). One test additionally runs the guard against the real
repository to prove the shipped EKS roots comply.
"""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "adr_guard.py"
SPEC = importlib.util.spec_from_file_location("adr_guard", MODULE_PATH)
ADR_GUARD = importlib.util.module_from_spec(SPEC)
sys.modules["adr_guard"] = ADR_GUARD
SPEC.loader.exec_module(ADR_GUARD)

REPO_ROOT = Path(__file__).resolve().parents[3]

_NATIVE_SOURCING_TF = """
data "aws_db_instance" "control_plane" {
  db_instance_identifier = "shifter-dev-portal"
}

data "aws_kms_alias" "secrets" {
  name = "alias/shifter-dev-secrets"
}

data "aws_ssm_parameter" "kali_ami" {
  name = "/shifter/ami/kali"
}
"""

_REMOTE_STATE_TF = """
data "terraform_remote_state" "range" {
  backend = "s3"
  config = {
    bucket = "shifter-dev-tfstate"
    key    = "dev/range/terraform.tfstate"
    region = "us-east-2"
  }
}
"""


def _write_eks_root(repo_root: Path, env: str, body: str) -> str:
    """Write an environments/<env>/eks/main.tf and return its repo-relative path."""
    root = repo_root / "platform" / "terraform" / "environments" / env / "eks"
    root.mkdir(parents=True, exist_ok=True)
    (root / "main.tf").write_text(body, encoding="utf-8")
    return f"platform/terraform/environments/{env}/eks/main.tf"


class EksCrossStackSourcingTests(unittest.TestCase):
    def test_native_data_sources_and_ssm_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            rel = _write_eks_root(repo, "dev", _NATIVE_SOURCING_TF)
            violations = ADR_GUARD.check_eks_cross_stack_sourcing(repo, [rel])
        self.assertEqual(violations, [])

    def test_remote_state_in_eks_root_is_a_violation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            rel = _write_eks_root(repo, "prod", _REMOTE_STATE_TF)
            violations = ADR_GUARD.check_eks_cross_stack_sourcing(repo, [rel])
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0].rule_id, "ADR-044-R6")
        self.assertEqual(violations[0].check, "eks-cross-stack-sourcing")
        self.assertEqual(violations[0].path, rel)

    def test_full_scan_flags_every_offending_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            _write_eks_root(repo, "dev", _NATIVE_SOURCING_TF)
            _write_eks_root(repo, "prod", _REMOTE_STATE_TF)
            _write_eks_root(repo, "proof", _REMOTE_STATE_TF)
            violations = ADR_GUARD.check_eks_cross_stack_sourcing(repo, None)
        offending = sorted(v.path for v in violations)
        self.assertEqual(
            offending,
            [
                "platform/terraform/environments/prod/eks/main.tf",
                "platform/terraform/environments/proof/eks/main.tf",
            ],
        )

    def test_unrelated_changed_files_skip_the_scan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            # An EKS root with a violation exists, but no changed file is under an
            # EKS root or the guard source, so the scoped run must not scan it.
            _write_eks_root(repo, "dev", _REMOTE_STATE_TF)
            violations = ADR_GUARD.check_eks_cross_stack_sourcing(repo, ["README.md"])
        self.assertEqual(violations, [])

    def test_real_repository_eks_roots_comply(self) -> None:
        violations = ADR_GUARD.check_eks_cross_stack_sourcing(REPO_ROOT, None)
        self.assertEqual(
            violations,
            [],
            msg=f"shipped EKS roots must not use terraform_remote_state: {[v.path for v in violations]}",
        )


if __name__ == "__main__":
    unittest.main()
