"""Synthetic pack bindings survive upgrades and fence isolated planning output."""

from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from django.contrib.auth.models import User
from django.utils import timezone
from shifter_adapter_sdk.runtime import RuntimePlan, canonical_digest

from engine.launch_intents import enqueue_provisioner_launch
from engine.models import (
    OperationInput,
    Range,
    RuntimePluginInstallation,
    RuntimePluginInvocation,
    RuntimePluginRangeBinding,
)
from engine.services import (
    RangeBindings,
    bind_runtime_plugin,
    change_runtime_plugin,
    create_raes_range,
    install_runtime_plugin,
    reconcile_runtime_plugin_operations,
)
from engine.services._runtime_plugin_bindings import retained_runtime_plugin_pin
from shared.exceptions import ValidationError
from shared.raes.operation_input import parse_raes_operation_input
from shared.range_instantiation_policy import BackendAdmission, InstantiationPurpose
from shared.runtime_plugin_binding import RuntimePluginScope
from workspaces.models import Organization, OrganizationMembership
from workspaces.services import OrganizationAuthorizationError

pytestmark = pytest.mark.django_db


@pytest.fixture
def pack(monkeypatch):
    monkeypatch.setattr("engine.services._raes_range.start_raes_range_provisioning", lambda request: None)
    actor = User.objects.create_user(username="pack-admin")
    organization = Organization.objects.create(name="Example")
    OrganizationMembership.objects.create(user=actor, organization=organization, role="admin")
    manifest = {
        "protocol": "shifter.runtime-plugin/v1",
        "plugin_id": "example.adapter",
        "version": "1",
        "distribution": "example-adapter",
        "entry_point": "example",
        "worker_image": "registry.example.test/adapter@sha256:" + "a" * 64,
        "capabilities": ["guest.configure", "guest.verify"],
        "required_bindings": ["server"],
    }
    installed = install_runtime_plugin(actor, organization.uuid, manifest)
    RuntimePluginInstallation.objects.filter(pk=installed.id).update(state="ready")
    scope = RuntimePluginScope(organization_uuid=organization.uuid, pack_id="example", pack_digest="sha256:" + "b" * 64)
    binding = bind_runtime_plugin(
        actor,
        RuntimePluginScope(organization_uuid=organization.uuid, pack_digest=scope.pack_digest, pack_id="example"),
        installed.id,
        {"targets": {"server": "node.web"}},
    )
    return SimpleNamespace(
        actor=actor, organization=organization, installed=installed, manifest=manifest, scope=scope, binding=binding
    )


def launch(pack, *, backend="gce"):
    plan = {"resources": {"node.web": {"resource_type": "node", "payload": {"os_family": "linux", "spec": {}}}}}
    request = uuid4()
    create_raes_range(
        request_id=request,
        user_id=pack.actor.id,
        workspace_id=1,
        compiled_plan=plan,
        backend_admission=BackendAdmission(True, backend, InstantiationPurpose.LIVE_FIRE, "", ""),
        bindings=RangeBindings(runtime_plugin_scope=pack.scope),
    )
    target = Range.objects.get(request__request_id=request)
    enqueue_provisioner_launch(["raes-range", "provision", "--request-id", str(request)])
    target.refresh_from_db()
    return target


def test_existing_range_keeps_original_version_after_pack_upgrade_and_retirement(pack):
    target = launch(pack)
    original = retained_runtime_plugin_pin(target)
    replacement = install_runtime_plugin(pack.actor, pack.organization.uuid, {**pack.manifest, "version": "2"})
    RuntimePluginInstallation.objects.filter(pk=replacement.id).update(state="ready")
    bind_runtime_plugin(
        pack.actor,
        RuntimePluginScope(
            organization_uuid=pack.organization.uuid, pack_digest=pack.scope.pack_digest, pack_id="example"
        ),
        replacement.id,
        {"targets": {"server": "node.web"}},
    )
    change_runtime_plugin(pack.actor, pack.organization.uuid, pack.installed.id, "retire")
    assert retained_runtime_plugin_pin(target) == original
    from engine.operation_inputs import operation_input_payload

    cleanup = parse_raes_operation_input(
        operation_input_payload(target, "raes-range", target.request, operation="destroy")
    )
    assert cleanup.runtime_plugin == original
    assert retained_runtime_plugin_pin(launch(pack)).installation_id == replacement.id


def test_tenant_admin_image_profile_is_pinned_with_the_adapter_target(pack):
    binding = bind_runtime_plugin(
        pack.actor,
        pack.scope,
        pack.installed.id,
        {
            "targets": {"server": "node.web"},
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
    )
    assert binding.bindings["image_profiles"]["server"]["provider"] == "gcp"
    pin = retained_runtime_plugin_pin(launch(pack))
    assert pin is not None
    assert pin.bindings.image_profile_for("node.web").image_ref.endswith("/machineImages/nested-host-v1")
    assert pin.bindings.image_profile_for("node.web").allow_public_web_egress is True


def test_pre_upgrade_pin_without_defaulted_profile_field_remains_usable_for_cleanup(pack):
    bind_runtime_plugin(
        pack.actor,
        pack.scope,
        pack.installed.id,
        {
            "targets": {"server": "node.web"},
            "image_profiles": {
                "server": {
                    "provider": "gcp",
                    "image_ref": "projects/example/global/images/training-v1",
                }
            },
        },
    )
    target = launch(pack)
    row = RuntimePluginRangeBinding.objects.get(range=target)
    legacy_pin = row.pin.copy()
    legacy_pin["bindings"] = row.pin["bindings"].copy()
    legacy_pin["bindings"]["image_profiles"] = row.pin["bindings"]["image_profiles"].copy()
    legacy_pin["bindings"]["image_profiles"]["server"] = row.pin["bindings"]["image_profiles"]["server"].copy()
    legacy_pin["bindings"]["image_profiles"]["server"].pop("allow_public_web_egress")
    row.pin = legacy_pin
    row.pin_digest = canonical_digest(legacy_pin)
    row.save(update_fields=["pin", "pin_digest"])

    pin = retained_runtime_plugin_pin(target)
    assert pin is not None
    assert pin.bindings.image_profile_for("node.web").allow_public_web_egress is False
    from engine.operation_inputs import operation_input_payload

    cleanup = parse_raes_operation_input(
        operation_input_payload(target, "raes-range", target.request, operation="destroy")
    )
    assert cleanup.runtime_plugin == pin

    legacy_pin["bindings"]["image_profiles"]["server"]["image_ref"] = "projects/example/global/images/other-v1"
    row.pin = legacy_pin
    row.save(update_fields=["pin"])
    with pytest.raises(ValidationError, match="binding is invalid"):
        retained_runtime_plugin_pin(target)


def test_image_profile_cannot_name_an_undeclared_binding(pack):
    with pytest.raises(ValidationError, match="declaration"):
        bind_runtime_plugin(
            pack.actor,
            pack.scope,
            pack.installed.id,
            {
                "targets": {"server": "node.web"},
                "image_profiles": {
                    "other": {"provider": "aws", "image_ref": "ami-0123456789abcdef0"},
                },
            },
        )


def test_image_profile_provider_must_match_the_admitted_backend(pack):
    bind_runtime_plugin(
        pack.actor,
        pack.scope,
        pack.installed.id,
        {
            "targets": {"server": "node.web"},
            "image_profiles": {
                "server": {
                    "provider": "gcp",
                    "image_ref": "projects/example/global/images/training-v1",
                }
            },
        },
    )
    with pytest.raises(ValidationError, match="compiled guests"):
        launch(pack, backend="ec2")
    assert not Range.objects.exists()


@pytest.mark.parametrize("action", ["disable", "retire"])
def test_disabled_or_retired_selection_blocks_new_range_before_dispatch(pack, action):
    change_runtime_plugin(pack.actor, pack.organization.uuid, pack.installed.id, action)
    with pytest.raises(ValidationError, match="not enabled and ready"):
        launch(pack)
    assert not Range.objects.exists()


def test_binding_cannot_select_another_tenant_executable(pack):
    other = Organization.objects.create(name="Other")
    OrganizationMembership.objects.create(user=pack.actor, organization=other, role="admin")
    with pytest.raises(ValidationError, match="unavailable"):
        bind_runtime_plugin(
            pack.actor,
            RuntimePluginScope(organization_uuid=other.uuid, pack_digest=pack.scope.pack_digest, pack_id="example"),
            pack.installed.id,
            {"targets": {"server": "node.web"}},
        )
    outsider = User.objects.create_user(username="staff-outsider", is_staff=True)
    with pytest.raises(OrganizationAuthorizationError):
        bind_runtime_plugin(
            outsider,
            RuntimePluginScope(
                organization_uuid=pack.organization.uuid, pack_digest=pack.scope.pack_digest, pack_id="example"
            ),
            pack.installed.id,
            {"targets": {"server": "node.web"}},
        )


def test_missing_guest_fails_without_persisting_a_range(pack):
    bind_runtime_plugin(
        pack.actor,
        RuntimePluginScope(
            organization_uuid=pack.organization.uuid, pack_digest=pack.scope.pack_digest, pack_id="example"
        ),
        pack.installed.id,
        {"targets": {"server": "node.absent"}},
    )
    with pytest.raises(ValidationError, match="compiled guests"):
        launch(pack)
    assert not Range.objects.exists()


def test_pack_update_requires_explicit_rebinding_instead_of_silently_skipping_plugin(pack):
    pack.scope = pack.scope.model_copy(update={"pack_digest": "sha256:" + "d" * 64})
    with pytest.raises(ValidationError, match="pack changed"):
        launch(pack)
    assert not Range.objects.exists()


@pytest.fixture
def worker(monkeypatch):
    dispatch = Mock()
    monkeypatch.setattr("engine.services._runtime_plugin_operations.launch_plugin", dispatch)
    monkeypatch.setattr("engine.services._runtime_plugin_operations._pull_secret", lambda *args: "")
    monkeypatch.setattr("engine.services._runtime_plugin_operations.interrupt_plugin", Mock())

    def observe(request):
        return RuntimePlan(
            protocol=request.protocol,
            invocation_id=request.invocation_id,
            input_digest=request.digest,
            phase=request.phase,
            status="planned",
            actions=[]
            if request.phase == "validate"
            else [
                {"action_id": request.phase, "binding": "server", "script": "exit 0"},
            ],
        )

    monkeypatch.setattr("engine.services._runtime_plugin_operations.observe_plugin", observe)
    return dispatch


def test_controller_plans_only_the_pinned_operation_in_isolated_workers(pack, worker):
    target = launch(pack)
    assert RuntimePluginInvocation.objects.count() == 3
    envelope = OperationInput.objects.get(operation_id=target.provisioner_operation_id).envelope
    assert parse_raes_operation_input(envelope["payload"]).runtime_plugin.installation_id == pack.installed.id
    assert reconcile_runtime_plugin_operations() == 3
    assert set(RuntimePluginInvocation.objects.values_list("state", flat=True)) == {"planned"}
    assert worker.call_count == 3
    for call in worker.call_args_list:
        assert call.args[0].operation_id == target.provisioner_operation_id
        assert call.args[0].manifest.version == "1"


@pytest.mark.parametrize("invalidate", ["generation", "expired", "tampered"])
def test_controller_refuses_stale_expired_or_tampered_input_before_launch(pack, worker, invalidate):
    target = launch(pack)
    if invalidate == "generation":
        Range.objects.filter(pk=target.pk).update(provisioner_operation_id=uuid4())
    elif invalidate == "expired":
        RuntimePluginInvocation.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
    else:
        RuntimePluginInvocation.objects.update(input_digest="sha256:" + "c" * 64)
    reconcile_runtime_plugin_operations()
    worker.assert_not_called()
    assert set(RuntimePluginInvocation.objects.values_list("state", flat=True)) == {"failed"}


def test_controller_rejects_generation_change_during_worker_observation(pack, worker, monkeypatch):
    target = launch(pack)

    def observe(request):
        Range.objects.filter(pk=target.pk).update(provisioner_operation_id=uuid4())
        return RuntimePlan(
            protocol=request.protocol,
            invocation_id=request.invocation_id,
            input_digest=request.digest,
            phase=request.phase,
            status="planned",
            actions=[]
            if request.phase == "validate"
            else [
                {"action_id": "check", "binding": "server", "script": "exit 0"},
            ],
        )

    monkeypatch.setattr("engine.services._runtime_plugin_operations.observe_plugin", observe)
    reconcile_runtime_plugin_operations()
    assert not RuntimePluginInvocation.objects.filter(state="planned").exists()


def test_warm_claim_cannot_skip_a_disabled_plugin_binding(pack, monkeypatch):
    from cms.services._warm_pool_claim import WarmClaimRequest, attempt_warm_claim
    from shared.enums import RangeSource

    monkeypatch.setattr("cms.services._warm_pool_claim._resolve_claim_candidates", lambda *args: [("pool", "digest")])
    monkeypatch.setattr(
        "workspaces.services.authorize_bound_workspace",
        lambda *args: SimpleNamespace(organization_uuid=pack.organization.uuid),
    )
    claim = Mock(side_effect=AssertionError("A base-only generation cannot satisfy a plugin-bound pack"))
    monkeypatch.setattr("cms.services._warm_pool_claim._run_atomic_claim", claim)
    request = WarmClaimRequest(
        pack.actor,
        "example",
        pack.scope.pack_digest,
        "",
        "gce",
        InstantiationPurpose.LIVE_FIRE,
        RangeSource.MISSION_CONTROL,
        1,
        "status-quo",
        uuid4(),
    )
    assert attempt_warm_claim(request) is None
    change_runtime_plugin(pack.actor, pack.organization.uuid, pack.installed.id, "disable")
    assert attempt_warm_claim(replace(request, request_id=uuid4())) is None
    claim.assert_not_called()


def test_aws_plugin_invocations_use_the_bound_provider_and_stable_resource_epoch(pack):
    target = launch(pack, backend="ec2")
    operation = OperationInput.objects.get(operation_id=target.provisioner_operation_id)
    parsed = parse_raes_operation_input(operation.envelope["payload"])
    assert parsed.resource_generation == str(target.resource_generation)
    invocations = list(RuntimePluginInvocation.objects.filter(operation_id=target.provisioner_operation_id))
    assert {row.phase for row in invocations} == {"validate", "configure", "verify"}
    assert all(row.input["provider"] == "aws" for row in invocations)
