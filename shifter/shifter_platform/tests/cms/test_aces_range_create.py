"""Tests for the ACES-native launch service + dispatcher (#1479).

Covers create_aces_native_range (flag gate, CMS bookkeeping, active-range
admission, launchability, failure handling) and create_range_dispatch routing.
One integration test drives the real resolve -> load -> plan -> apply -> port
chain with only the engine seam (engine.services.create_aces_range) mocked, so
no real provisioning is triggered.
"""

from __future__ import annotations

import pytest

from cms.exceptions import CMSError
from cms.models import AcesPackageSource, RangeInstance
from cms.scenarios.pack_validation import pack_digest
from cms.services import create_aces_native_range, create_range_dispatch
from shared.enums import ResourceStatus
from tests.cms.conftest import write_pack_content_manifest

_PACK_REF = "packs/aces-launch"
_DISPATCH = "cms.services._aces_range_create._dispatch_aces_package"


@pytest.fixture
def user(django_user_model):
    return django_user_model.objects.create(username="aces-launcher")


@pytest.fixture
def native_on(monkeypatch):
    from django.conf import settings

    monkeypatch.setattr(settings, "ACES_NATIVE_PROVISIONING_ENABLED", True)


def _make_source(user, scenario_id="aces-launch", **overrides):
    fields = {
        "scenario_id": scenario_id,
        "contract_kind": "aces",
        "contract_profile": "shifter",
        "source_kind": "repo",
        "package_ref": _PACK_REF,
        "package_version": "1.0.0",
        "package_digest": "sha256:" + "a" * 64,
        "conformance_status": "passed",
        "registered_by": user,
    }
    fields.update(overrides)
    return AcesPackageSource.objects.create(**fields)


@pytest.mark.django_db
def test_flag_off_refuses(user, monkeypatch):
    from django.conf import settings

    monkeypatch.setattr(settings, "ACES_NATIVE_PROVISIONING_ENABLED", False)
    with pytest.raises(CMSError):
        create_aces_native_range(user, "aces-launch")


@pytest.mark.django_db
def test_launch_persists_bookkeeping_and_dispatches(user, native_on, monkeypatch):
    _make_source(user)
    seen = {}
    monkeypatch.setattr(
        _DISPATCH,
        lambda request_id, u, source, backend_admission=None: seen.update(
            ref=source.package_ref,
            digest=source.package_digest,
        ),
    )
    ctx = create_aces_native_range(user, "aces-launch")

    assert ctx.request_id is not None
    assert seen["ref"] == _PACK_REF
    assert seen["digest"] == "sha256:" + "a" * 64
    instance = RangeInstance.objects.get(request__request_id=ctx.request_id)
    assert instance.scenario_id == "aces-launch"
    assert instance.range_spec is None  # no cyberscript RangeSpec for ACES
    assert instance.status == ResourceStatus.PROVISIONING.value


@pytest.mark.django_db
def test_dispatch_failure_marks_failed_and_raises(user, native_on, monkeypatch):
    _make_source(user)

    def boom(*_args, **_kwargs):
        raise CMSError("dispatch failed")

    monkeypatch.setattr(_DISPATCH, boom)
    with pytest.raises(CMSError):
        create_aces_native_range(user, "aces-launch")
    # FAILED is terminal and soft-deletes the row, so query via all_objects.
    instance = RangeInstance.all_objects.get(scenario_id="aces-launch")
    assert instance.status == ResourceStatus.FAILED.value


@pytest.mark.django_db
def test_non_launchable_pending_refused(user, native_on, monkeypatch):
    _make_source(user, conformance_status="pending")
    monkeypatch.setattr(_DISPATCH, lambda *a, **k: None)
    with pytest.raises(CMSError):
        create_aces_native_range(user, "aces-launch")


@pytest.mark.django_db
def test_active_range_refused(user, native_on, monkeypatch):
    _make_source(user)
    monkeypatch.setattr(_DISPATCH, lambda *a, **k: None)
    create_aces_native_range(user, "aces-launch")
    with pytest.raises(CMSError):
        create_aces_native_range(user, "aces-launch")


@pytest.mark.django_db
def test_live_fire_gate_denies_gdc_before_dispatch(user, native_on, monkeypatch):
    # Issue #1348 / ADR-030: the ACES-native path shares the same live-fire gate;
    # a GDC selector is denied before the pack is resolved or dispatched.
    from django.conf import settings

    _make_source(user)
    dispatched = {"called": False}
    monkeypatch.setattr(_DISPATCH, lambda *a, **k: dispatched.update(called=True))
    monkeypatch.setattr(settings, "CLOUD_PROVIDER", "gcp")
    monkeypatch.setenv("GCP_RANGE_BACKEND", "gdc")

    with pytest.raises(CMSError, match=r"not an approved live-fire|GCE VM range-cell"):
        create_aces_native_range(user, "aces-launch")

    assert dispatched["called"] is False
    assert not RangeInstance.all_objects.filter(user_id=user.id).exists()


@pytest.mark.django_db
def test_live_fire_gate_admits_gce(user, native_on, monkeypatch):
    from django.conf import settings

    _make_source(user)
    monkeypatch.setattr(_DISPATCH, lambda *a, **k: None)
    monkeypatch.setattr(settings, "CLOUD_PROVIDER", "gcp")
    monkeypatch.setenv("GCP_RANGE_BACKEND", "gce")

    ctx = create_aces_native_range(user, "aces-launch")

    assert ctx.request_id is not None
    assert RangeInstance.objects.filter(user_id=user.id).exists()


@pytest.mark.django_db
def test_dispatch_routes_cyberscript_when_flag_off(user, monkeypatch):
    from django.conf import settings

    monkeypatch.setattr(settings, "ACES_NATIVE_PROVISIONING_ENABLED", False)
    routed = {}
    monkeypatch.setattr(
        "cms.services._aces_range_create.create_range",
        lambda *a, **k: routed.setdefault("path", "cyberscript"),
    )
    create_range_dispatch(user, "basic", {})
    assert routed["path"] == "cyberscript"


@pytest.mark.django_db
def test_dispatch_routes_native_for_aces_when_flag_on(user, native_on, monkeypatch):
    _make_source(user, scenario_id="aces-x")
    routed = {}
    monkeypatch.setattr(
        "cms.services._aces_range_create.create_aces_native_range",
        lambda u, s, *, range_source=None: routed.setdefault("scenario", s),
    )
    create_range_dispatch(user, "aces-x", {})
    assert routed["scenario"] == "aces-x"


@pytest.mark.django_db
def test_dispatch_routes_cyberscript_for_non_aces_when_flag_on(user, native_on, monkeypatch):
    routed = {}
    monkeypatch.setattr(
        "cms.services._aces_range_create.create_range",
        lambda *a, **k: routed.setdefault("path", "cyberscript"),
    )
    create_range_dispatch(user, "basic", {})
    assert routed["path"] == "cyberscript"


@pytest.mark.django_db
def test_end_to_end_chain_with_engine_seam_mocked(user, native_on, make_pack, tmp_path, monkeypatch):
    # Real resolve -> load SDL -> plan -> apply -> CmsAcesDispatchPort.realize;
    # only the engine service is mocked so no real provisioning is dispatched.
    from django.conf import settings

    from engine.services import AcesRangeRef

    root = make_pack(tmp_path / _PACK_REF, name="aces-launch")
    monkeypatch.setattr(settings, "ACES_PACKAGE_ROOT", str(tmp_path))
    captured = {}

    def fake_create_aces_range(*, request_id, user_id, compiled_plan, backend_admission=None, delivery_bindings=()):
        captured["kind"] = compiled_plan.get("kind")
        captured["request_id"] = request_id
        captured["delivery_bindings"] = delivery_bindings
        return AcesRangeRef(request_id=request_id, accepted=True, status="accepted", range_id="rng-1")

    monkeypatch.setattr("cms.aces.dispatch.create_aces_range", fake_create_aces_range)
    _make_source(user, package_digest=pack_digest(root))
    ctx = create_aces_native_range(user, "aces-launch")

    assert ctx.request_id is not None
    assert captured["kind"] == "aces_provisioning_plan"
    assert captured["request_id"] == str(ctx.request_id)
    assert RangeInstance.objects.get(request__request_id=ctx.request_id).status == ResourceStatus.PROVISIONING.value


@pytest.mark.django_db
def test_launch_rejects_pack_mutated_after_registration(user, native_on, make_pack, tmp_path, monkeypatch):
    from django.conf import settings

    root = make_pack(tmp_path / _PACK_REF, name="aces-launch")
    registered_digest = pack_digest(root)
    _make_source(user, package_digest=registered_digest)
    (root / "docs" / "concepts.md").write_text("mutated after registration\n", encoding="utf-8")
    monkeypatch.setattr(settings, "ACES_PACKAGE_ROOT", str(tmp_path))
    monkeypatch.setattr(
        "cms.aces.dispatch.create_aces_range",
        lambda **_kwargs: pytest.fail("mutated content reached the dispatch boundary"),
    )

    with pytest.raises(CMSError, match="content identity could not be verified"):
        create_aces_native_range(user, "aces-launch")

    instance = RangeInstance.all_objects.get(scenario_id="aces-launch")
    assert instance.status == ResourceStatus.FAILED.value


@pytest.mark.django_db
def test_launch_rejects_valid_pack_resealed_after_registration(user, native_on, make_pack, tmp_path, monkeypatch):
    from django.conf import settings

    root = make_pack(tmp_path / _PACK_REF, name="aces-launch")
    registered_digest = pack_digest(root)
    _make_source(user, package_digest=registered_digest)
    (root / "docs" / "concepts.md").write_text("valid replacement bytes\n", encoding="utf-8")
    replacement_digest = write_pack_content_manifest(root, "aces-launch")
    assert replacement_digest != registered_digest
    monkeypatch.setattr(settings, "ACES_PACKAGE_ROOT", str(tmp_path))
    monkeypatch.setattr(
        "cms.aces.dispatch.create_aces_range",
        lambda **_kwargs: pytest.fail("replacement content reached the dispatch boundary"),
    )

    with pytest.raises(CMSError, match="no longer matches registration"):
        create_aces_native_range(user, "aces-launch")

    instance = RangeInstance.all_objects.get(scenario_id="aces-launch")
    assert instance.status == ResourceStatus.FAILED.value


@pytest.fixture
def object_bucket(monkeypatch):
    from django.conf import settings

    monkeypatch.setattr(settings, "ACES_PACKAGE_BUCKET", "aces-pkgs")


def _make_object_source(user, package_digest, scenario_id="aces-launch"):
    return _make_source(
        user,
        scenario_id=scenario_id,
        source_kind="object",
        package_ref="mypack.tar.gz",
        package_digest=package_digest,
    )


def _patch_object_stage(monkeypatch, pack_root):
    """Stub the object resolver to yield a real on-disk pack (the download +
    safe-extract path is unit-tested in tests/shared/aces/test_object_source.py),
    so this drives the launch-side validate -> digest -> dispatch wiring."""
    from contextlib import contextmanager

    @contextmanager
    def fake_stage(**_kwargs):
        yield pack_root

    monkeypatch.setattr("shared.aces.object_source.stage_object_pack", fake_stage)
    monkeypatch.setattr("shared.cloud.get_object_storage", lambda: object())


class TestObjectPackageLaunch:
    @pytest.mark.django_db
    def test_object_launch_validates_and_dispatches(
        self, user, native_on, object_bucket, make_pack, tmp_path, monkeypatch
    ):
        from engine.services import AcesRangeRef

        root = make_pack(tmp_path / "aces-launch", name="aces-launch")
        _make_object_source(user, pack_digest(root))
        _patch_object_stage(monkeypatch, root)
        captured = {}

        def fake_create_aces_range(*, request_id, user_id, compiled_plan, backend_admission=None, delivery_bindings=()):
            captured["kind"] = compiled_plan.get("kind")
            return AcesRangeRef(request_id=request_id, accepted=True, status="accepted", range_id="rng-1")

        monkeypatch.setattr("cms.aces.dispatch.create_aces_range", fake_create_aces_range)
        ctx = create_aces_native_range(user, "aces-launch")

        assert captured["kind"] == "aces_provisioning_plan"
        instance = RangeInstance.objects.get(request__request_id=ctx.request_id)
        assert instance.status == ResourceStatus.PROVISIONING.value

    @pytest.mark.django_db
    def test_object_launch_rejects_digest_mismatch(
        self, user, native_on, object_bucket, make_pack, tmp_path, monkeypatch
    ):
        root = make_pack(tmp_path / "aces-launch", name="aces-launch")
        _make_object_source(user, "sha256:" + "b" * 64)
        _patch_object_stage(monkeypatch, root)
        monkeypatch.setattr(
            "cms.aces.dispatch.create_aces_range",
            lambda **_kwargs: pytest.fail("mismatched object pack reached the dispatch boundary"),
        )

        with pytest.raises(CMSError, match="no longer matches registration"):
            create_aces_native_range(user, "aces-launch")
        assert RangeInstance.all_objects.get(scenario_id="aces-launch").status == ResourceStatus.FAILED.value

    @pytest.mark.django_db
    def test_object_launch_rejects_identity_mismatch(
        self, user, native_on, object_bucket, make_pack, tmp_path, monkeypatch
    ):
        # Staged pack's validated identity ("other-name") must equal the
        # registered scenario_id ("aces-launch") or launch fails closed.
        root = make_pack(tmp_path / "other-name", name="other-name")
        _make_object_source(user, pack_digest(root), scenario_id="aces-launch")
        _patch_object_stage(monkeypatch, root)
        monkeypatch.setattr(
            "cms.aces.dispatch.create_aces_range",
            lambda **_kwargs: pytest.fail("identity-mismatched object pack reached the dispatch boundary"),
        )

        with pytest.raises(CMSError, match="identity does not match"):
            create_aces_native_range(user, "aces-launch")

    @pytest.mark.django_db
    def test_object_launch_rejects_invalid_pack(self, user, native_on, object_bucket, make_pack, tmp_path, monkeypatch):
        # Object registration defers content validation to launch, so a staged
        # pack that fails validate_pack (here: missing pack.yaml) must fail closed
        # at dispatch. This pins the _dispatch_object_aces_package
        # PackValidationError branch.
        root = make_pack(tmp_path / "aces-launch", name="aces-launch", pack_yaml=None)
        # validate_pack fails before the digest check, so the registered digest is
        # irrelevant here.
        _make_object_source(user, "sha256:" + "c" * 64)
        _patch_object_stage(monkeypatch, root)
        monkeypatch.setattr(
            "cms.aces.dispatch.create_aces_range",
            lambda **_kwargs: pytest.fail("invalid object pack reached the dispatch boundary"),
        )

        with pytest.raises(CMSError, match="failed validation"):
            create_aces_native_range(user, "aces-launch")
        assert RangeInstance.all_objects.get(scenario_id="aces-launch").status == ResourceStatus.FAILED.value

    @pytest.mark.django_db
    def test_object_not_launchable_without_bucket(self, user, native_on, make_pack, tmp_path, monkeypatch):
        # No object_bucket fixture: an object row is non-launchable when no
        # package bucket is configured, so admission refuses it before dispatch.
        from django.conf import settings

        monkeypatch.setattr(settings, "ACES_PACKAGE_BUCKET", "")
        root = make_pack(tmp_path / "aces-launch", name="aces-launch")
        _make_object_source(user, pack_digest(root))

        with pytest.raises(CMSError):
            create_aces_native_range(user, "aces-launch")
