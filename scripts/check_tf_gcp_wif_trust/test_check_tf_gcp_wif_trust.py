"""Tests for check_tf_gcp_wif_trust.py."""

from __future__ import annotations

import tempfile
import textwrap
import unittest
from pathlib import Path

from .check_tf_gcp_wif_trust import check_file

# The exact-subject federation shape this guard requires (ADR-004-R23, #1690):
# a single-source subject list, an exact-subject for_each WIF binding, and a
# static condition (repo + protected ref + literal assertion.sub ==) that matches
# the list. Single-quoted CEL literals so Checkov's regex matches.
GOOD_MODULE = """
locals {
  federated_subjects = [
    "repo:Brad-Edwards/shifter:environment:gcp-dev",
    "repo:Brad-Edwards/shifter:ref:refs/heads/dev",
  ]
  wif_subject_principals = {
    for sub in local.federated_subjects :
    sub => "principal://iam.googleapis.com/pool/subject/${sub}"
  }
  ref_condition = join(" || ", [for r in var.allowed_workflow_refs : "assertion.ref == '${r}'"])
}

resource "google_iam_workload_identity_pool_provider" "github" {
  attribute_condition = "assertion.repository == 'Brad-Edwards/shifter' && (${local.ref_condition}) && (assertion.sub == 'repo:Brad-Edwards/shifter:environment:gcp-dev' || assertion.sub == 'repo:Brad-Edwards/shifter:ref:refs/heads/dev')"
}

resource "google_service_account_iam_member" "packer_build_wif" {
  for_each           = local.wif_subject_principals
  service_account_id = google_service_account.packer_build.name
  role               = "roles/iam.workloadIdentityUser"
  member             = each.value
}
"""

# Repository-only condition + repository-wide principalSet + surviving waiver.
BAD_MODULE = """
locals {
  repo_principal = "principalSet://iam.googleapis.com/pool/attribute.repository/Brad-Edwards/shifter"
}

resource "google_iam_workload_identity_pool_provider" "github" {
  # checkov:skip=CKV_GCP_125:Federation is repository-scoped the recommended way.
  attribute_condition = "assertion.repository == 'Brad-Edwards/shifter'"
}

resource "google_service_account_iam_member" "packer_build_wif" {
  service_account_id = google_service_account.packer_build.name
  role               = "roles/iam.workloadIdentityUser"
  member             = local.repo_principal
}
"""


# A repository-only condition whose attribute_mapping DOES map assertion.ref /
# assertion.sub. A block-wide token scan would pass this (the tokens appear in
# the mapping); the condition-scoped checks must still reject it (codex #1690).
MAPPED_REPO_ONLY = """
resource "google_iam_workload_identity_pool_provider" "github" {
  attribute_mapping = {
    "google.subject"       = "assertion.sub"
    "attribute.repository" = "assertion.repository"
    "attribute.ref"        = "assertion.ref"
  }
  attribute_condition = "assertion.repository == 'Brad-Edwards/shifter'"
}

resource "google_service_account_iam_member" "wif" {
  role   = "roles/iam.workloadIdentityUser"
  member = "principal://iam.googleapis.com/pool/subject/repo:Brad-Edwards/shifter:ref:refs/heads/dev"
}
"""


def _write(tmp_path: Path, name: str, body: str) -> Path:
    path = tmp_path / name
    path.write_text(textwrap.dedent(body).lstrip())
    return path


class CheckTfGcpWifTrustTest(unittest.TestCase):
    def test_exact_subject_module_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(Path(tmp), "main.tf", GOOD_MODULE)
            self.assertEqual(check_file(tf), [])

    def test_repository_only_condition_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(Path(tmp), "main.tf", BAD_MODULE)
            reasons = [v.reason for v in check_file(tf)]
        self.assertTrue(any("assertion.ref" in reason for reason in reasons))

    def test_missing_assertion_sub_clause_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(Path(tmp), "main.tf", BAD_MODULE)
            reasons = [v.reason for v in check_file(tf)]
        self.assertTrue(any("assertion.sub" in reason for reason in reasons))

    def test_repository_wide_principalset_binding_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(Path(tmp), "main.tf", BAD_MODULE)
            reasons = [v.reason for v in check_file(tf)]
        self.assertTrue(any("principalSet" in reason for reason in reasons))

    def test_surviving_ckv_gcp_125_waiver_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(Path(tmp), "main.tf", BAD_MODULE)
            reasons = [v.reason for v in check_file(tf)]
        self.assertTrue(any("CKV_GCP_125" in reason for reason in reasons))

    def test_condition_binding_drift_is_rejected(self) -> None:
        # local.federated_subjects lists a subject the static condition omits.
        drift = GOOD_MODULE.replace(
            '    "repo:Brad-Edwards/shifter:ref:refs/heads/dev",\n',
            '    "repo:Brad-Edwards/shifter:ref:refs/heads/dev",\n'
            '    "repo:Brad-Edwards/shifter:ref:refs/heads/main",\n',
        )
        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(Path(tmp), "main.tf", drift)
            reasons = [v.reason for v in check_file(tf)]
        self.assertTrue(
            any("must equal local.federated_subjects" in r for r in reasons)
        )

    def test_prose_mentioning_ckv_gcp_125_does_not_false_positive(self) -> None:
        # Non-false-positive counterpart to the waiver-rejection test: a comment
        # that NAMES the rule (not a checkov:skip directive) must not trip the
        # CKV_GCP_125 guard, mirroring the real module's explanatory comment.
        module = GOOD_MODULE.replace(
            'resource "google_iam_workload_identity_pool_provider" "github" {',
            'resource "google_iam_workload_identity_pool_provider" "github" {\n'
            "  # Replaces the repository-only condition and the CKV_GCP_125 waiver.",
        )
        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(Path(tmp), "main.tf", module)
            self.assertEqual(check_file(tf), [])

    def test_exact_principal_member_not_confused_with_principalset(self) -> None:
        # Non-false-positive counterpart to the principalSet-rejection test: an
        # exact `principal://.../subject/` member contains `//` but is NOT a
        # repository-wide principalSet, and `//` must not be stripped as a comment.
        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(Path(tmp), "main.tf", GOOD_MODULE)
            reasons = [v.reason for v in check_file(tf)]
        self.assertFalse(any("principalSet" in reason for reason in reasons))

    def test_condition_checks_are_scoped_to_condition_value(self) -> None:
        # attribute_mapping maps assertion.ref/sub, but the condition is repo-only;
        # the checks must fire on the CONDITION, not the block (codex #1690).
        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(Path(tmp), "main.tf", MAPPED_REPO_ONLY)
            reasons = [v.reason for v in check_file(tf)]
        self.assertTrue(any("assertion.ref" in r for r in reasons))
        self.assertTrue(any("assertion.sub" in r for r in reasons))

    def test_module_without_wif_resources_is_ignored(self) -> None:
        module = """
        resource "google_storage_bucket" "b" {
          name = "x"
        }
        """
        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(Path(tmp), "main.tf", module)
            self.assertEqual(check_file(tf), [])

    def test_non_tf_inputs_are_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifact = Path(tmp) / "image.tar"
            artifact.write_bytes(b"\x00\x8a\xff")
            self.assertEqual(check_file(artifact), [])


if __name__ == "__main__":
    unittest.main()
