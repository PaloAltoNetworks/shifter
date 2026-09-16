"""The post-setup add-on has separate, narrowly scoped cloud authorities."""

from shared.cloud.preparation_cloud_installation import render_preparation_terraform
from tests.shared.cloud.test_preparation_installation import installation_fixture


def test_workers_cannot_read_platform_secrets_or_impersonate_other_identities():
    configuration = installation_fixture()
    resources = render_preparation_terraform(configuration)["resource"]
    for role in resources["google_project_iam_custom_role"].values():
        assert all(permission.startswith("compute.") for permission in role["permissions"])
        assert not any("setIamPolicy" in permission or "ExternalIp" in permission for permission in role["permissions"])
    secrets = resources["google_secret_manager_secret_iam_member"].values()
    assert len(secrets) == 3
    assert all(item["role"] == "roles/secretmanager.secretAccessor" for item in secrets)
    assert all(item["member"] == "${google_service_account.controller.member}" for item in secrets)


def test_only_cleanup_identity_can_delete_owned_resources_and_cannot_create():
    resources = render_preparation_terraform(installation_fixture())["resource"]
    roles = resources["google_project_iam_custom_role"]
    for name, role in roles.items():
        if name == "cleanup_mutate":
            assert set(role["permissions"]) == {
                "compute.instances.delete",
                "compute.disks.delete",
                "compute.images.delete",
            }
        else:
            assert not any(permission.endswith(".delete") for permission in role["permissions"])
    bindings = resources["google_project_iam_member"]
    assert "resource.name.startsWith" in bindings["cleanup_mutate"]["condition"][0]["expression"]
    assert all("cleanup" not in key or "create" not in key for key in bindings)
    assert all("controller" not in key or key == "controller_read" for key in bindings)


def test_network_has_no_nat_or_peering_and_subnet_use_is_resource_scoped():
    resources = render_preparation_terraform(installation_fixture())["resource"]
    assert not any("router" in kind or "peering" in kind for kind in resources)
    assert resources["google_compute_network"]["preparation"]["auto_create_subnetworks"] is False
    assert resources["google_compute_subnetwork"]["preparation"]["ip_cidr_range"] == "10.240.0.0/24"
    assert set(resources["google_compute_subnetwork_iam_member"]) == {"builder", "verifier"}
    for binding in resources["google_compute_subnetwork_iam_member"].values():
        assert binding["role"] == "${google_project_iam_custom_role.subnet_use.name}"
        assert binding["subnetwork"] == "${google_compute_subnetwork.preparation.name}"


def test_builder_can_label_candidate_images_with_ownership_without_granting_verifiers_image_mutation():
    resources = render_preparation_terraform(installation_fixture())["resource"]
    roles = resources["google_project_iam_custom_role"]
    # GCE images.insert separately authorizes setLabels when the candidate
    # carries the labels required for independent verification and cleanup.
    assert "compute.images.setLabels" in roles["builder_mutate"]["permissions"]
    assert "compute.images.setLabels" not in roles["verifier_mutate"]["permissions"]
    binding = resources["google_project_iam_member"]["builder_mutate"]
    assert "/global/images/prep-" in binding["condition"][0]["expression"]
