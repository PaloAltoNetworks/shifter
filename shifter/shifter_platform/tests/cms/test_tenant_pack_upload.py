"""Tenant uploads exercise real pack validation, storage identity and catalog access."""

import io
import tarfile
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from cms.models import RaesPackageSource, ScenarioModelNeeds
from cms.scenarios.registry import check_scenario_access, list_all_scenarios
from engine.models import Range, RuntimePluginInstallation, RuntimePluginInvocation
from tests.cms.test_runtime_plugins import tenant as tenant
from workspaces.models import Organization, OrganizationMembership

pytestmark = pytest.mark.django_db


class PackStorage:
    def __init__(self):
        self.objects = {}
        self.deleted = []

    def upload_file(self, file_obj, bucket, key, content_type=""):
        self.objects[(bucket, key)] = file_obj.read()

    def delete_object(self, bucket, key):
        self.deleted.append((bucket, key))
        self.objects.pop((bucket, key), None)

    def head_object(self, bucket, key):
        return {"content_length": len(self.objects[(bucket, key)]), "etag": key}

    def download_object(self, bucket, key, dest_path, *, max_bytes, expected_identity):
        raw = self.objects[(bucket, key)]
        assert len(raw) <= max_bytes
        assert expected_identity == self.head_object(bucket, key)
        Path(dest_path).write_bytes(raw)
        return expected_identity


def _archive(root):
    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode="w:gz") as archive:
        archive.add(root, arcname=root.name)
    return SimpleUploadedFile("pack.tar.gz", data.getvalue(), content_type="application/gzip")


@pytest.fixture
def upload(tenant, make_pack, tmp_path, settings, monkeypatch):
    actor, organization = tenant
    root = make_pack(tmp_path / "example")
    settings.RAES_PACKAGE_BUCKET = "test-private-pack-storage"
    settings.RAES_PACKAGE_PREFIX = "packs"
    storage = PackStorage()
    monkeypatch.setattr("cms.services._tenant_pack_upload.get_object_storage", lambda: storage)
    monkeypatch.setattr("shared.cloud.get_object_storage", lambda: storage)
    client = APIClient()
    client.force_authenticate(user=actor)
    return client, organization, root, storage


def _post(client, organization, root, **extra):
    return client.post(
        f"/api/v1/cms/organizations/{organization.uuid}/packs/",
        {"name": root.name, "archive": _archive(root), **extra},
        format="multipart",
    )


def test_admin_installs_validated_pack_without_staff_or_executable_side_effects(upload, tenant):
    client, organization, root, storage = upload
    actor, _ = tenant
    assert not actor.is_staff
    response = _post(client, organization, root)
    assert response.status_code == 201, response.data
    source = RaesPackageSource.objects.get()
    assert source.organization_uuid == organization.uuid
    assert source.package_identity == "example"
    assert source.scenario_id != source.package_identity
    assert response.data["conformance_status"] == "passed"
    assert len(storage.objects) == 1
    assert all(f"packs/tenant-packs/{organization.uuid}/" in key for _, key in storage.objects)
    assert not Range.objects.exists()
    assert not RuntimePluginInstallation.objects.exists()
    assert not RuntimePluginInvocation.objects.exists()
    # Read the uploaded bytes back through the existing launch-time trust seam.
    from cms.scenarios.realizability import _trusted_scenario_path

    with _trusted_scenario_path(source) as (path, _):
        assert path is not None and path.is_file()


def test_pack_model_need_is_digest_bound_during_tenant_install(upload):
    from tests.cms.conftest import write_pack_content_manifest

    client, organization, root, _storage = upload
    (root / "model-needs.json").write_text(
        """{
          "contract_version": "model-access-pack/v1",
          "needs": {
            "participant": {
              "workload_role": "participant",
              "profile_id": "coding",
              "required": true,
              "required_capabilities": ["messages"],
              "allowed_capabilities": ["messages"],
              "allowed_strategies": ["fixed-v1"],
              "data_regions": ["us-central1"],
              "limits": {
                "max_request_seconds": 120,
                "max_request_bytes": 1000000,
                "max_input_tokens": 8000,
                "max_output_tokens": 2000,
                "max_requests_per_window": 60,
                "request_window_seconds": 60,
                "max_spend_micro_units": 5000000,
                "currency": "USD",
                "max_concurrent_requests": 2
              }
            }
          }
        }""",
        encoding="utf-8",
    )
    write_pack_content_manifest(root, root.name)
    response = _post(client, organization, root)
    assert response.status_code == 201, response.data
    source = RaesPackageSource.objects.get()
    overlay = ScenarioModelNeeds.objects.get(scenario_id=source.scenario_id)
    assert overlay.authored_package_digest == source.package_digest
    assert overlay.needs["participant"]["scenario_digest"] == source.package_digest


def test_identical_pack_names_have_independent_tenant_catalog_identities(upload, tenant):
    client, organization, root, storage = upload
    first = _post(client, organization, root)
    other = Organization.objects.create(name="Other")
    second_actor = User.objects.create_user(username="other-pack-admin")
    OrganizationMembership.objects.create(user=second_actor, organization=other, role="admin")
    client.force_authenticate(user=second_actor)
    second = _post(client, other, root)
    assert first.status_code == second.status_code == 201
    assert first.data["scenario_id"] != second.data["scenario_id"]
    assert len(storage.objects) == 2
    assert [row["id"] for row in list_all_scenarios(user=tenant[0])] == [first.data["scenario_id"]]
    assert [row["id"] for row in list_all_scenarios(user=second_actor)] == [second.data["scenario_id"]]
    with pytest.raises(ValueError, match="not available"):
        check_scenario_access(first.data["scenario_id"], second_actor)


def test_foreign_staff_cannot_upload_or_inspect_tenant_content(upload):
    client, organization, root, storage = upload
    source_id = _post(client, organization, root).data["scenario_id"]
    outsider = User.objects.create_user(username="foreign-staff", is_staff=True)
    client.force_authenticate(user=outsider)
    assert _post(client, organization, root).status_code == 403
    assert list_all_scenarios(user=outsider) == []
    with pytest.raises(ValueError):
        check_scenario_access(source_id, outsider)
    assert len(storage.objects) == 1


@pytest.mark.parametrize("invalid", ["identity", "content", "oversized", "asserted-conformance"])
def test_invalid_upload_has_no_storage_or_registry_effects(upload, settings, invalid):
    client, organization, root, storage = upload
    extra = {}
    if invalid == "identity":
        extra["name"] = "different"
    elif invalid == "content":
        (root / "docs/concepts.md").write_text("Changed bytes")
    elif invalid == "oversized":
        settings.RAES_PACKAGE_MAX_ARCHIVE_BYTES = 8
    else:
        extra["conformance_status"] = "passed"
    response = _post(client, organization, root, **extra)
    assert response.status_code == 400
    assert not storage.objects
    assert not RaesPackageSource.objects.exists()


@pytest.mark.parametrize("entry_kind", ["traversal", "symlink"])
def test_archive_containment_applies_before_storage(upload, entry_kind):
    client, organization, _, storage = upload
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w:gz") as archive:
        entry = tarfile.TarInfo("../escape" if entry_kind == "traversal" else "link")
        if entry_kind == "symlink":
            entry.type = tarfile.SYMTYPE
            entry.linkname = "/etc/passwd"
        archive.addfile(entry)
    response = client.post(
        f"/api/v1/cms/organizations/{organization.uuid}/packs/",
        {
            "name": "example",
            "archive": SimpleUploadedFile("pack.tar.gz", raw.getvalue()),
        },
        format="multipart",
    )
    assert response.status_code == 400
    assert not storage.objects


def test_failed_registration_cleans_only_its_new_upload(upload):
    client, organization, root, storage = upload
    original = _post(client, organization, root)
    original_objects = dict(storage.objects)
    stale = _post(client, organization, root, expected_digest="sha256:" + "f" * 64)
    assert original.status_code == 201 and stale.status_code == 400
    assert storage.objects == original_objects
    assert len(storage.deleted) == 1
    assert RaesPackageSource.objects.count() == 1


def test_pack_cannot_be_launched_in_another_organization_workspace(upload, tenant):
    from cms.exceptions import CMSError
    from cms.services._raes_dispatch import _runtime_plugin_scope
    from workspaces.models import Workspace, WorkspaceMembership

    client, organization, root, _ = upload
    _post(client, organization, root)
    other = Organization.objects.create(name="Other workspace organization")
    workspace = Workspace.objects.create(organization=other, name="Other workspace")
    WorkspaceMembership.objects.create(workspace=workspace, user=tenant[0], role="owner")
    with pytest.raises(CMSError, match="unavailable in this workspace"):
        _runtime_plugin_scope(tenant[0], workspace.pk, RaesPackageSource.objects.get(), None)
    assert not Range.objects.exists()


def test_ctf_event_owner_binds_tenant_adapter_for_participant_workspace(upload, tenant, monkeypatch):
    from cms.services._raes_dispatch import _launch_pack, _runtime_plugin_scope
    from workspaces.services import resolve_personal_workspace

    client, organization, root, _ = upload
    owner, _ = tenant
    _post(client, organization, root)
    source = RaesPackageSource.objects.get()
    participant = User.objects.create_user(username="ctf-participant")
    workspace = resolve_personal_workspace(participant)
    captured = {}

    def launch(**kwargs):
        captured["scope"] = kwargs["port"].runtime_plugin_scope
        return SimpleNamespace(accepted=True)

    monkeypatch.setattr("shared.raes.package_loader.launch_raes_package", launch)
    plugin_scope = _runtime_plugin_scope(participant, workspace.workspace_id, source, owner)
    _launch_pack(
        uuid4(),
        participant,
        root,
        None,
        workspace.workspace_id,
        "status-quo",
        plugin_scope,
    )

    assert captured["scope"].organization_uuid == organization.uuid
    assert captured["scope"].pack_id == source.scenario_id


def test_rejected_launch_logs_bounded_diagnostics(upload, tenant, monkeypatch, caplog):
    from cms.exceptions import CMSError
    from cms.services._raes_dispatch import _launch_pack
    from shared.raes.package_loader import ShifterLaunchResult
    from shared.runtime_plugin_binding import RuntimePluginScope
    from workspaces.services import resolve_personal_workspace

    _, organization, root, _ = upload
    owner, _ = tenant
    workspace = resolve_personal_workspace(owner)
    request_id = uuid4()
    diagnostic = "shifter-provisioner.dispatch-failed @ plan: allocation unavailable"

    monkeypatch.setattr(
        "shared.raes.package_loader.launch_raes_package",
        lambda **_kwargs: ShifterLaunchResult(
            accepted=False,
            status="rejected",
            diagnostics=(diagnostic,),
        ),
    )
    scope = RuntimePluginScope(
        organization_uuid=organization.uuid,
        pack_id="example",
        pack_digest="sha256:" + "a" * 64,
    )

    with (
        caplog.at_level("WARNING", logger="cms.services._raes_dispatch"),
        pytest.raises(CMSError, match="RAES provisioning was not accepted"),
    ):
        _launch_pack(request_id, owner, root, None, workspace.workspace_id, "status-quo", scope)

    assert str(request_id) in caplog.text
    assert "status=rejected" in caplog.text
    assert diagnostic in caplog.text


def test_pack_revision_requires_existing_identity(upload):
    client, organization, root, storage = upload
    response = _post(client, organization, root, expected_digest="sha256:" + "f" * 64)
    assert response.status_code == 400
    assert not RaesPackageSource.objects.exists()
    assert not storage.objects


def test_update_installs_verified_new_version_without_replacing_existing_object(upload, make_pack):
    from tests.cms.conftest import conformant_pack_yaml

    client, organization, root, storage = upload
    first = _post(client, organization, root)
    original_objects = dict(storage.objects)
    metadata = conformant_pack_yaml(root.name)
    metadata["version"] = "0.2.0"
    make_pack(root, pack_yaml=metadata)
    from raes_contracts.associated_artifacts import associated_artifact_set_digest
    from raes_contracts.contracts import AssociatedArtifactManifestModel

    manifest_path = root / "associated-artifacts.json"
    manifest = AssociatedArtifactManifestModel.model_validate_json(manifest_path.read_text())
    manifest = manifest.model_copy(update={"manifest_version": "0.2.0"})
    manifest = manifest.model_copy(update={"set_digest": associated_artifact_set_digest(manifest)})
    manifest_path.write_text(manifest.model_dump_json(indent=2) + "\n")
    updated = _post(client, organization, root, expected_digest=first.data["package_digest"])
    assert updated.status_code == 201, updated.data
    assert updated.data["scenario_id"] == first.data["scenario_id"]
    assert updated.data["package_version"] == "0.2.0"
    assert updated.data["package_digest"] != first.data["package_digest"]
    assert not updated.data["created"]
    assert all(storage.objects[key] == value for key, value in original_objects.items())
    assert len(storage.objects) == 2


@pytest.mark.parametrize("failure", ["revoked-admin", "audit-unavailable"])
def test_authority_and_audit_failure_roll_back_registration_and_upload(upload, tenant, monkeypatch, failure):
    client, organization, root, storage = upload
    if failure == "revoked-admin":
        original_upload = storage.upload_file

        def revoke(*args, **kwargs):
            original_upload(*args, **kwargs)
            OrganizationMembership.objects.filter(user=tenant[0], organization=organization).delete()

        monkeypatch.setattr(storage, "upload_file", revoke)
    else:

        def failed_audit(*args, **kwargs):
            raise RuntimeError("Synthetic audit failure")

        monkeypatch.setattr("cms.services._tenant_pack_upload.audit_log", failed_audit)
    response = _post(client, organization, root)
    assert response.status_code == 400
    assert not RaesPackageSource.objects.exists()
    assert not storage.objects


def test_foreign_author_cannot_read_tenant_pack_through_catalog_api(upload):
    client, organization, root, _ = upload
    identifier = _post(client, organization, root).data["scenario_id"]
    client.force_authenticate(user=User.objects.create_user(username="outside-author", is_staff=True))
    assert client.get("/api/v1/cms/catalog/").data == []
    for path in (f"/api/v1/cms/catalog/{identifier}/", f"/api/v1/cms/scenarios/{identifier}/"):
        assert client.get(path).status_code == 404


def test_workspace_membership_allows_read_but_not_metadata_changes(upload, tenant):
    from cms.scenario_editor._metadata import update_metadata
    from workspaces.models import Workspace, WorkspaceMembership
    from workspaces.services import OrganizationAuthorizationError

    client, organization, root, _ = upload
    identifier = _post(client, organization, root).data["scenario_id"]
    staff = User.objects.create_user(username="tenant-staff-seat", is_staff=True)
    workspace = Workspace.objects.create(organization=organization, name="Content viewers")
    WorkspaceMembership.objects.create(workspace=workspace, user=staff, role="member")
    assert check_scenario_access(identifier, staff)["id"] == identifier
    with pytest.raises(OrganizationAuthorizationError):
        update_metadata(staff, identifier, enabled=False)
    update_metadata(tenant[0], identifier, enabled=False)
    assert list_all_scenarios(user=tenant[0]) == []


def test_tenant_conformance_mutation_requires_admin_even_for_staff_members(upload, tenant):
    from cms.services._pack_conformance import validate_registered_pack_conformance
    from workspaces.models import Workspace, WorkspaceMembership
    from workspaces.services import OrganizationAuthorizationError

    client, organization, root, _ = upload
    installed = _post(client, organization, root).data
    staff = User.objects.create_user(username="conformance-staff-seat", is_staff=True)
    workspace = Workspace.objects.create(organization=organization, name="Conformance viewers")
    WorkspaceMembership.objects.create(workspace=workspace, user=staff, role="member")
    arguments = {"scenario_id": installed["scenario_id"], "expected_package_digest": installed["package_digest"]}
    with pytest.raises(OrganizationAuthorizationError):
        validate_registered_pack_conformance(user=staff, **arguments)
    assert validate_registered_pack_conformance(user=tenant[0], **arguments) == "passed"
