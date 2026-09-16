"""Unit tests for engine get_range_pause_resume_capability (#614).

Pure: patches get_range_status so no DB is needed. Verifies the realized asset
mix is classified against the persisted range-backend binding.
"""

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
