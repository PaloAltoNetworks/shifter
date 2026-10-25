"""The IAM guard rejects model-identity escalation at its real HCL boundary."""

import pytest

from scripts.check_tf_gcp_iam_resource_scope.check_tf_gcp_iam_resource_scope import (
    check_paths,
)


@pytest.mark.parametrize(
    "mutation", [None, "prefix", "condition", "project", "member", "role"]
)
def test_source_control_secret_access_requires_exact_owned_boundary(tmp_path, mutation):
    resource = """resource "google_project_iam_member" "model_source_control_read" {
  count = var.model_broker.enabled ? 1 : 0
  project = var.project_id
  role = "roles/secretmanager.secretAccessor"
  member = "serviceAccount:${google_service_account.workload["workers"].email}"
  condition {
    expression = "resource.name.startsWith('projects/${data.google_project.platform.number}/secrets/shifter-model-source-')"
  }
}"""
    edits = {
        "prefix": ("shifter-model-source-", ""),
        "condition": (
            "resource.name.startsWith('projects/${data.google_project.platform.number}/secrets/shifter-model-source-')",
            "true",
        ),
        "project": ("project = var.project_id", "project = var.other_project"),
        "member": ('workload["workers"]', 'workload["portal"]'),
        "role": ("roles/secretmanager.secretAccessor", "roles/secretmanager.admin"),
    }
    if mutation:
        resource = resource.replace(*edits[mutation])
    path = tmp_path / "model_broker.tf"
    path.write_text(resource)
    assert bool(check_paths([path])) == bool(mutation)


@pytest.mark.parametrize(
    "resource",
    [
        """resource "google_project_iam_member" "broker_tokens" {
      project = var.project_id
      role = "roles/iam.serviceAccountTokenCreator"
      member = "serviceAccount:${google_service_account.model_broker[0].email}"
    }""",
        """resource "google_service_account_iam_member" "broker_tokens" {
      service_account_id = "projects/-/serviceAccounts/foreign@example.iam.gserviceaccount.com"
      role = "roles/iam.serviceAccountTokenCreator"
      member = "serviceAccount:${google_service_account.model_broker[0].email}"
    }""",
        """resource "google_service_account_key" "model_key" {
      service_account_id = google_service_account.model_invocation["models-example"].name
    }""",
        """resource "google_project_iam_member" "invoke" {
      project = var.project_id
      role = "roles/aiplatform.user"
      member = "serviceAccount:${google_service_account.model_invocation[each.key].email}"
    }""",
    ],
)
def test_model_identity_cannot_receive_broad_authority(tmp_path, resource):
    path = tmp_path / "broker.tf"
    path.write_text(resource)
    assert check_paths([path]), "the guard accepted model identity escalation"


@pytest.mark.parametrize(
    "role,permission",
    [
        ("model_invoke", "aiplatform.endpoints.predict"),
        ("model_token", "iam.serviceAccounts.getAccessToken"),
    ],
)
@pytest.mark.parametrize("widen", [False, True])
def test_model_custom_roles_have_exact_permissions(tmp_path, role, permission, widen):
    import json

    permissions = [permission] + (["iam.serviceAccounts.signBlob"] if widen else [])
    path = tmp_path / "broker.tf"
    path.write_text(
        f'resource "google_project_iam_custom_role" "{role}" {{\n'
        f"  permissions = {json.dumps(permissions)}\n"
        "}\n"
    )
    violations = check_paths([path])
    if widen:
        assert len(violations) == 1
        assert (
            violations[0].reason == "model custom role exceeds its exact permission set"
        )
    else:
        assert violations == []
