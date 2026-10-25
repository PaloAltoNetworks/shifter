"""Tenant binding UX reads real compiled pack targets without dispatching a range."""

import pytest
from django.contrib.auth.models import User
from rest_framework.test import APIClient

from cms.models import RaesPackageSource
from cms.scenarios.pack_validation import pack_digest
from engine.models import Range, RuntimePluginInstallation, RuntimePluginPackBinding
from engine.services import install_runtime_plugin
from tests.cms.test_runtime_plugins import manifest as manifest
from tests.cms.test_runtime_plugins import tenant as tenant

pytestmark = pytest.mark.django_db


@pytest.fixture
def pack_api(tenant, manifest, make_pack, tmp_path, settings):
    actor, organization = tenant
    root = make_pack(tmp_path / "example")
    settings.RAES_PACKAGE_ROOT = str(tmp_path)
    source = RaesPackageSource.objects.create(
        scenario_id="example",
        contract_kind="raes",
        contract_profile="shifter",
        package_ref="example",
        package_version="1",
        package_digest=pack_digest(root),
        registered_by=actor,
        conformance_status="passed",
    )
    installed = install_runtime_plugin(actor, organization.uuid, manifest)
    RuntimePluginInstallation.objects.filter(pk=installed.id).update(state="ready")
    client = APIClient()
    client.force_authenticate(user=actor)
    base = f"/api/v1/cms/organizations/{organization.uuid}/plugin-packs/"
    return client, base, installed, source, root


def test_admin_binds_an_installed_adapter_using_verified_guest_choices(pack_api):
    client, base, installed, source, _root = pack_api
    response = client.get(base)
    assert response.status_code == 200
    assert response.json()["count"] == 1
    assert response.json()["results"][0]["binding"] is None
    detail = client.get(base + "example/")
    assert detail.status_code == 200
    targets = detail.json()["targets"]
    assert targets and all(row["os_family"] == "linux" for row in targets)
    response = client.post(
        base + "example/",
        {
            "installation_id": str(installed.id),
            "pack_digest": source.package_digest,
            "bindings": {"targets": {"server": targets[0]["address"]}},
        },
        format="json",
    )
    assert response.status_code == 200
    assert response.json()["enabled"] is True
    assert client.get(base).json()["results"][0]["binding"]["installation_id"] == str(installed.id)
    assert not Range.objects.exists()


def test_admin_binds_a_provider_image_without_hosting_access(pack_api):
    client, base, installed, source, _root = pack_api
    target = client.get(base + "example/").json()["targets"][0]["address"]
    response = client.post(
        base + "example/",
        {
            "installation_id": str(installed.id),
            "pack_digest": source.package_digest,
            "bindings": {
                "targets": {"server": target},
                "image_profiles": {
                    "server": {
                        "provider": "gcp",
                        "image_kind": "machine-image",
                        "image_ref": "projects/example/global/machineImages/nested-host-v1",
                        "machine_type": "e2-standard-8",
                        "bootstrap_capability": "preconfigured-machine-host",
                        "management_ssh_username": "host-admin",
                        "participant_container_name": "participant-desktop",
                        "participant_username": "student",
                        "participant_readiness_contract": "participant-readiness/v1",
                        "participant_readiness_manifest_sha256": "a" * 64,
                        "allow_public_web_egress": True,
                    }
                },
            },
        },
        format="json",
    )
    assert response.status_code == 200
    assert response.json()["bindings"]["image_profiles"]["server"]["provider"] == "gcp"
    assert response.json()["bindings"]["image_profiles"]["server"]["allow_public_web_egress"] is True


def test_admin_binds_a_prepromoted_directory_image(pack_api):
    client, base, installed, source, _root = pack_api
    target = client.get(base + "example/").json()["targets"][0]["address"]
    response = client.post(
        base + "example/",
        {
            "installation_id": str(installed.id),
            "pack_digest": source.package_digest,
            "bindings": {
                "targets": {"server": target},
                "image_profiles": {
                    "server": {
                        "provider": "gcp",
                        "image_ref": "projects/example/global/images/directory-v1",
                        "machine_type": "e2-standard-4",
                        "disk_size_gb": 100,
                        "disk_type": "pd-ssd",
                        "bootstrap_capability": "prepromoted-domain-controller",
                        "domain_dns_name": "example.test",
                        "domain_netbios_name": "EXAMPLE",
                    }
                },
            },
        },
        format="json",
    )
    assert response.status_code == 200
    profile = response.json()["bindings"]["image_profiles"]["server"]
    assert profile["bootstrap_capability"] == "prepromoted-domain-controller"
    assert profile["domain_dns_name"] == "example.test"


def test_pack_access_and_configuration_require_tenant_admin_even_for_staff(pack_api):
    client, base, installed, source, _root = pack_api
    outsider = User.objects.create_user(username="outsider-staff", is_staff=True)
    client.force_authenticate(user=outsider)
    assert client.get(base).status_code == 403
    assert client.get(base + "example/").status_code == 403
    assert (
        client.post(
            base + "example/",
            {
                "installation_id": str(installed.id),
                "pack_digest": source.package_digest,
                "bindings": {"targets": {"server": "node.host"}},
            },
            format="json",
        ).status_code
        == 403
    )
    assert not RuntimePluginPackBinding.objects.exists()


@pytest.mark.parametrize("invalid", ["digest", "guest", "authority", "mutated-pack"])
def test_binding_rejects_stale_or_untrusted_pack_configuration(pack_api, invalid):
    client, base, installed, source, root = pack_api
    detail = client.get(base + "example/").json()
    body = {
        "installation_id": str(installed.id),
        "pack_digest": source.package_digest,
        "bindings": {"targets": {"server": detail["targets"][0]["address"]}},
    }
    if invalid == "digest":
        body["pack_digest"] = "sha256:" + "c" * 64
    elif invalid == "guest":
        body["bindings"]["targets"]["server"] = "node.foreign"
    elif invalid == "authority":
        body["organization_uuid"] = str(installed.organization_uuid)
    else:
        (root / "docs" / "concepts.md").write_text("Changed pack", encoding="utf-8")
    assert client.post(base + "example/", body, format="json").status_code == 400
    assert not RuntimePluginPackBinding.objects.exists()
