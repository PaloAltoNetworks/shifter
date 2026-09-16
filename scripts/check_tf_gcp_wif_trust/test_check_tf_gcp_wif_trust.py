"""Regression checks for generic source enforcement and resolved apply policy."""

import json
import re
import tempfile
import unittest
from pathlib import Path

from .check_tf_gcp_wif_trust import check_file
from .test_resolved_plan import ResolvedPlanTests  # noqa: F401 - existing CI entry point

MODULE = (
    Path(__file__).resolve().parents[2]
    / "platform/terraform/gcp/modules/cicd-oidc-identity"
)


class GenericSourceTests(unittest.TestCase):
    def check_changed(self, before, after, filename="main.tf"):
        sources = {path.name: path.read_text() for path in MODULE.glob("*.tf")}
        self.assertIn(before, "\n".join(sources.values()))
        with tempfile.TemporaryDirectory() as directory:
            module = Path(directory) / MODULE.name
            module.mkdir()
            for name, source in sources.items():
                (module / name).write_text(source.replace(before, after))
            return check_file(module / filename)

    def variable_block(self, name):
        source = (MODULE / "variables.tf").read_text()
        match = re.search(r'variable "' + name + r'" \{.*?^\}', source, re.S | re.M)
        self.assertIsNotNone(match)
        return match.group()

    def check_default_changed(self, name, values):
        block = self.variable_block(name)
        changed, count = re.subn(
            r"default\s*=\s*\[.*?]",
            "default = " + json.dumps(values),
            block,
            flags=re.S,
        )
        self.assertEqual(count, 1)
        return self.check_changed(block, changed)

    def assert_violation(self, violations, reason):
        self.assertTrue(
            any(reason in violation.reason for violation in violations),
            [v.reason for v in violations],
        )

    def test_current_generic_module_passes(self):
        self.assertEqual(
            [error for path in MODULE.glob("*.tf") for error in check_file(path)], []
        )

    def test_immutable_subject_ids_cannot_be_substituted(self):
        self.assertTrue(self.check_changed(
            "${var.github_org}@${var.github_owner_id}", "${var.github_org}@999"
        ))
        self.assertTrue(self.check_changed(
            "${var.github_repo}@${var.github_repository_id}", "${var.github_repo}@999"
        ))

    def test_bypassing_a_claim_gate_is_rejected(self):
        for claim in (
            "sub",
            "ref",
            "workflow_ref",
            "repository_id",
            "repository_owner_id",
        ):
            with self.subTest(claim=claim):
                self.assertTrue(
                    self.check_changed(
                        f"assertion.{claim} ==", f"true || assertion.{claim} =="
                    )
                )

    def test_issuer_or_principal_widening_is_rejected(self):
        for before, after in [
            ("https://token.actions.githubusercontent.com", "https://attacker.example"),
            (
                "principal://iam.googleapis.com/projects/",
                "principalSet://iam.googleapis.com/projects/",
            ),
            (
                "local.purpose_subject_principals.deploy",
                "local.purpose_subject_principals.build",
            ),
            (
                "local.service_account_names.destroy",
                "local.service_account_names.deploy",
            ),
        ]:
            with self.subTest(after=after):
                self.assertTrue(self.check_changed(before, after))

    def test_project_iam_requires_the_configured_project(self):
        self.assertTrue(
            self.check_changed("= var.project_id", "= var.unapproved_project_id")
        )

    def test_checkov_waiver_is_rejected(self):
        self.assertTrue(
            self.check_changed(
                "# GitHub Actions",
                "# checkov:skip=CKV_GCP_125:waiver\n# GitHub Actions",
            )
        )

    def test_broad_roles_are_rejected(self):
        for purpose in ("deploy", "destroy"):
            for role in (
                "roles/compute.admin",
                "roles/compute.imageAdmin",
                "roles/compute.instanceAdmin.v1",
                "roles/compute.storageAdmin",
                "roles/storage.admin",
                "roles/editor",
                "roles/owner",
            ):
                with self.subTest(purpose=purpose, role=role):
                    self.assert_violation(
                        self.check_default_changed(purpose + "_roles", [role]),
                        purpose
                        + " role set contains release-evidence-bypassing broad roles",
                    )

    def test_validation_cannot_create_delete_or_promote_images(self):
        for permission in (
            "compute.images.create",
            "compute.images.delete",
            "compute.images.deprecate",
        ):
            with self.subTest(permission=permission):
                self.assert_violation(
                    self.check_default_changed("validate_permissions", [permission]),
                    "validate permission set crosses image-build/promotion authority",
                )

    def test_shared_legacy_platform_roles_are_rejected(self):
        source = (MODULE / "variables.tf").read_text()
        addition = '\nvariable "platform_roles" {\n  default = ["roles/viewer"]\n}\n'
        self.assert_violation(
            self.check_changed(source, source + addition),
            "platform lifecycle identities must use separate deploy_roles and destroy_roles",
        )

    def test_validate_broad_roles_are_rejected(self):
        for role in (
            "roles/compute.admin",
            "roles/storage.admin",
            "roles/cloudbuild.builds.editor",
            "roles/iam.serviceAccountAdmin",
            "roles/resourcemanager.projectIamAdmin",
        ):
            with self.subTest(role=role):
                self.assert_violation(
                    self.check_default_changed("validate_roles", [role]),
                    "validate role set contains forbidden broad roles",
                )

    def test_build_roles_cannot_have_project_wide_storage_admin(self):
        self.assert_violation(
            self.check_default_changed("build_roles", ["roles/storage.admin"]),
            "build role set must use resource-scoped GCS grants",
        )

    def test_promote_permissions_cannot_manage_other_capabilities(self):
        for permission in (
            "compute.instances.create",
            "storage.objects.get",
            "cloudbuild.builds.create",
            "iam.serviceAccounts.actAs",
        ):
            with self.subTest(permission=permission):
                self.assert_violation(
                    self.check_default_changed("promote_permissions", [permission]),
                    "promote permission set crosses instance/storage/build/IAM authority",
                )

    def test_release_scan_cannot_have_a_project_wide_role(self):
        resource = (MODULE / "main.tf").read_text()
        addition = '\nresource "google_project_iam_member" "invalid_scan_role" {\n  project = var.project_id\n  role = "roles/viewer"\n  member = "serviceAccount:${local.service_account_emails.release_scan}"\n}\n'
        self.assert_violation(
            self.check_changed(resource, resource + addition),
            "release-scan identity must have no project-wide IAM role",
        )

    def test_deploy_and_destroy_role_sets_must_be_independently_derived(self):
        default = re.search(
            r"default\s*=\s*(\[.*?])", self.variable_block("destroy_roles"), re.S
        ).group(1)
        values = json.loads(default.replace(",\n  ]", "\n  ]"))
        self.assert_violation(
            self.check_default_changed("deploy_roles", values),
            "deploy and destroy role sets must be independently derived",
        )

    def test_destroy_role_set_cannot_manage_project_services(self):
        self.assert_violation(
            self.check_default_changed(
                "destroy_roles", ["roles/serviceusage.serviceUsageAdmin"]
            ),
            "destroy role set must not enable or disable project services",
        )

    def test_missing_lifecycle_role_variables_is_rejected(self):
        for names in (
            ("deploy_roles",),
            ("destroy_roles",),
            ("deploy_roles", "destroy_roles"),
        ):
            with self.subTest(names=names):
                before = (MODULE / "variables.tf").read_text()
                after = before
                for name in names:
                    after = after.replace(
                        f'variable "{name}"', f'variable "unused_{name}"'
                    )
                self.assert_violation(
                    self.check_changed(before, after),
                    "platform lifecycle identities must use separate deploy_roles and destroy_roles",
                )

    def test_purpose_module_missing_explicit_output_is_rejected(self):
        for name in (
            "workload_identity_provider",
            "packer_build_service_account_email",
            "packer_validate_service_account_email",
            "packer_promote_service_account_email",
            "release_scan_service_account_email",
            "deploy_service_account_email",
            "destroy_service_account_email",
        ):
            with self.subTest(name=name):
                self.assert_violation(
                    self.check_changed(
                        f'output "{name}"', f'output "removed_{name}"', "outputs.tf"
                    ),
                    "GCP CI identity module must publish explicit purpose outputs; missing",
                )


if __name__ == "__main__":
    unittest.main()
