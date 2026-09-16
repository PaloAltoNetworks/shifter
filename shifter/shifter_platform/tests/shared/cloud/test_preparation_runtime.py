"""Preparation uses dedicated identities with the neutral Job lifecycle."""

from uuid import uuid4

import pytest

from shared.cloud.preparation_runtime import preparation_task
from shared.preparation_grant import PreparationGrantConfiguration
from tests.shared.test_preparation_grant import grant_configuration


@pytest.mark.parametrize(
    "phase,account",
    [("verify-inputs", "verifier"), ("build", "builder"), ("verify-output", "verifier"), ("cleanup", "cleanup")],
)
def test_phase_uses_its_separately_granted_identity_and_hardening(phase, account):
    grant = PreparationGrantConfiguration.model_validate(grant_configuration())
    image = (
        grant.cleanup_image
        if account == "cleanup"
        else (grant.approved_worker_images[0] if account == "builder" else grant.approved_verifier_images[0])
    )
    task = preparation_task(grant, phase, image, uuid4(), uuid4())
    assert task.profile.service_account_name == f"preparation-{account}"
    assert task.profile.backoff_limit == 0
    assert task.profile.node_selector == {"iam.gke.io/gke-metadata-server-enabled": "true"}
    assert task.profile.active_deadline_seconds == grant.max_duration_seconds
    assert task.profile.image_pull_secrets == ("private-registry",)
    assert task.profile.hardening.run_as_uid == 1000
    assert task.profile.hardening.writable_mounts == (("tmp", "/tmp", "Memory", "64Mi"),)  # noqa: S108 - pod mount
    assert task.expected_identity["image"] == image
    assert task.expected_identity["command"] == []


def test_builder_cannot_dispatch_using_verifier_executable_or_cleanup_role():
    grant = PreparationGrantConfiguration.model_validate(grant_configuration())
    with pytest.raises(ValueError):
        preparation_task(grant, "build", grant.approved_verifier_images[0], uuid4(), uuid4())
    with pytest.raises(ValueError):
        preparation_task(grant, "cleanup", grant.approved_worker_images[0], uuid4(), uuid4())


def test_job_identity_is_stable_and_contains_no_private_package_metadata():
    grant = PreparationGrantConfiguration.model_validate(grant_configuration())
    operation, attempt = uuid4(), uuid4()
    first = preparation_task(grant, "build", grant.approved_worker_images[0], operation, attempt)
    retry = preparation_task(grant, "build", grant.approved_worker_images[0], operation, attempt)
    assert first.task_ref == retry.task_ref
    assert first.task_ref.startswith("shifter-preparation/artifact-preparation-")


def test_composition_root_refuses_foreign_tenant_project(settings):
    from shared.cloud import get_preparation_task

    grant = PreparationGrantConfiguration.model_validate(grant_configuration())
    settings.CLOUD_PROVIDER = "gcp"
    settings.GCP_PROJECT_ID = "foreign-project"
    with pytest.raises(ValueError):
        get_preparation_task(grant, "build", grant.approved_worker_images[0], uuid4(), uuid4())
    settings.GCP_PROJECT_ID = grant.project_id
    assert get_preparation_task(grant, "build", grant.approved_worker_images[0], uuid4(), uuid4()).grant == grant
