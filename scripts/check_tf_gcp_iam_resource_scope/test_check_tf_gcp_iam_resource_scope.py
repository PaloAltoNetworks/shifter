"""Tests for check_tf_gcp_iam_resource_scope.py.

Run from the repo root:
    python3 -m unittest scripts.check_tf_gcp_iam_resource_scope.test_check_tf_gcp_iam_resource_scope -v

Two suites:
* CheckTfGcpIamResourceScopeTest exercises the guard against synthetic HCL.
* EffectivePermissionMatrixTest is the ADR-008-R7 effective-permission oracle: it
  reads the live portal/iam module and asserts each workload identity's resource
  set (project roles, named-secret readers, per-bucket roles, and the two tracked
  #1586 residuals), the prefix-conditioned VPN gateway actAs grant, plus explicit
  denied examples.
"""

from __future__ import annotations

import datetime
import re
import tempfile
import textwrap
import unittest
from collections import defaultdict
from pathlib import Path
from unittest.mock import patch

from .check_tf_gcp_iam_resource_scope import (
    ALLOWLIST,
    _LITERAL_ROLE_RE,
    _PROJECT_IAM_MEMBER_RE,
    _WORKLOAD_MEMBER_RE,
    _extract_resource_blocks,
    _parse_role_map,
    check_file,
    check_paths,
)

LIVE_IAM_DIR = Path("platform/terraform/gcp/modules/portal/iam")
LIVE_IAM_TF = LIVE_IAM_DIR / "main.tf"

# A minimal representation of the refactored module: the project-role map (no
# secret/storage role), the map-driven for_each resource, and the two allowlisted
# residual literals. Reused as the base for the negative fixtures.
_CLEAN_MODULE = """
locals {
  workload_project_roles = {
    portal = toset(["roles/firebaseauth.viewer", "roles/pubsub.publisher"])
    workers = toset(["roles/pubsub.publisher", "roles/pubsub.subscriber"])
    "ctf-scheduler" = toset(["roles/pubsub.publisher"])
    provisioner = toset(["roles/artifactregistry.reader", "roles/compute.admin"])
  }
}

resource "google_project_iam_member" "workload_roles" {
  for_each = merge([
    for account_name, roles in local.workload_project_roles : {
      for role in roles : "${account_name}:${role}" => {
        account_name = account_name
        role         = role
      }
    }
  ]...)
  project = var.project_id
  role    = each.value.role
  member  = "serviceAccount:${google_service_account.workload[each.value.account_name].email}"
}

resource "google_project_iam_member" "portal_dynamic_secret_accessor" {
  project = var.project_id
  role    = "roles/secretmanager.secretAccessor"
  member  = "serviceAccount:${google_service_account.workload["portal"].email}"
}

resource "google_project_iam_member" "provisioner_dynamic_secret_admin" {
  project = var.project_id
  role    = "roles/secretmanager.admin"
  member  = "serviceAccount:${google_service_account.workload["provisioner"].email}"
}
"""


def _write(tmp_path: Path, body: str, name: str = "iam.tf") -> Path:
    path = tmp_path / name
    path.write_text(textwrap.dedent(body).lstrip())
    return path


class CheckTfGcpIamResourceScopeTest(unittest.TestCase):
    def test_clean_module_with_only_allowlisted_residuals_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(Path(tmp), _CLEAN_MODULE)
            self.assertEqual(check_file(tf), [])

    def test_forbidden_role_in_local_map_is_rejected(self) -> None:
        # A secretAccessor slipped back into the workers project-role map.
        module = _CLEAN_MODULE.replace(
            'workers = toset(["roles/pubsub.publisher", "roles/pubsub.subscriber"])',
            'workers = toset(["roles/pubsub.publisher", "roles/secretmanager.secretAccessor"])',
        )
        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(Path(tmp), module)
            reasons = [v.reason for v in check_file(tf)]
        self.assertTrue(
            any("workers" in r and "secretAccessor" in r for r in reasons),
            f"expected workers secretAccessor map violation, got: {reasons}",
        )

    def test_forbidden_storage_role_in_map_for_provisioner_is_rejected(self) -> None:
        module = _CLEAN_MODULE.replace(
            'provisioner = toset(["roles/artifactregistry.reader", "roles/compute.admin"])',
            'provisioner = toset(["roles/compute.admin", "roles/storage.objectAdmin"])',
        )
        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(Path(tmp), module)
            reasons = [v.reason for v in check_file(tf)]
        self.assertTrue(
            any("provisioner" in r and "storage.objectAdmin" in r for r in reasons),
            f"expected provisioner objectAdmin map violation, got: {reasons}",
        )

    def test_literal_forbidden_grant_is_rejected_regardless_of_resource_name(self) -> None:
        # Renaming the resource does not bypass detection: the guard keys on the
        # role + member, not the resource label.
        module = _CLEAN_MODULE + textwrap.dedent(
            """
            resource "google_project_iam_member" "totally_innocent_name" {
              project = var.project_id
              role    = "roles/storage.objectAdmin"
              member  = "serviceAccount:${google_service_account.workload["workers"].email}"
            }
            """
        )
        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(Path(tmp), module)
            reasons = [v.reason for v in check_file(tf)]
        self.assertTrue(
            any("workers" in r and "storage.objectAdmin" in r for r in reasons),
            f"expected workers objectAdmin literal violation, got: {reasons}",
        )

    def test_forbidden_role_on_non_workload_principal_is_allowed(self) -> None:
        # The GCE range-host SA is a different principal, not one of the four
        # workload identities; a project-level object role on it is out of scope.
        module = _CLEAN_MODULE + textwrap.dedent(
            """
            resource "google_project_iam_member" "range_host_admin" {
              project = var.project_id
              role    = "roles/storage.objectAdmin"
              member  = "serviceAccount:${google_service_account.range_host.email}"
            }
            """
        )
        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(Path(tmp), module)
            self.assertEqual(check_file(tf), [])

    def test_extra_allowlisted_pair_beyond_residuals_is_rejected(self) -> None:
        # workers project-level secretAccessor is NOT allowlisted (only portal is);
        # a literal grant must still be flagged.
        module = _CLEAN_MODULE + textwrap.dedent(
            """
            resource "google_project_iam_member" "workers_secret" {
              project = var.project_id
              role    = "roles/secretmanager.secretAccessor"
              member  = "serviceAccount:${google_service_account.workload["workers"].email}"
            }
            """
        )
        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(Path(tmp), module)
            reasons = [v.reason for v in check_file(tf)]
        self.assertTrue(
            any("workers" in r and "secretAccessor" in r for r in reasons),
            f"expected workers secretAccessor literal violation, got: {reasons}",
        )

    def test_custom_role_with_forbidden_permissions_bound_to_workload_is_rejected(self) -> None:
        module = _CLEAN_MODULE + textwrap.dedent(
            """
            resource "google_project_iam_custom_role" "prov_dynamic" {
              role_id     = "shifterProvDynamic"
              title       = "prov"
              permissions = ["secretmanager.secrets.create", "secretmanager.versions.add"]
            }

            resource "google_project_iam_member" "prov_custom" {
              project = var.project_id
              role    = google_project_iam_custom_role.prov_dynamic.id
              member  = "serviceAccount:${google_service_account.workload["provisioner"].email}"
            }
            """
        )
        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(Path(tmp), module)
            reasons = [v.reason for v in check_file(tf)]
        self.assertTrue(
            any("custom role" in r and "provisioner" in r for r in reasons),
            f"expected provisioner custom-role violation, got: {reasons}",
        )

    def test_custom_role_with_benign_permissions_is_allowed(self) -> None:
        module = _CLEAN_MODULE + textwrap.dedent(
            """
            resource "google_project_iam_custom_role" "meta_only" {
              role_id     = "shifterMetaOnly"
              title       = "meta"
              permissions = ["secretmanager.secrets.get", "secretmanager.locations.list"]
            }

            resource "google_project_iam_member" "meta_custom" {
              project = var.project_id
              role    = google_project_iam_custom_role.meta_only.id
              member  = "serviceAccount:${google_service_account.workload["provisioner"].email}"
            }
            """
        )
        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(Path(tmp), module)
            self.assertEqual(check_file(tf), [])

    def test_authoritative_policy_binding_is_rejected(self) -> None:
        module = _CLEAN_MODULE + textwrap.dedent(
            """
            data "google_iam_policy" "p" {
              binding {
                role    = "roles/storage.objectAdmin"
                members = ["serviceAccount:${google_service_account.workload["ctf-scheduler"].email}"]
              }
            }
            """
        )
        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(Path(tmp), module)
            reasons = [v.reason for v in check_file(tf)]
        self.assertTrue(
            any("ctf-scheduler" in r and "storage.objectAdmin" in r for r in reasons),
            f"expected ctf-scheduler policy-binding violation, got: {reasons}",
        )

    def test_forbidden_grant_split_across_sibling_files_is_rejected(self) -> None:
        # The role map lives in one file and the for_each resource that consumes
        # it in a sibling file. check_paths shares locals across the file set, so
        # a forbidden role cannot hide by splitting map and consumer.
        with tempfile.TemporaryDirectory() as tmp:
            locals_file = _write(
                Path(tmp),
                """
                locals {
                  workload_project_roles = {
                    workers = toset(["roles/pubsub.publisher", "roles/storage.objectAdmin"])
                  }
                }
                """,
                name="locals.tf",
            )
            resource_file = _write(
                Path(tmp),
                """
                resource "google_project_iam_member" "workload_roles" {
                  for_each = merge([
                    for account_name, roles in local.workload_project_roles : {
                      for role in roles : "${account_name}:${role}" => {
                        account_name = account_name
                        role         = role
                      }
                    }
                  ]...)
                  project = var.project_id
                  role    = each.value.role
                  member  = "serviceAccount:${google_service_account.workload[each.value.account_name].email}"
                }
                """,
                name="members.tf",
            )
            reasons = [v.reason for v in check_paths([locals_file, resource_file])]
        self.assertTrue(
            any("workers" in r and "storage.objectAdmin" in r for r in reasons),
            f"expected cross-file split violation, got: {reasons}",
        )

    def test_live_module_all_tf_files_pass(self) -> None:
        # Whole-module scan (matches the pre-commit / CI *.tf glob): no sibling
        # file may carry a forbidden grant either.
        tf_files = sorted(LIVE_IAM_DIR.glob("*.tf"))
        self.assertTrue(tf_files, "expected .tf files in the iam module")
        self.assertEqual(check_paths(tf_files), [])

    def test_allowlist_residuals_have_future_expiry(self) -> None:
        # A residual whose expiry has passed becomes a violation; keep them dated
        # ahead of the #1586 review window so the guard stays green until then.
        for (workload, role), residual in ALLOWLIST.items():
            self.assertGreater(
                residual.expires_on,
                datetime.date.today(),
                f"ALLOWLIST residual {workload}:{role} expired on {residual.expires_on}",
            )

    def test_expired_allowlist_residual_is_reported_by_the_checker(self) -> None:
        pair, residual = next(iter(ALLOWLIST.items()))
        expired = type(residual)(
            reason=residual.reason,
            expires_on=datetime.date.today() - datetime.timedelta(days=1),
        )
        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(Path(tmp), _CLEAN_MODULE)
            with patch.dict(ALLOWLIST, {pair: expired}):
                violations = check_file(tf)

        self.assertEqual(len(violations), 1)
        self.assertIn(pair[0], violations[0].reason)
        self.assertIn(pair[1], violations[0].reason)
        self.assertIn("ALLOWLIST residual that expired", violations[0].reason)

    def test_live_iam_module_passes(self) -> None:
        # Live-state regression: the refactored module must hold only the two
        # allowlisted residual project grants; every static grant is per-resource.
        self.assertEqual(check_file(LIVE_IAM_TF), [])


class EffectivePermissionMatrixTest(unittest.TestCase):
    """ADR-008-R7 effective-permission oracle over the live portal/iam module.

    Parses and expands the module into the computed IAM binding graph -- the
    per-workload project roles, per-bucket roles, named-secret-reader set, and
    literal project grants -- and asserts that graph against an independent
    expected oracle, rather than matching source substrings.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.text = LIVE_IAM_TF.read_text()
        cls.lines = cls.text.splitlines()
        cls.project_roles = {
            workload: set(roles)
            for workload, roles in _parse_role_map(cls.text, "workload_project_roles").items()
        }
        cls.bucket_roles = cls._bucket_role_graph(cls.text)
        cls.literal_project_grants = cls._literal_project_grants(cls.lines)
        cls.secret_readers = cls._secret_reader_workloads(cls.text)

    @staticmethod
    def _bucket_role_graph(text: str) -> dict[str, set[str]]:
        """Expand workload_bucket_bindings into {workload -> {roles}}."""
        graph: dict[str, set[str]] = defaultdict(set)
        entry = re.compile(
            r'workload\s*=\s*"([\w-]+)"\s*,\s*bucket\s*=\s*[^,]+,\s*role\s*=\s*"(roles/[^"]+)"'
        )
        for workload, role in entry.findall(text):
            graph[workload].add(role)
        return graph

    @staticmethod
    def _literal_project_grants(lines: list[str]) -> set[tuple[str, str]]:
        """Expand literal google_project_iam_member grants into {(workload, role)}."""
        grants: set[tuple[str, str]] = set()
        for _name, _line, body in _extract_resource_blocks(lines, _PROJECT_IAM_MEMBER_RE):
            role_match = _LITERAL_ROLE_RE.search(body)
            if not role_match:
                continue
            for workload in _WORKLOAD_MEMBER_RE.findall(body):
                grants.add((workload, role_match.group(1)))
        return grants

    @staticmethod
    def _secret_reader_workloads(text: str) -> set[str]:
        """Expand secret_reader_workloads = toset([...]) into a set."""
        match = re.search(r"secret_reader_workloads\s*=\s*toset\(\[([^\]]*)\]", text)
        return set(re.findall(r'"([\w-]+)"', match.group(1))) if match else set()

    def test_expected_project_roles_per_workload(self) -> None:
        self.assertEqual(
            self.project_roles,
            {
                "portal": {"roles/firebaseauth.viewer", "roles/pubsub.publisher"},
                "workers": {"roles/pubsub.publisher", "roles/pubsub.subscriber"},
                "ctf-scheduler": {"roles/pubsub.publisher"},
                "provisioner": {
                    "roles/artifactregistry.reader",
                    "roles/compute.admin",
                    "roles/pubsub.publisher",
                },
            },
        )

    def test_project_roles_hold_no_secret_or_storage_role(self) -> None:
        for workload, roles in self.project_roles.items():
            for role in roles:
                self.assertFalse(
                    role.startswith(("roles/secretmanager.", "roles/storage.")),
                    f"{workload} carries project-level {role}",
                )

    def test_bucket_role_graph_matches_expected(self) -> None:
        self.assertEqual(
            {workload: roles for workload, roles in self.bucket_roles.items()},
            {
                # portal: objectAdmin on the assets bucket, and read-only
                # objectViewer on the optional object-backed ACES package bucket
                # (#1567, gated on aces_package_bucket_name).
                "portal": {"roles/storage.objectAdmin", "roles/storage.objectViewer"},
                "workers": {"roles/storage.objectViewer"},
                "provisioner": {"roles/storage.objectViewer", "roles/storage.objectAdmin"},
            },
        )
        self.assertNotIn("ctf-scheduler", self.bucket_roles)

    def test_named_secret_readers_include_the_launch_worker(self) -> None:
        self.assertEqual(
            self.secret_readers,
            {"portal", "workers", "ctf-scheduler", "provisioner-launcher"},
        )
        self.assertNotIn("provisioner", self.secret_readers)

    def test_named_secret_reader_binding_uses_accessor_not_admin(self) -> None:
        reader_blocks = [
            body
            for name, _line, body in _extract_resource_blocks(
                self.lines,
                re.compile(r'^\s*resource\s+"google_secret_manager_secret_iam_member"\s+"([^"]+)"'),
            )
            if name == "workload_secret_readers"
        ]
        self.assertEqual(len(reader_blocks), 1)
        self.assertRegex(reader_blocks[0], r'role\s*=\s*"roles/secretmanager\.secretAccessor"')

    def test_only_guacamole_db_is_excluded_from_named_secrets(self) -> None:
        match = re.search(
            r"runtime_secret_reader_keys\s*=\s*\[for key in keys\(var\.runtime_secret_ids\)"
            r"\s*:\s*key\s+if\s+(.+?)\]",
            self.text,
        )
        self.assertIsNotNone(match)
        self.assertEqual(match.group(1).strip(), 'key != "guacamole-db"')

    def test_literal_project_grants_are_exactly_the_residuals_and_scoped_vpn_act_as(self) -> None:
        # Secret/storage literals remain exactly the two ALLOWLIST residuals.
        # The only additional literal is actAs, condition-scoped to generation
        # OpenVPN identities rather than all project service accounts.
        expected = set(ALLOWLIST.keys()) | {("provisioner", "roles/iam.serviceAccountUser")}
        self.assertEqual(self.literal_project_grants, expected)
        vpn_blocks = [
            body
            for name, _line, body in _extract_resource_blocks(self.lines, _PROJECT_IAM_MEMBER_RE)
            if name == "provisioner_vpn_gateway_user"
        ]
        self.assertEqual(len(vpn_blocks), 1)
        self.assertIn(
            "resource.name.startsWith('projects/${var.project_id}/serviceAccounts/sh-vpn-')",
            vpn_blocks[0],
        )
        self.assertEqual(check_paths(sorted(LIVE_IAM_DIR.glob("*.tf"))), [])


if __name__ == "__main__":
    unittest.main()
