"""Cloud grants have one closed parser and preserve independent verifier authority."""

import pytest

from shared.preparation_grant import PreparationGrantConfiguration


def grant_configuration():
    from tests.shared.raes.test_preparation_inputs import bound_input_fixture

    binding = bound_input_fixture()
    return {
        "protocol": "shifter.preparation-grant/v1",
        "backend": "gce",
        "project_id": "test-project",
        "zone": "us-central1-a",
        "namespace": "shifter-preparation",
        "subnetwork": "projects/test-project/regions/us-central1/subnetworks/preparation",
        "builder_service_account": "preparation-builder",
        "verifier_service_account": "preparation-verifier",
        "cleanup_service_account": "preparation-cleanup",
        "cleanup_image": "registry.example/private/cleanup@sha256:" + "9" * 64,
        "trusted_input_bindings": {binding.lock.trust_policy_ref: [binding.digest]},
        "image_pull_secrets": ["private-registry"],
        "registry_prefixes": ["registry.example/private/"],
        "approved_verifier_images": ["registry.example/private/verify@sha256:" + "c" * 64],
        "approved_worker_images": [
            "registry.example/private/build@sha256:" + "b" * 64,
            "registry.example/private/build@sha256:" + "f" * 64,
        ],
        "permissions": ["gce-image-build", "private-artifact-storage"],
        "worker_endpoint": "https://portal.example/api/v1/cms/artifact-preparation/workers/",
        "max_duration_seconds": 3600,
        "max_concurrent_operations": 2,
        "max_disk_gb": 40,
        "scanner_image": "projects/test-project/global/images/approved-scanner",
        "scanner_image_id": "123456789",
    }


def test_valid_grant_binds_complete_policy_and_backend_scope():
    raw = grant_configuration()
    configuration = PreparationGrantConfiguration.model_validate(raw)
    changed = grant_configuration()
    changed["max_duration_seconds"] = 1800
    replacement = PreparationGrantConfiguration.model_validate(changed)
    assert replacement.digest != configuration.digest
    assert replacement.scope_digest == configuration.scope_digest
    changed["project_id"] = "foreign-project"
    changed["subnetwork"] = "projects/foreign-project/regions/us-central1/subnetworks/preparation"
    assert PreparationGrantConfiguration.model_validate(changed).scope_digest != configuration.scope_digest


def test_explicit_standard_https_port_is_allowed():
    raw = grant_configuration()
    raw["worker_endpoint"] = "https://portal.example:443/api/v1/cms/artifact-preparation/workers/"
    assert PreparationGrantConfiguration.model_validate(raw).worker_endpoint == raw["worker_endpoint"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("namespace", "shifter-provisioner"),
        ("verifier_service_account", "preparation-builder"),
        ("max_duration_seconds", 999999),
        ("max_concurrent_operations", 0),
        ("max_disk_gb", True),
        ("worker_endpoint", "http://portal.example/"),
        ("worker_endpoint", "https://user:password@portal.example/"),
        ("worker_endpoint", "https://portal.example/?token=private"),
        ("worker_endpoint", "https://portal.example:8443/api/v1/cms/artifact-preparation/workers/"),
        ("worker_endpoint", "https://portal.example:99999/api/v1/cms/artifact-preparation/workers/"),
        ("subnetwork", "projects/foreign-project/regions/us-central1/subnetworks/private"),
        ("registry_prefixes", ["registry.example/private"]),
        ("approved_verifier_images", ["registry.example/private/verify:latest"]),
        ("image_pull_secrets", ["foreign/registry"]),
    ],
)
def test_invalid_identity_authority_endpoint_or_budget_is_not_a_grant(field, value):
    raw = grant_configuration()
    raw[field] = value
    with pytest.raises(ValueError):
        PreparationGrantConfiguration.model_validate(raw)


def test_unsupported_grant_fields_do_not_become_worker_configuration():
    raw = grant_configuration()
    raw["env"] = {"DATABASE_PASSWORD": "forbidden"}
    with pytest.raises(ValueError):
        PreparationGrantConfiguration.model_validate(raw)
