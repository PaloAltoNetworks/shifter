"""Application grants require actual role, network and Kubernetes observations."""

import pytest
from django.contrib.auth.models import Permission, User

from engine.models import PreparationGrant
from engine.services._preparation_grants import activate_preparation_grant, revoke_preparation_grant
from shared.exceptions import ValidationError
from tests.shared.cloud.test_preparation_cloud_readback import cloud_observations
from tests.shared.cloud.test_preparation_installation_readback import observed_fixture

pytestmark = pytest.mark.django_db


@pytest.fixture
def operator():
    user = User.objects.create_user("cloud-operator")
    user.user_permissions.add(Permission.objects.get(codename="manage_preparation_grants"))
    return user


@pytest.fixture
def observation():
    configuration, kube = observed_fixture()
    cloud = cloud_observations(configuration)
    return configuration, cloud, kube


def activate(user, observation):
    configuration, cloud, kube = observation
    return activate_preparation_grant(
        user,
        configuration.model_dump(mode="json"),
        cloud_reader=cloud.get,
        kubernetes_reader=lambda resource: kube.get((resource["kind"], resource["metadata"]["name"])),
    )


def test_adapter_administration_cannot_create_cloud_authority(observation):
    user = User.objects.create_user("adapter-admin")
    user.user_permissions.add(Permission.objects.get(codename="manage_preparation_adapters"))
    accessed = []
    with pytest.raises(ValidationError):
        activate_preparation_grant(user, observation[0].model_dump(mode="json"), cloud_reader=accessed.append)
    assert not accessed and not PreparationGrant.objects.exists()


@pytest.mark.parametrize("failure", ["cloud", "kubernetes", "wrong-proof"])
def test_missing_or_foreign_installation_proof_cannot_activate_grant(operator, observation, failure):
    configuration, cloud, kube = observation
    if failure == "cloud":
        cloud.pop("role:builder_create")
    elif failure == "kubernetes":
        kube[("Deployment", configuration.controller_name)]["status"]["readyReplicas"] = 0
    else:
        kube[("ConfigMap", "preparation-installation")]["data"]["installation_digest"] = "sha256:" + "0" * 64
    with pytest.raises(ValidationError):
        activate(operator, observation)
    assert not PreparationGrant.objects.exists()


def test_activation_retry_records_verified_installation_and_revocation_keeps_pins(operator, observation):
    configuration = observation[0]
    identity = activate(operator, observation)
    assert activate(operator, observation) == identity
    row = PreparationGrant.objects.get(pk=identity)
    assert row.active and row.installation_digest == configuration.digest and row.verified_at
    assert row.installation == configuration.model_dump(mode="json")
    revoke_preparation_grant(operator, identity)
    row.refresh_from_db()
    assert not row.active and row.configuration_digest == configuration.grant.digest
    assert row.installation_digest == configuration.digest


def test_unauthorized_actor_cannot_revoke_an_active_grant(operator, observation):
    identity = activate(operator, observation)
    unauthorized = User.objects.create_user("unauthorized-grant-revoker")

    with pytest.raises(ValidationError):
        revoke_preparation_grant(unauthorized, identity)

    assert PreparationGrant.objects.get(pk=identity).active is True


def test_installation_cannot_retarget_an_existing_scope(operator, observation):
    configuration = observation[0]
    PreparationGrant.objects.create(
        scope_digest=configuration.grant.scope_digest, configuration_digest="sha256:" + "0" * 64, configuration={}
    )
    with pytest.raises(ValidationError, match="namespace"):
        activate(operator, observation)


def test_verified_controller_release_upgrade_preserves_the_worker_grant(operator, observation):
    original = observation[0]
    identity = activate(operator, observation)
    upgraded = original.model_copy(update={"controller_image": "registry.example/private/portal@sha256:" + "8" * 64})
    _, kube = observed_fixture(upgraded)
    assert activate(operator, (upgraded, cloud_observations(upgraded), kube)) == identity
    row = PreparationGrant.objects.get(pk=identity)
    assert row.configuration == original.grant.model_dump(mode="json")
    assert row.configuration_digest == original.grant.digest
    assert row.installation_digest == upgraded.digest
    assert row.installation["controller_image"] == upgraded.controller_image


def test_controller_release_upgrade_cannot_change_network_authority(operator, observation):
    original = observation[0]
    identity = activate(operator, observation)
    changed = original.model_copy(update={"network_cidr": "10.241.0.0/24"})
    _, kube = observed_fixture(changed)
    with pytest.raises(ValidationError, match="namespace"):
        activate(operator, (changed, cloud_observations(changed), kube))
    assert PreparationGrant.objects.get(pk=identity).installation_digest == original.digest
