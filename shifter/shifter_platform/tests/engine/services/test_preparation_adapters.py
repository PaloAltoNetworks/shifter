"""Private adapter installation requires distinct authority and immutable grants."""

from copy import deepcopy

import pytest
from django.contrib.auth.models import Permission, User

from engine.models import PreparationAdapter, PreparationGrant
from engine.services import install_preparation_adapter, set_preparation_adapter_state
from shared.exceptions import ValidationError
from shared.preparation_grant import PreparationGrantConfiguration
from tests.shared.raes.test_preparation_contract import manifest_payload
from tests.shared.test_preparation_grant import grant_configuration

pytestmark = pytest.mark.django_db


@pytest.fixture
def administrator():
    actor = User.objects.create_user(username="adapter-admin")
    actor.user_permissions.add(Permission.objects.get(codename="manage_preparation_adapters"))
    return actor


@pytest.fixture
def grant():
    configuration = PreparationGrantConfiguration.model_validate(grant_configuration())
    return PreparationGrant.objects.create(
        scope_digest=configuration.scope_digest,
        configuration_digest=configuration.digest,
        configuration=configuration.model_dump(mode="json"),
        active=True,
    )


def test_staff_and_content_authority_do_not_install_code(grant):
    actor = User.objects.create_user(username="staff", is_staff=True)
    with pytest.raises(ValidationError):
        install_preparation_adapter(actor, grant.pk, manifest_payload())
    assert not PreparationAdapter.objects.exists()


def test_inactive_administrator_cannot_install_code(administrator, grant):
    administrator.is_active = False
    administrator.save()
    with pytest.raises(ValidationError):
        install_preparation_adapter(administrator, grant.pk, manifest_payload())
    assert not PreparationAdapter.objects.exists()


def test_install_and_exact_retry_preserve_one_immutable_version(administrator, grant):
    first = install_preparation_adapter(administrator, grant.pk, manifest_payload())
    retry = install_preparation_adapter(administrator, grant.pk, manifest_payload())
    assert retry.id == first.id
    assert PreparationAdapter.objects.count() == 1
    assert first.manifest["worker_image"].endswith("b" * 64)


def test_same_version_cannot_change_worker_image(administrator, grant):
    first = install_preparation_adapter(administrator, grant.pk, manifest_payload())
    changed = manifest_payload()
    changed["worker_image"] = "registry.example/private/changed@sha256:" + "f" * 64
    with pytest.raises(ValidationError):
        install_preparation_adapter(administrator, grant.pk, changed)
    assert PreparationAdapter.objects.get(pk=first.id).manifest["worker_image"].endswith("b" * 64)


def test_registry_access_does_not_authorize_an_unapproved_cloud_worker(administrator, grant):
    changed = dict(manifest_payload(), worker_image="registry.example/private/unknown@sha256:" + "f" * 64)
    with pytest.raises(ValidationError):
        install_preparation_adapter(administrator, grant.pk, changed)
    assert not PreparationAdapter.objects.exists()


def test_upgrade_installs_new_version_and_retains_old_manifest(administrator, grant):
    old = install_preparation_adapter(administrator, grant.pk, manifest_payload())
    changed = deepcopy(manifest_payload())
    changed["version"] = "2"
    changed["worker_image"] = "registry.example/private/build@sha256:" + "f" * 64
    new = install_preparation_adapter(administrator, grant.pk, changed)
    assert old.id != new.id
    assert PreparationAdapter.objects.get(pk=old.id).manifest["worker_image"].endswith("b" * 64)


@pytest.mark.parametrize("state", ["disabled", "retired"])
def test_lifecycle_retains_executable_identity_for_cleanup(administrator, grant, state):
    old = install_preparation_adapter(administrator, grant.pk, manifest_payload())
    changed = set_preparation_adapter_state(administrator, old.id, state)
    assert changed.state == state
    assert changed.manifest_digest == old.manifest_digest
    assert changed.grant_id == grant.pk


def test_retired_version_cannot_be_reactivated(administrator, grant):
    old = install_preparation_adapter(administrator, grant.pk, manifest_payload())
    set_preparation_adapter_state(administrator, old.id, "retired")
    with pytest.raises(ValidationError):
        set_preparation_adapter_state(administrator, old.id, "enabled")


def test_disabled_grant_and_missing_permission_fail_before_install(administrator, grant):
    grant.active = False
    grant.save()
    with pytest.raises(ValidationError):
        install_preparation_adapter(administrator, grant.pk, manifest_payload())
    grant.active = True
    grant.configuration["permissions"] = ["private-artifact-storage"]
    grant.configuration_digest = PreparationGrantConfiguration.model_validate(grant.configuration).digest
    grant.save()
    with pytest.raises(ValidationError):
        install_preparation_adapter(administrator, grant.pk, manifest_payload())
    assert not PreparationAdapter.objects.exists()


def test_audit_failure_rolls_back_executable_registration(administrator, grant, monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr("engine.services._preparation_adapters.audit_log", fail)
    with pytest.raises(RuntimeError):
        install_preparation_adapter(administrator, grant.pk, manifest_payload())
    assert not PreparationAdapter.objects.exists()


def test_installer_cannot_choose_an_unapproved_verifier(administrator, grant):
    raw = manifest_payload()
    raw["verifier_image"] = "registry.example/private/forged-verifier@sha256:" + "f" * 64
    with pytest.raises(ValidationError):
        install_preparation_adapter(administrator, grant.pk, raw)
    assert not PreparationAdapter.objects.exists()


def test_installer_cannot_pull_from_an_ungranted_registry(administrator, grant):
    raw = manifest_payload()
    raw["worker_image"] = "foreign.example/private/build@sha256:" + "b" * 64
    with pytest.raises(ValidationError):
        install_preparation_adapter(administrator, grant.pk, raw)
    assert not PreparationAdapter.objects.exists()


def test_mutated_grant_or_backend_scope_cannot_be_used(administrator, grant):
    grant.configuration["max_disk_gb"] = 80
    grant.save()
    with pytest.raises(ValidationError):
        install_preparation_adapter(administrator, grant.pk, manifest_payload())
    grant.configuration_digest = PreparationGrantConfiguration.model_validate(grant.configuration).digest
    grant.scope_digest = "sha256:" + "f" * 64
    grant.save()
    with pytest.raises(ValidationError):
        install_preparation_adapter(administrator, grant.pk, manifest_payload())
    assert not PreparationAdapter.objects.exists()
