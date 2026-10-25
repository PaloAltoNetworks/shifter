"""Tenant plugin installation authority, immutable identity and probe fencing."""

from dataclasses import asdict
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest
from django.contrib.auth.models import User
from django.db import connection
from django.utils import timezone
from rest_framework.test import APIClient
from shifter_adapter_sdk.runtime import InspectionResult

from engine.models import RuntimePluginInstallation
from engine.services import change_runtime_plugin, install_runtime_plugin, reconcile_runtime_plugins
from shared.exceptions import ValidationError
from workspaces.models import Organization, OrganizationMembership

pytestmark = pytest.mark.django_db


@pytest.fixture
def tenant():
    actor = User.objects.create_user(username="plugin-admin", is_staff=False)
    organization = Organization.objects.create(name="Example tenant")
    OrganizationMembership.objects.create(user=actor, organization=organization, role="admin")
    return actor, organization


@pytest.fixture
def manifest():
    return {
        "protocol": "shifter.runtime-plugin/v1",
        "plugin_id": "example.adapter",
        "version": "1.0",
        "distribution": "example-adapter",
        "entry_point": "example",
        "worker_image": "registry.example.test/adapters/example@sha256:" + "a" * 64,
        "capabilities": ["guest.configure", "guest.verify"],
        "required_bindings": ["server"],
    }


def url(organization):
    return f"/api/v1/cms/organizations/{organization.uuid}/plugins/"


def test_tenant_admin_installs_without_staff_operator_grants_or_execution(tenant, manifest, monkeypatch):
    actor, organization = tenant
    execute = Mock(side_effect=AssertionError("HTTP must not run plugin code"))
    monkeypatch.setattr("engine.services._runtime_plugin_controller.launch_plugin", execute)
    client = APIClient()
    client.force_authenticate(user=actor)
    response = client.post(url(organization), {"manifest": manifest}, format="json")
    assert response.status_code == 202
    assert response.json()["state"] == "checking"
    assert len(client.get(url(organization)).json()["results"]) == 1
    execute.assert_not_called()


def test_installation_pages_are_bounded_complete_and_tenant_scoped(tenant, manifest):
    actor, organization = tenant
    rows = [
        RuntimePluginInstallation(
            id=UUID(int=i + 1),
            organization_uuid=organization.uuid,
            plugin_id=manifest["plugin_id"],
            version=f"1.{i}",
            manifest={**manifest, "version": f"1.{i}"},
            manifest_digest=str(i),
            installed_by=actor,
            probe_expires_at=timezone.now(),
        )
        for i in range(53)
    ]
    RuntimePluginInstallation.objects.bulk_create(rows)
    RuntimePluginInstallation.objects.filter(organization_uuid=organization.uuid).update(created_at=timezone.now())
    foreign = RuntimePluginInstallation.objects.create(
        organization_uuid=uuid4(),
        plugin_id="other.adapter",
        version="1",
        manifest={},
        manifest_digest="other",
        installed_by=actor,
        probe_expires_at=timezone.now(),
    )
    client = APIClient()
    client.force_authenticate(user=actor)
    first = client.get(url(organization)).json()
    assert len(first["results"]) == 50
    assert first["results"][0]["id"] == str(rows[-1].pk)
    second = client.get(url(organization), {"cursor": first["next_cursor"]}).json()
    assert len(second["results"]) == 3
    assert second["next_cursor"] is None
    ids = [row["id"] for row in first["results"] + second["results"]]
    assert len(set(ids)) == 53
    assert set(ids) == {str(row.pk) for row in rows}
    assert str(foreign.pk) not in ids
    assert client.get(url(organization), {"cursor": "not-a-cursor"}).status_code == 400
    assert client.get(url(organization), {"cursor": str(foreign.pk)}).status_code == 400


def test_staff_or_another_tenant_admin_cannot_inspect_or_mutate(tenant, manifest):
    actor, organization = tenant
    installation = install_runtime_plugin(actor, organization.uuid, manifest)
    outsider = User.objects.create_user(username="other-admin", is_staff=True)
    other = Organization.objects.create(name="Other tenant")
    OrganizationMembership.objects.create(user=outsider, organization=other, role="admin")
    client = APIClient()
    client.force_authenticate(user=outsider)
    assert client.get(url(organization)).status_code == 403
    assert client.post(url(organization), {"manifest": manifest}, format="json").status_code == 403
    action = f"{url(organization)}{installation.id}/actions/"
    assert client.post(action, {"action": "retire"}, format="json").status_code == 403
    assert RuntimePluginInstallation.objects.get().state == "checking"


def test_registry_secret_is_encrypted_and_not_returned_or_audited(tenant, manifest, monkeypatch):
    actor, organization = tenant
    events = []
    monkeypatch.setattr("engine.services._runtime_plugins.audit_log", lambda event, **kwargs: events.append(event))
    result = install_runtime_plugin(
        actor, organization.uuid, manifest, registry_credentials={"username": "reader", "password": "private-value"}
    )
    assert result.has_registry_credentials
    with connection.cursor() as cursor:
        cursor.execute("SELECT registry_credentials FROM engine_runtimeplugininstallation")
        stored = cursor.fetchone()[0]
    assert stored.startswith("enc:v1:")
    assert "private-value" not in stored + str(asdict(result)) + str(events)
    assert "private-value" in RuntimePluginInstallation.objects.get().registry_credentials


def test_same_version_cannot_replace_executable_or_reenable_it(tenant, manifest):
    actor, organization = tenant
    result = install_runtime_plugin(actor, organization.uuid, manifest)
    change_runtime_plugin(actor, organization.uuid, result.id, "disable")
    assert install_runtime_plugin(actor, organization.uuid, manifest).state == "disabled"
    with pytest.raises(ValidationError):
        install_runtime_plugin(
            actor, organization.uuid, {**manifest, "worker_image": manifest["worker_image"][:-1] + "b"}
        )
    assert RuntimePluginInstallation.objects.count() == 1


def test_unknown_install_authority_fields_are_rejected(tenant, manifest):
    actor, organization = tenant
    client = APIClient()
    client.force_authenticate(user=actor)
    assert (
        client.post(
            url(organization), {"manifest": manifest, "service_account": "provisioner"}, format="json"
        ).status_code
        == 400
    )
    assert not RuntimePluginInstallation.objects.exists()


@pytest.fixture
def worker(monkeypatch):
    launch = Mock()
    monkeypatch.setattr("engine.services._runtime_plugin_controller.launch_plugin", launch)

    def observe(request):
        return InspectionResult(
            protocol=request.protocol,
            phase="inspect",
            invocation_id=request.invocation_id,
            input_digest=request.digest,
            status="compatible",
        )

    monkeypatch.setattr("engine.services._runtime_plugin_controller.observe_plugin", observe)
    return launch


def test_current_probe_enables_exact_version(tenant, manifest, worker):
    actor, organization = tenant
    install_runtime_plugin(actor, organization.uuid, manifest)
    assert reconcile_runtime_plugins() == 1
    row = RuntimePluginInstallation.objects.get()
    assert row.state == "ready"
    assert row.verified_at is not None
    assert worker.call_args.args[0].manifest.worker_image == manifest["worker_image"]


def test_another_probes_result_cannot_enable_installation(tenant, manifest, worker, monkeypatch):
    actor, organization = tenant
    install_runtime_plugin(actor, organization.uuid, manifest)

    def observe(request):
        return InspectionResult(
            protocol=request.protocol,
            phase="inspect",
            invocation_id=uuid4(),
            input_digest=request.digest,
            status="compatible",
        )

    monkeypatch.setattr("engine.services._runtime_plugin_controller.observe_plugin", observe)
    reconcile_runtime_plugins()
    row = RuntimePluginInstallation.objects.get()
    assert row.state == "failed"
    assert row.verified_at is None


def test_disable_during_probe_fences_completion(tenant, manifest, worker, monkeypatch):
    actor, organization = tenant
    result = install_runtime_plugin(actor, organization.uuid, manifest)

    def observe(request):
        change_runtime_plugin(actor, organization.uuid, result.id, "disable")
        return InspectionResult(
            protocol=request.protocol,
            phase="inspect",
            invocation_id=request.invocation_id,
            input_digest=request.digest,
            status="compatible",
        )

    monkeypatch.setattr("engine.services._runtime_plugin_controller.observe_plugin", observe)
    reconcile_runtime_plugins()
    assert RuntimePluginInstallation.objects.get().state == "disabled"


def test_private_exception_is_bounded_and_retry_uses_fresh_probe(tenant, manifest, worker):
    actor, organization = tenant
    result = install_runtime_plugin(actor, organization.uuid, manifest)
    original_probe = RuntimePluginInstallation.objects.get().probe_id
    worker.side_effect = RuntimeError("private registry diagnostic")
    reconcile_runtime_plugins()
    row = RuntimePluginInstallation.objects.get()
    assert row.state == "failed"
    assert row.failure_code == "installation-failed"
    change_runtime_plugin(actor, organization.uuid, result.id, "retry")
    row.refresh_from_db()
    assert row.state == "checking"
    assert row.probe_id != original_probe


def test_retirement_is_irreversible_and_expired_probe_cannot_enable(tenant, manifest, worker, monkeypatch):
    actor, organization = tenant
    result = install_runtime_plugin(actor, organization.uuid, manifest)
    RuntimePluginInstallation.objects.update(probe_expires_at=timezone.now())
    stop = Mock()
    monkeypatch.setattr("engine.services._runtime_plugin_controller.interrupt_plugin", stop)
    reconcile_runtime_plugins()
    row = RuntimePluginInstallation.objects.get()
    assert row.state == "failed"
    assert row.failure_code == "installation-timeout"
    worker.assert_not_called()
    stop.assert_called_once()
    change_runtime_plugin(actor, organization.uuid, result.id, "retire")
    with pytest.raises(ValidationError):
        change_runtime_plugin(actor, organization.uuid, result.id, "enable")


def test_plugin_validation_response_excludes_diagnostic_value(tenant, manifest, monkeypatch):
    actor, organization = tenant
    diagnostic = "internal-registry-diagnostic"
    failure = ValidationError("Invalid plugin manifest", field="manifest", value=diagnostic)
    monkeypatch.setattr("cms.api.runtime_plugins.install_runtime_plugin", Mock(side_effect=failure))
    client = APIClient()
    client.force_authenticate(user=actor)
    response = client.post(url(organization), {"manifest": manifest}, format="json")
    assert response.status_code == 400
    assert response.json()["error"]["message"] == "Invalid plugin manifest"
    assert diagnostic not in response.content.decode()
