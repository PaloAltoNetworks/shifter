"""Workspace scope binding on the canonical RAES launch path (ADR-046-R3, #1325)."""

from __future__ import annotations

import pytest

from cms.models import RaesPackageSource, RangeInstance
from cms.scenarios.pack_validation import pack_digest
from cms.services import create_raes_native_range
from workspaces import services as workspace_services
from workspaces.models import Workspace

_PACK_REF = "packs/raes-ws"


@pytest.fixture
def user(django_user_model):
    return django_user_model.objects.create(username="raes-ws-launcher")


def _make_source(user, digest, scenario_id="raes-ws"):
    return RaesPackageSource.objects.create(
        scenario_id=scenario_id,
        contract_kind="raes",
        contract_profile="shifter",
        source_kind="repo",
        package_ref=_PACK_REF,
        package_version="1.0.0",
        package_digest=digest,
        conformance_status="passed",
        registered_by=user,
    )


@pytest.mark.django_db
def test_raes_launch_binds_cms_rows_and_carries_the_scope_to_engine(user, make_pack, tmp_path, monkeypatch):
    """The scope reaches the engine seam as a trusted argument, like backend_admission."""
    from django.conf import settings

    from engine.services import RaesRangeRef

    root = make_pack(tmp_path / _PACK_REF, name="raes-ws")
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
        captured["workspace_id"] = workspace_id
        captured["egress_mode"] = egress_mode
        return RaesRangeRef(request_id=request_id, accepted=True, status="accepted", range_id="rng-1")

    monkeypatch.setattr("cms.raes.dispatch.create_raes_range", fake_create_raes_range)
    _make_source(user, pack_digest(root))

    # Opt the launcher's workspace into zero egress so the effective mode CMS
    # resolves under the workspace lock is a non-default value that must be
    # forwarded to the engine seam (PLAT-238), not silently dropped.
    expected = workspace_services.resolve_personal_workspace(user).workspace_id
    workspace_services.set_workspace_egress_policy(
        user,
        Workspace.objects.get(pk=expected).uuid,
        "none",
        audit=workspace_services.WorkspaceAuditContext(actor_type="user", actor_id=user.pk),
    )

    ctx = create_raes_native_range(user, "raes-ws")

    instance = RangeInstance.objects.get(request__request_id=ctx.request_id)
    assert instance.workspace_id == expected
    assert instance.request.workspace_id == expected
    assert captured["workspace_id"] == expected
    assert captured["egress_mode"] == "none"
