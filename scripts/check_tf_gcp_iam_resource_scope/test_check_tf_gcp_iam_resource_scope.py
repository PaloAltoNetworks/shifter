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

import re
import tempfile
import textwrap
import unittest
from collections import defaultdict
from pathlib import Path

from .check_tf_gcp_iam_resource_scope import (
    _LITERAL_ROLE_RE,
    _PROJECT_IAM_MEMBER_RE,
    _RANGE_HOST_MEMBER_RE,
    _WORKLOAD_MEMBER_RE,
    _extract_resource_blocks,
    _parse_role_map,
    _resource_granted_roles,
    check_file,
    check_paths,
)

LIVE_IAM_DIR = Path("platform/terraform/gcp/modules/portal/iam")
LIVE_IAM_TF = LIVE_IAM_DIR / "main.tf"

# A minimal workload-role module with no secret/storage grants. Reused as the
# base for generic negative fixtures; the live module exercises the exact
# dynamic-secret exception graph.
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

"""


def _write(tmp_path: Path, body: str, name: str = "iam.tf") -> Path:
    path = tmp_path / name
    path.write_text(textwrap.dedent(body).lstrip())
    return path


class CheckTfGcpIamResourceScopeTest(unittest.TestCase):
    def test_clean_module_without_project_secret_grants_passes(self) -> None:
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

    def test_literal_forbidden_grant_is_rejected_regardless_of_resource_name(
        self,
    ) -> None:
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

    def test_range_host_literal_storage_grant_is_rejected(self) -> None:
        # #1644: the GCE range-host SA is attached to participant-controllable
        # guests, so a project-level storage role on it is now a violation (a
        # compromised guest could read across tenants).
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
            reasons = [v.reason for v in check_file(tf)]
        self.assertTrue(
            any("range-host" in r and "storage.objectAdmin" in r for r in reasons),
            f"expected range-host objectAdmin violation, got: {reasons}",
        )

    def test_range_host_inline_toset_objectviewer_is_rejected(self) -> None:
        # The real shape of the #1644 defect: an inline for_each = toset([...roles])
        # with role = each.value. objectViewer is read-only but still forbidden on
        # a participant-reachable range host (unlike the per-bucket workload grant).
        module = _CLEAN_MODULE + textwrap.dedent(
            """
            resource "google_project_iam_member" "range_host_roles" {
              for_each = toset([
                "roles/logging.logWriter",
                "roles/monitoring.metricWriter",
                "roles/storage.objectViewer",
              ])
              project = var.project_id
              role    = each.value
              member  = "serviceAccount:${google_service_account.range_host.email}"
            }
            """
        )
        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(Path(tmp), module)
            reasons = [v.reason for v in check_file(tf)]
        self.assertTrue(
            any("range-host" in r and "storage.objectViewer" in r for r in reasons),
            f"expected range-host objectViewer violation, got: {reasons}",
        )

    def test_range_host_logging_and_monitoring_only_is_allowed(self) -> None:
        # The fixed shape: logging + monitoring writes, no storage role -> clean.
        module = _CLEAN_MODULE + textwrap.dedent(
            """
            resource "google_project_iam_member" "range_host_roles" {
              for_each = toset([
                "roles/logging.logWriter",
                "roles/monitoring.metricWriter",
              ])
              project = var.project_id
              role    = each.value
              member  = "serviceAccount:${google_service_account.range_host.email}"
            }
            """
        )
        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(Path(tmp), module)
            self.assertEqual(check_file(tf), [])

    def test_range_host_pool_storage_grant_is_rejected(self) -> None:
        # The attachable range-host-pool identities are covered too (#1644).
        module = _CLEAN_MODULE + textwrap.dedent(
            """
            resource "google_project_iam_member" "range_host_pool_read" {
              count   = var.range_host_identity_pool_size
              project = var.project_id
              role    = "roles/storage.objectViewer"
              member  = "serviceAccount:${google_service_account.range_host_pool[count.index].email}"
            }
            """
        )
        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(Path(tmp), module)
            reasons = [v.reason for v in check_file(tf)]
        self.assertTrue(
            any("range-host" in r and "storage.objectViewer" in r for r in reasons),
            f"expected range-host-pool objectViewer violation, got: {reasons}",
        )

    def test_range_host_policy_binding_storage_is_rejected(self) -> None:
        module = _CLEAN_MODULE + textwrap.dedent(
            """
            data "google_iam_policy" "rh" {
              binding {
                role    = "roles/storage.objectViewer"
                members = ["serviceAccount:${google_service_account.range_host.email}"]
              }
            }
            """
        )
        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(Path(tmp), module)
            reasons = [v.reason for v in check_file(tf)]
        self.assertTrue(
            any("range-host" in r and "storage.objectViewer" in r for r in reasons),
            f"expected range-host policy-binding violation, got: {reasons}",
        )

    def test_range_host_custom_role_with_object_read_is_rejected(self) -> None:
        # An object-read custom role (get/list) bound to the range host must fail
        # even though those read perms are not in the workload FORBIDDEN set.
        module = _CLEAN_MODULE + textwrap.dedent(
            """
            resource "google_project_iam_custom_role" "rh_reader" {
              role_id     = "shifterRangeHostReader"
              title       = "range host reader"
              permissions = ["storage.objects.get", "storage.objects.list"]
            }

            resource "google_project_iam_member" "rh_custom" {
              project = var.project_id
              role    = google_project_iam_custom_role.rh_reader.id
              member  = "serviceAccount:${google_service_account.range_host.email}"
            }
            """
        )
        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(Path(tmp), module)
            reasons = [v.reason for v in check_file(tf)]
        self.assertTrue(
            any("custom role" in r and "range-host" in r for r in reasons),
            f"expected range-host custom-role violation, got: {reasons}",
        )

    def test_project_secret_accessor_is_rejected_outside_exact_boundary(self) -> None:
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

    def test_custom_role_with_forbidden_permissions_bound_to_workload_is_rejected(
        self,
    ) -> None:
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

    def test_custom_role_with_service_account_setiampolicy_bound_to_workload_is_rejected(
        self,
    ) -> None:
        # ADR-008-R7 gateway-identity escalation: a project-level custom role
        # granting the provisioner iam.serviceAccounts.setIamPolicy lets it seize
        # any service account. The pool model removes this; re-adding it must fail.
        module = _CLEAN_MODULE + textwrap.dedent(
            """
            resource "google_project_iam_custom_role" "prov_sa_admin" {
              role_id     = "shifterProvSaAdmin"
              title       = "prov sa admin"
              permissions = [
                "iam.serviceAccounts.create",
                "iam.serviceAccounts.delete",
                "iam.serviceAccounts.setIamPolicy",
              ]
            }

            resource "google_project_iam_member" "prov_sa_admin" {
              project = var.project_id
              role    = google_project_iam_custom_role.prov_sa_admin.id
              member  = "serviceAccount:${google_service_account.workload["provisioner"].email}"
            }
            """
        )
        with tempfile.TemporaryDirectory() as tmp:
            tf = _write(Path(tmp), module)
            reasons = [v.reason for v in check_file(tf)]
        self.assertTrue(
            any("custom role" in r and "provisioner" in r for r in reasons),
            f"expected provisioner SA-admin custom-role violation, got: {reasons}",
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

    def test_old_broad_dynamic_secret_residuals_are_rejected(self) -> None:
        module = _CLEAN_MODULE + textwrap.dedent(
            """
            resource "google_project_iam_member" "old_portal_residual" {
              project = var.project_id
              role    = "roles/secretmanager.secretAccessor"
              member  = "serviceAccount:${google_service_account.workload["portal"].email}"
            }
            resource "google_project_iam_member" "old_provisioner_residual" {
              project = var.project_id
              role    = "roles/secretmanager.admin"
              member  = "serviceAccount:${google_service_account.workload["provisioner"].email}"
            }
            """
        )
        with tempfile.TemporaryDirectory() as tmp:
            violations = check_file(_write(Path(tmp), module))

        reasons = [violation.reason for violation in violations]
        self.assertTrue(
            any("portal" in reason and "secretAccessor" in reason for reason in reasons)
        )
        self.assertTrue(
            any(
                "provisioner" in reason and "secretmanager.admin" in reason
                for reason in reasons
            )
        )

    def test_named_boundary_binding_fails_if_its_condition_is_removed(self) -> None:
        broken = LIVE_IAM_TF.read_text().replace(
            "    expression  = local.portal_dynamic_read_condition",
            "    expression  = true",
        )
        with tempfile.TemporaryDirectory() as tmp:
            violations = check_file(_write(Path(tmp), broken))

        self.assertTrue(
            any(
                "portal_dynamic_secret_accessor" in violation.reason
                for violation in violations
            )
        )

    def test_named_boundary_rejects_widened_condition_local_definitions(self) -> None:
        cases = {
            "dedicated_project_switch": (
                "var.dynamic_secret_project_id != var.project_id",
                "var.dynamic_secret_project_id == var.project_id",
            ),
            "canonical_prefix": (
                "secrets/shifter-${var.environment}-dynamic-",
                "secrets/",
            ),
            "participant_prefix": (
                '"${local.canonical_secret_prefix}participant-"',
                '"${local.canonical_secret_prefix}"',
            ),
            "legacy_prefixes": (
                '"projects/${data.google_project.platform.number}/secrets/shifter-range-",',
                '"projects/${data.google_project.platform.number}/secrets/",',
            ),
            "legacy_name_condition": (
                "\"resource.name.startsWith('${prefix}')\"",
                "\"resource.name != ''\"",
            ),
            "legacy_raes_directory_exclusion": (
                "-raes-domain-') == ''",
                "-raes-domain-') != ''",
            ),
            "secret_version_extraction": (
                "resource.name.extract('/secrets/{secret_id}/versions/')",
                "resource.name",
            ),
            "legacy_participant_classes": (
                "${local.legacy_secret_version_id}.endsWith('-participant-ssh')",
                "${local.legacy_secret_version_id}.endsWith('-ssh')",
            ),
            "dynamic_lifecycle_condition": (
                "resource.name.startsWith('${local.canonical_secret_prefix}')",
                "resource.name != ''",
            ),
            "portal_dynamic_read_condition": (
                "resource.name.startsWith('${local.canonical_participant_secret_prefix}')",
                "resource.name.startsWith('${local.canonical_secret_prefix}')",
            ),
        }
        live = LIVE_IAM_TF.read_text()
        for name, (closed, widened) in cases.items():
            with self.subTest(name=name):
                self.assertIn(closed, live)
                broken = live.replace(closed, widened, 1)
                with tempfile.TemporaryDirectory() as tmp:
                    violations = check_file(_write(Path(tmp), broken))

                self.assertTrue(
                    any(
                        "condition local" in violation.reason
                        for violation in violations
                    ),
                    f"expected widened {name} to fail, got: {[v.reason for v in violations]}",
                )

    def test_named_boundary_rejects_condition_above_google_operator_limit(self) -> None:
        closed = "((${local.legacy_raes_directory_name_condition}) &&"
        broken = LIVE_IAM_TF.read_text().replace(
            closed,
            "(!(${local.legacy_raes_directory_name_condition}) && true &&",
            1,
        )
        with tempfile.TemporaryDirectory() as tmp:
            violations = check_file(_write(Path(tmp), broken))

        self.assertTrue(
            any(
                "13 logical operators" in violation.reason
                and "at most 12" in violation.reason
                for violation in violations
            ),
            [violation.reason for violation in violations],
        )

    def test_named_boundary_rejects_any_extra_creator_permission(self) -> None:
        broken = LIVE_IAM_TF.read_text().replace(
            'permissions = ["secretmanager.secrets.create"]',
            'permissions = ["secretmanager.secrets.create", "iam.serviceAccounts.setIamPolicy"]',
            1,
        )
        with tempfile.TemporaryDirectory() as tmp:
            violations = check_file(_write(Path(tmp), broken))

        self.assertTrue(
            any(
                "dynamic_secret_creator must contain only" in violation.reason
                for violation in violations
            ),
            [violation.reason for violation in violations],
        )

    def test_named_boundary_rejects_any_extra_lifecycle_permission(self) -> None:
        broken = LIVE_IAM_TF.read_text().replace(
            '  permissions = [\n    "secretmanager.secrets.delete",',
            '  permissions = [\n    "iam.serviceAccounts.setIamPolicy",\n    "secretmanager.secrets.delete",',
            1,
        )
        with tempfile.TemporaryDirectory() as tmp:
            violations = check_file(_write(Path(tmp), broken))

        self.assertTrue(
            any(
                "dynamic_secret_lifecycle permissions/project differ"
                in violation.reason
                for violation in violations
            ),
            [violation.reason for violation in violations],
        )

    def test_named_boundary_fails_if_one_required_binding_is_removed(self) -> None:
        broken = re.sub(
            r'resource "google_project_iam_member" "portal_dynamic_secret_accessor" \{.*?^\}',
            "",
            LIVE_IAM_TF.read_text(),
            count=1,
            flags=re.DOTALL | re.MULTILINE,
        )
        with tempfile.TemporaryDirectory() as tmp:
            violations = check_file(_write(Path(tmp), broken))

        self.assertTrue(
            any(
                "portal_dynamic_secret_accessor" in violation.reason
                for violation in violations
            )
        )

    def test_named_boundary_cannot_hide_an_authoritative_multi_member_binding(
        self,
    ) -> None:
        broken = (
            LIVE_IAM_TF.read_text()
            .replace(
                'resource "google_project_iam_member" "portal_dynamic_secret_accessor"',
                'resource "google_project_iam_binding" "portal_dynamic_secret_accessor"',
            )
            .replace(
                '  member  = "serviceAccount:${google_service_account.workload["portal"].email}"',
                '  members = ["serviceAccount:${google_service_account.workload["portal"].email}", "allUsers"]',
                1,
            )
        )
        with tempfile.TemporaryDirectory() as tmp:
            violations = check_file(_write(Path(tmp), broken))

        self.assertTrue(
            any(
                "portal_dynamic_secret_accessor" in violation.reason
                for violation in violations
            )
        )

    def test_live_iam_module_passes(self) -> None:
        # Live-state regression: only the exact #2083 dynamic boundary may
        # carry project-level Secret Manager permissions.
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
            for workload, roles in _parse_role_map(
                cls.text, "workload_project_roles"
            ).items()
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
        for _name, _line, body in _extract_resource_blocks(
            lines, _PROJECT_IAM_MEMBER_RE
        ):
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
                # objectViewer on the optional object-backed RAES package bucket
                # (#1567, gated on raes_package_bucket_name).
                "portal": {"roles/storage.objectAdmin", "roles/storage.objectViewer"},
                "workers": {"roles/storage.objectViewer"},
                "provisioner": {
                    "roles/storage.objectViewer",
                    "roles/storage.objectAdmin",
                },
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
                re.compile(
                    r'^\s*resource\s+"google_secret_manager_secret_iam_member"\s+"([^"]+)"'
                ),
            )
            if name == "workload_secret_readers"
        ]
        self.assertEqual(len(reader_blocks), 1)
        self.assertRegex(
            reader_blocks[0], r'role\s*=\s*"roles/secretmanager\.secretAccessor"'
        )

    def test_only_guacamole_db_is_excluded_from_named_secrets(self) -> None:
        match = re.search(
            r"runtime_secret_reader_keys\s*=\s*\[for key in keys\(var\.runtime_secret_ids\)"
            r"\s*:\s*key\s+if\s+(.+?)\]",
            self.text,
        )
        self.assertIsNotNone(match)
        self.assertEqual(match.group(1).strip(), 'key != "guacamole-db"')

    def test_literal_project_secret_grants_are_conditioned_portal_reads_only(
        self,
    ) -> None:
        self.assertEqual(
            self.literal_project_grants,
            {("portal", "roles/secretmanager.secretAccessor")},
        )
        self.assertIn("local.portal_dynamic_read_condition", self.text)
        self.assertIn("local.legacy_participant_secret_condition", self.text)
        self.assertIn("local.legacy_raes_directory_name_condition", self.text)
        self.assertIn("resource.name.extract", self.text)
        self.assertEqual(check_paths(sorted(LIVE_IAM_DIR.glob("*.tf"))), [])

    def test_legacy_portal_condition_excludes_raes_directory_account_password(
        self,
    ) -> None:
        self.assertIn(
            "shifter-range-{range_scope}-raes-domain-') == ''",
            self.text,
        )
        self.assertIn(
            "((${local.legacy_raes_directory_name_condition})",
            self.text,
        )
        self.assertNotIn("legacy_participant_suffix_condition", self.text)

    def test_range_host_holds_only_logging_and_monitoring_no_storage(self) -> None:
        # ADR-008-R9 / #1644 effective-permission oracle: the participant-reachable
        # range-host SA carries exactly logging + monitoring writes and no
        # project-level Cloud Storage role of any kind (its tarball read moved to a
        # provisioner-minted signed URL).
        range_host_roles: set[str] = set()
        for _name, _line, body in _extract_resource_blocks(
            self.lines, _PROJECT_IAM_MEMBER_RE
        ):
            if _RANGE_HOST_MEMBER_RE.search(body):
                range_host_roles.update(_resource_granted_roles(body))
        self.assertEqual(
            range_host_roles,
            {"roles/logging.logWriter", "roles/monitoring.metricWriter"},
        )
        for role in range_host_roles:
            self.assertFalse(
                role.startswith("roles/storage."),
                f"range host must hold no project storage role, found {role}",
            )


if __name__ == "__main__":
    unittest.main()
