"""Tests for the RAES-native launch service + dispatcher (#1479).

Covers create_raes_native_range (flag gate, CMS bookkeeping, active-range
admission, launchability, failure handling) and create_range_dispatch routing.
One integration test drives the real resolve -> load -> plan -> apply -> port
chain with only the engine seam (engine.services.create_raes_range) mocked, so
no real provisioning is triggered.
"""

from __future__ import annotations

import pytest

from cms.exceptions import CMSError
from cms.models import RaesPackageSource, RangeInstance
from cms.scenarios.pack_validation import pack_digest
from cms.services import create_non_user_range, create_raes_native_range, create_range_dispatch
from cms.services._non_user_range_launch import NonUserWorkflow
from shared.enums import ResourceStatus
from shared.range_instantiation_policy import InstantiationPurpose
from tests.cms.conftest import write_pack_content_manifest

_PACK_REF = "packs/raes-launch"
_DISPATCH = "cms.services._raes_range_create._dispatch_raes_package"


@pytest.fixture
def user(django_user_model):
    return django_user_model.objects.create(username="raes-launcher")


def _make_source(user, scenario_id="raes-launch", **overrides):
    fields = {
        "scenario_id": scenario_id,
        "contract_kind": "raes",
        "contract_profile": "shifter",
        "source_kind": "repo",
        "package_ref": _PACK_REF,
        "package_version": "1.0.0",
        "package_digest": "sha256:" + "a" * 64,
        "conformance_status": "passed",
        "registered_by": user,
    }
    fields.update(overrides)
    return RaesPackageSource.objects.create(**fields)


@pytest.mark.django_db
def test_launch_persists_bookkeeping_and_dispatches(user, monkeypatch):
    _make_source(user)
    seen = {}
    monkeypatch.setattr(
        _DISPATCH,
        lambda request_id, u, source, backend_admission=None, workspace_id=None, egress_mode=None: seen.update(
            ref=source.package_ref,
            digest=source.package_digest,
        ),
    )
    ctx = create_raes_native_range(user, "raes-launch")

    assert ctx.request_id is not None
    assert seen["ref"] == _PACK_REF
    assert seen["digest"] == "sha256:" + "a" * 64
    instance = RangeInstance.objects.get(request__request_id=ctx.request_id)
    assert instance.scenario_id == "raes-launch"
    assert instance.range_spec is None  # no cyberscript RangeSpec for RAES
    assert instance.status == ResourceStatus.PROVISIONING.value
    # New Mission Control ranges persist deadlines + the increment from the effective
    # lease policy (default 30/30/365) as a per-generation snapshot (#27).
    assert instance.expires_at is not None
    assert instance.maximum_expires_at is not None
    assert instance.extension_days == 30
    # Deadlines derive from the default policy durations: maximum 365d, initial 30d.
    assert (instance.maximum_expires_at - instance.expires_at).days == 365 - 30


@pytest.mark.django_db
def test_launch_snapshots_the_configured_lease_policy_onto_the_generation(user, monkeypatch):
    from django.test import override_settings

    from shared.mission_control_lease import MissionControlLeasePolicy

    _make_source(user)
    monkeypatch.setattr(_DISPATCH, lambda *a, **k: None)
    policy = MissionControlLeasePolicy(initial_days=7, extension_days=3, maximum_days=90)
    with override_settings(MISSION_CONTROL_LEASE_POLICY=policy):
        ctx = create_raes_native_range(user, "raes-launch")

    instance = RangeInstance.objects.get(request__request_id=ctx.request_id)
    # The generation snapshots the increment; deadlines derive from the policy durations.
    assert instance.extension_days == 3
    delta_days = (instance.maximum_expires_at - instance.expires_at).days
    assert delta_days == 90 - 7


@pytest.mark.django_db
def test_launch_resolves_group_policy_inside_reservation_and_records_provenance(user, monkeypatch):
    from django.contrib.auth.models import Group
    from django.db import connection

    from cms.models import MissionControlGroupLeasePolicy
    from shared.audit import AuditAction, AuditEntityType
    from shared.models import AuditLog

    _make_source(user)
    monkeypatch.setattr(_DISPATCH, lambda *a, **k: None)
    group = Group.objects.create(name="Short Lease")
    user.groups.add(group)
    MissionControlGroupLeasePolicy.objects.create(
        group=group,
        initial_days=7,
        extension_days=3,
        maximum_days=90,
        extensions_enabled=True,
    )
    from cms.services import _range_lease as lease_module

    original = lease_module.resolve_mission_control_lease_policy

    def assert_transaction(owner, *, for_update=False):
        assert connection.in_atomic_block
        assert for_update is True
        return original(owner, for_update=for_update)

    monkeypatch.setattr(lease_module, "resolve_mission_control_lease_policy", assert_transaction)

    ctx = create_raes_native_range(user, "raes-launch")

    instance = RangeInstance.objects.get(request__request_id=ctx.request_id)
    assert instance.extension_days == 3
    assert instance.lease_initial_days == 7
    assert instance.lease_maximum_days == 90
    assert instance.lease_policy_source == "group"
    assert instance.lease_policy_tenant_revision == 0
    assert instance.lease_policy_group_revisions == [{"group_id": group.pk, "revision": 1}]
    audit = AuditLog.objects.get(
        entity_type=AuditEntityType.RANGE,
        action=AuditAction.PROVISION,
        entity_id=instance.pk,
    )
    assert audit.new_state["lease_policy_source"] == "group"
    assert audit.new_state["lease_initial_days"] == 7
    assert audit.new_state["lease_maximum_days"] == 90


@pytest.mark.django_db
def test_dispatch_failure_marks_failed_and_raises(user, monkeypatch):
    _make_source(user)

    def boom(*_args, **_kwargs):
        raise CMSError("dispatch failed")

    monkeypatch.setattr(_DISPATCH, boom)
    with pytest.raises(CMSError):
        create_raes_native_range(user, "raes-launch")
    # FAILED is terminal and soft-deletes the row, so query via all_objects.
    instance = RangeInstance.all_objects.get(scenario_id="raes-launch")
    assert instance.status == ResourceStatus.FAILED.value


@pytest.mark.django_db
def test_non_launchable_pending_refused(user, monkeypatch):
    _make_source(user, conformance_status="pending")
    monkeypatch.setattr(_DISPATCH, lambda *a, **k: None)
    with pytest.raises(CMSError, match="not available for launch"):
        create_raes_native_range(user, "raes-launch")
    # Refused before any range row is created.
    assert not RangeInstance.all_objects.filter(user_id=user.id).exists()


@pytest.mark.django_db
def test_active_range_refused(user, monkeypatch):
    _make_source(user)
    monkeypatch.setattr(_DISPATCH, lambda *a, **k: None)
    create_raes_native_range(user, "raes-launch")
    with pytest.raises(CMSError, match="already have an active range"):
        create_raes_native_range(user, "raes-launch")
    # The second launch is refused; only the first range remains.
    assert RangeInstance.objects.filter(user_id=user.id).count() == 1


@pytest.mark.django_db
def test_live_fire_gate_denies_gdc_before_dispatch(user, monkeypatch):
    # Issue #1348 / ADR-030: the RAES-native path shares the same live-fire gate;
    # a GDC selector is denied before the pack is resolved or dispatched.
    from django.conf import settings

    _make_source(user)
    dispatched = {"called": False}
    monkeypatch.setattr(_DISPATCH, lambda *a, **k: dispatched.update(called=True))
    monkeypatch.setattr(settings, "CLOUD_PROVIDER", "gcp")
    monkeypatch.setenv("GCP_RANGE_BACKEND", "gdc")

    with pytest.raises(CMSError, match=r"not an approved live-fire|GCE VM range-cell"):
        create_raes_native_range(user, "raes-launch")

    assert dispatched["called"] is False
    assert not RangeInstance.all_objects.filter(user_id=user.id).exists()


@pytest.mark.django_db
def test_live_fire_gate_admits_gce(user, monkeypatch):
    from django.conf import settings

    _make_source(user)
    monkeypatch.setattr(_DISPATCH, lambda *a, **k: None)
    monkeypatch.setattr(settings, "CLOUD_PROVIDER", "gcp")
    monkeypatch.setenv("GCP_RANGE_BACKEND", "gce")

    ctx = create_raes_native_range(user, "raes-launch")

    assert ctx.request_id is not None
    assert RangeInstance.objects.filter(user_id=user.id).exists()


@pytest.mark.django_db
def test_policy_allowed_gdc_still_fails_unsupported_capability(user, monkeypatch):
    # Issue #1354: policy admission and adapter availability are separate gates.
    # raes_range_ops realizes GCE only, so a non-user purpose that the policy
    # permits on GDC must still fail closed before dispatch rather than binding
    # gdc and then running the hard-coded GCE adapter.
    from django.conf import settings

    _make_source(user)
    dispatched = {"called": False}
    monkeypatch.setattr(_DISPATCH, lambda *a, **k: dispatched.update(called=True))
    monkeypatch.setattr(settings, "CLOUD_PROVIDER", "gcp")
    monkeypatch.setenv("GCP_RANGE_BACKEND", "gdc")

    user.is_staff = True
    user.save(update_fields=["is_staff"])
    with pytest.raises(CMSError) as exc:
        create_non_user_range(user, "raes-launch", workflow=NonUserWorkflow.OPERATOR_VALIDATION)

    assert exc.value.details["code"] == "unsupported-capability"
    assert dispatched["called"] is False
    assert not RangeInstance.all_objects.filter(user_id=user.id).exists()


@pytest.mark.django_db
def test_dispatch_routes_registered_raes_source(user, monkeypatch):
    _make_source(user, scenario_id="raes-x")
    routed = {}
    monkeypatch.setattr(
        "cms.services._raes_range_create._create_raes_native_range_impl",
        lambda u, s, **kwargs: routed.update(scenario=s, purpose=kwargs.get("instantiation_purpose")),
    )
    create_range_dispatch(user, "raes-x")
    assert routed["scenario"] == "raes-x"
    # The product router always mints live-fire authority (#1354, ADR-030-R6).
    assert routed["purpose"] is InstantiationPurpose.LIVE_FIRE


@pytest.mark.django_db
def test_end_to_end_chain_with_engine_seam_mocked(user, make_pack, tmp_path, monkeypatch):
    # Real resolve -> load SDL -> plan -> apply -> CmsRaesDispatchPort.realize;
    # only the engine service is mocked so no real provisioning is dispatched.
    from django.conf import settings

    from engine.services import RaesRangeRef

    root = make_pack(tmp_path / _PACK_REF, name="raes-launch")
    monkeypatch.setattr(settings, "RAES_PACKAGE_ROOT", str(tmp_path))
    captured = {}

    def fake_create_raes_range(
        *,
        request_id,
        user_id,
        compiled_plan,
        backend_admission=None,
        bindings=None,
        workspace_id=None,
        egress_mode=None,
    ):
        captured["kind"] = compiled_plan.get("kind")
        captured["request_id"] = request_id
        captured["delivery_bindings"] = bindings.delivery if bindings else ()
        return RaesRangeRef(request_id=request_id, accepted=True, status="accepted", range_id="rng-1")

    monkeypatch.setattr("cms.raes.dispatch.create_raes_range", fake_create_raes_range)
    _make_source(user, package_digest=pack_digest(root))
    ctx = create_raes_native_range(user, "raes-launch")

    assert ctx.request_id is not None
    assert captured["kind"] == "raes_provisioning_plan"
    assert captured["request_id"] == str(ctx.request_id)
    assert RangeInstance.objects.get(request__request_id=ctx.request_id).status == ResourceStatus.PROVISIONING.value


@pytest.mark.django_db
def test_unsatisfiable_artifact_requirement_fails_launch_closed(user, make_pack, tmp_path, monkeypatch):
    # An authored artifact requirement the backend cannot satisfy raises
    # ArtifactSatisfactionError in the dispatch resolver (ADR-034-R8, fail closed).
    # The launch must surface a domain CMSError -- the range is not accepted -- and
    # the engine seam is never reached, rather than an unhandled 500 or a fall-through.
    from django.conf import settings

    from shared.raes.artifact_inventory import ArtifactSatisfactionError

    root = make_pack(tmp_path / _PACK_REF, name="raes-launch")
    monkeypatch.setattr(settings, "RAES_PACKAGE_ROOT", str(tmp_path))

    def _unsatisfiable(*_args, **_kwargs):
        raise ArtifactSatisfactionError("artifact requirement at provision.node.web is unsatisfiable")

    monkeypatch.setattr("shared.raes.artifact_inventory.resolve_plan_artifact_bindings", _unsatisfiable)
    monkeypatch.setattr(
        "cms.raes.dispatch.create_raes_range",
        lambda **_kwargs: pytest.fail("an unsatisfiable requirement must not reach the engine seam"),
    )
    _make_source(user, package_digest=pack_digest(root))

    with pytest.raises(CMSError):
        create_raes_native_range(user, "raes-launch")


@pytest.mark.django_db
def test_launch_rejects_pack_mutated_after_registration(user, make_pack, tmp_path, monkeypatch):
    from django.conf import settings

    root = make_pack(tmp_path / _PACK_REF, name="raes-launch")
    registered_digest = pack_digest(root)
    _make_source(user, package_digest=registered_digest)
    (root / "docs" / "concepts.md").write_text("mutated after registration\n", encoding="utf-8")
    monkeypatch.setattr(settings, "RAES_PACKAGE_ROOT", str(tmp_path))
    monkeypatch.setattr(
        "cms.raes.dispatch.create_raes_range",
        lambda **_kwargs: pytest.fail("mutated content reached the dispatch boundary"),
    )

    with pytest.raises(CMSError, match="content identity could not be verified"):
        create_raes_native_range(user, "raes-launch")

    instance = RangeInstance.all_objects.get(scenario_id="raes-launch")
    assert instance.status == ResourceStatus.FAILED.value


@pytest.mark.django_db
def test_launch_rejects_valid_pack_resealed_after_registration(user, make_pack, tmp_path, monkeypatch):
    from django.conf import settings

    root = make_pack(tmp_path / _PACK_REF, name="raes-launch")
    registered_digest = pack_digest(root)
    _make_source(user, package_digest=registered_digest)
    (root / "docs" / "concepts.md").write_text("valid replacement bytes\n", encoding="utf-8")
    replacement_digest = write_pack_content_manifest(root, "raes-launch")
    assert replacement_digest != registered_digest
    monkeypatch.setattr(settings, "RAES_PACKAGE_ROOT", str(tmp_path))
    monkeypatch.setattr(
        "cms.raes.dispatch.create_raes_range",
        lambda **_kwargs: pytest.fail("replacement content reached the dispatch boundary"),
    )

    with pytest.raises(CMSError, match="no longer matches registration"):
        create_raes_native_range(user, "raes-launch")

    instance = RangeInstance.all_objects.get(scenario_id="raes-launch")
    assert instance.status == ResourceStatus.FAILED.value


@pytest.fixture
def object_bucket(monkeypatch):
    from django.conf import settings

    monkeypatch.setattr(settings, "RAES_PACKAGE_BUCKET", "raes-pkgs")


def _make_object_source(user, package_digest, scenario_id="raes-launch"):
    return _make_source(
        user,
        scenario_id=scenario_id,
        source_kind="object",
        package_ref="mypack.tar.gz",
        package_digest=package_digest,
    )


def _patch_object_stage(monkeypatch, pack_root):
    """Stub the object resolver to yield a real on-disk pack (the download +
    safe-extract path is unit-tested in tests/shared/raes/test_object_source.py),
    so this drives the launch-side validate -> digest -> dispatch wiring."""
    from contextlib import contextmanager

    @contextmanager
    def fake_stage(**_kwargs):
        yield pack_root

    monkeypatch.setattr("shared.raes.object_source.stage_object_pack", fake_stage)
    monkeypatch.setattr("shared.cloud.get_object_storage", lambda: object())


class TestObjectPackageLaunch:
    @pytest.mark.django_db
    def test_object_launch_validates_and_dispatches(self, user, object_bucket, make_pack, tmp_path, monkeypatch):
        from engine.services import RaesRangeRef

        root = make_pack(tmp_path / "raes-launch", name="raes-launch")
        _make_object_source(user, pack_digest(root))
        _patch_object_stage(monkeypatch, root)
        captured = {}

        def fake_create_raes_range(
            *,
            request_id,
            user_id,
            compiled_plan,
            backend_admission=None,
            bindings=None,
            workspace_id=None,
            egress_mode=None,
        ):
            captured["kind"] = compiled_plan.get("kind")
            return RaesRangeRef(request_id=request_id, accepted=True, status="accepted", range_id="rng-1")

        monkeypatch.setattr("cms.raes.dispatch.create_raes_range", fake_create_raes_range)
        ctx = create_raes_native_range(user, "raes-launch")

        assert captured["kind"] == "raes_provisioning_plan"
        instance = RangeInstance.objects.get(request__request_id=ctx.request_id)
        assert instance.status == ResourceStatus.PROVISIONING.value

    @pytest.mark.django_db
    def test_object_launch_rejects_digest_mismatch(self, user, object_bucket, make_pack, tmp_path, monkeypatch):
        root = make_pack(tmp_path / "raes-launch", name="raes-launch")
        _make_object_source(user, "sha256:" + "b" * 64)
        _patch_object_stage(monkeypatch, root)
        monkeypatch.setattr(
            "cms.raes.dispatch.create_raes_range",
            lambda **_kwargs: pytest.fail("mismatched object pack reached the dispatch boundary"),
        )

        with pytest.raises(CMSError, match="no longer matches registration"):
            create_raes_native_range(user, "raes-launch")
        assert RangeInstance.all_objects.get(scenario_id="raes-launch").status == ResourceStatus.FAILED.value

    @pytest.mark.django_db
    def test_object_launch_rejects_identity_mismatch(self, user, object_bucket, make_pack, tmp_path, monkeypatch):
        # Staged pack's validated identity ("other-name") must equal the
        # registered scenario_id ("raes-launch") or launch fails closed.
        root = make_pack(tmp_path / "other-name", name="other-name")
        _make_object_source(user, pack_digest(root), scenario_id="raes-launch")
        _patch_object_stage(monkeypatch, root)
        monkeypatch.setattr(
            "cms.raes.dispatch.create_raes_range",
            lambda **_kwargs: pytest.fail("identity-mismatched object pack reached the dispatch boundary"),
        )

        with pytest.raises(CMSError, match="identity does not match"):
            create_raes_native_range(user, "raes-launch")

    @pytest.mark.django_db
    def test_object_launch_rejects_invalid_pack(self, user, object_bucket, make_pack, tmp_path, monkeypatch):
        # Object registration defers content validation to launch, so a staged
        # pack that fails validate_pack (here: missing pack.yaml) must fail closed
        # at dispatch. This pins the _dispatch_object_raes_package
        # PackValidationError branch.
        root = make_pack(tmp_path / "raes-launch", name="raes-launch", pack_yaml=None)
        # validate_pack fails before the digest check, so the registered digest is
        # irrelevant here.
        _make_object_source(user, "sha256:" + "c" * 64)
        _patch_object_stage(monkeypatch, root)
        monkeypatch.setattr(
            "cms.raes.dispatch.create_raes_range",
            lambda **_kwargs: pytest.fail("invalid object pack reached the dispatch boundary"),
        )

        with pytest.raises(CMSError, match="failed validation"):
            create_raes_native_range(user, "raes-launch")
        assert RangeInstance.all_objects.get(scenario_id="raes-launch").status == ResourceStatus.FAILED.value

    @pytest.mark.django_db
    def test_object_not_launchable_without_bucket(self, user, make_pack, tmp_path, monkeypatch):
        # No object_bucket fixture: an object row is non-launchable when no
        # package bucket is configured, so admission refuses it before dispatch.
        from django.conf import settings

        monkeypatch.setattr(settings, "RAES_PACKAGE_BUCKET", "")
        root = make_pack(tmp_path / "raes-launch", name="raes-launch")
        _make_object_source(user, pack_digest(root))

        with pytest.raises(CMSError, match="not available for launch"):
            create_raes_native_range(user, "raes-launch")
        # Refused at admission, before any range row is created.
        assert not RangeInstance.all_objects.filter(user_id=user.id).exists()


@pytest.mark.django_db
def test_ec2_allowlist_denied_before_reservation_or_dispatch(user, monkeypatch, settings):
    from unittest.mock import Mock

    settings.CLOUD_PROVIDER = "aws"
    _make_source(user)
    monkeypatch.setattr("cms.services._range_workspace.resolve_effective_egress_mode", lambda _: "allowlist")
    dispatch = Mock()
    monkeypatch.setattr(_DISPATCH, dispatch)
    with pytest.raises(CMSError, match="allowlist"):
        create_raes_native_range(user, "raes-launch")
    assert not RangeInstance.objects.filter(user_id=user.id).exists()
    dispatch.assert_not_called()
