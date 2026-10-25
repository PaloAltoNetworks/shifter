"""Unit tests for engine get_range_pause_resume_capability (#614).

Pure: patches get_range_status so no DB is needed. Verifies the realized asset
mix is classified against the persisted range-backend binding.
"""

import pytest

import engine.services._range as range_service


def _patch_status(monkeypatch, instances, backend):
    monkeypatch.setattr(
        range_service, "get_range_status", lambda rid: {"instances": instances, "range_backend": backend}
    )


def test_all_gce_range_is_supported(monkeypatch):
    _patch_status(monkeypatch, [{"uuid": "a", "cloud_provider": "gcp", "asset_type": "gce_vm"}], "gce")
    assert range_service.get_range_pause_resume_capability(1).supported is True


def test_vm_runtime_range_is_supported(monkeypatch):
    _patch_status(monkeypatch, [{"uuid": "a", "cloud_provider": "gcp", "asset_type": "vm_runtime_vm"}], "gdc")
    assert range_service.get_range_pause_resume_capability(1).supported is True


def test_pod_backed_range_is_unsupported(monkeypatch):
    _patch_status(
        monkeypatch,
        [
            {"uuid": "a", "cloud_provider": "gcp", "asset_type": "vm_runtime_vm"},
            {"uuid": "b", "cloud_provider": "gcp", "asset_type": "scenario_pod"},
        ],
        "gdc",
    )
    cap = range_service.get_range_pause_resume_capability(1)
    assert cap.supported is False
    assert ("gcp", "scenario_pod") in cap.unsupported_assets


def test_asset_disagreeing_with_binding_is_unsupported(monkeypatch):
    # A gce_vm asset recorded on a gdc-bound range disagrees with the binding.
    _patch_status(monkeypatch, [{"uuid": "a", "cloud_provider": "gcp", "asset_type": "gce_vm"}], "gdc")
    assert range_service.get_range_pause_resume_capability(1).supported is False


def test_unprovisioned_range_is_vacuously_supported(monkeypatch):
    monkeypatch.setattr(range_service, "get_range_status", lambda rid: None)
    assert range_service.get_range_pause_resume_capability(1).supported is True


@pytest.mark.django_db
@pytest.mark.parametrize("backend", ["gce", "ec2"])
@pytest.mark.parametrize(("operation", "status"), [("pause", "ready"), ("resume", "paused")])
def test_native_range_refuses_power_operations_before_dispatch(
    django_user_model, monkeypatch, backend, operation, status
):
    from unittest.mock import Mock
    from uuid import uuid4

    from engine.models import Range, Request
    from engine.services import pause_range, resume_range

    actor = django_user_model.objects.create_user(username="native-lifecycle")
    request = Request.objects.create(request_id=uuid4(), request_type="range", user=actor)
    range_obj = Range.objects.create(
        user=actor,
        request=request,
        workspace_id=1,
        range_backend=backend,
        range_config={"kind": "raes_provisioning_plan"},
        status=status,
        provisioned_instances=[{"cloud_provider": "gcp" if backend == "gce" else "aws", "asset_type": f"{backend}_vm"}],
    )
    dispatch = Mock(side_effect=AssertionError("Native ranges cannot use legacy power dispatch"))
    monkeypatch.setattr("engine.ecs.start_range_operation", dispatch)
    capability = range_service.get_range_pause_resume_capability(range_obj.pk)
    assert not capability.supported
    assert capability.reason == "Pause and resume are not available for native scenario ranges."
    result = (pause_range if operation == "pause" else resume_range)(request.request_id)
    assert result is False
    range_obj.refresh_from_db()
    assert range_obj.status == status
    dispatch.assert_not_called()
