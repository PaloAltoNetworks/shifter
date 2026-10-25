"""Tests for the fenced ArtifactBinding transport carrier (#1580, ADR-034-R8)."""

from __future__ import annotations

import pytest

from shared.raes.artifact_binding import MAX_ARTIFACT_BINDINGS, ArtifactBinding, ArtifactBindingError

_DIGEST = "sha256:" + "a" * 64


def _row(**overrides: object) -> dict[str, object]:
    row = {
        "target": "provision.node.web",
        "requirement_id": "req-1",
        "artifact_id": "img-web",
        "version": "1.0.0",
        "digest": _DIGEST,
        "media_type": "application/vnd.raes.image",
        "mechanism": "exact-artifact",
        "acquisition": "local-lookup",
        "timing": "backend-preparation",
        "image_ref": "projects/x/global/images/web",
        "machine_type": "e2-medium",
        "disk_size_gb": 30,
        "disk_type": "pd-balanced",
    }
    row.update(overrides)
    return row


def test_round_trips_through_transport():
    binding = ArtifactBinding.from_transport(_row())
    assert ArtifactBinding.from_transport(binding.to_transport()) == binding
    assert binding.target == "provision.node.web"
    assert binding.image_ref == "projects/x/global/images/web"


def test_management_port_round_trip_and_legacy_digest_stability():
    binding = ArtifactBinding.from_transport(_row(management_ssh_port=2222, management_ssh_username="image-admin"))
    assert binding.management_ssh_port == 2222
    assert binding.management_ssh_username == "image-admin"
    assert ArtifactBinding.from_transport(binding.to_transport()) == binding
    legacy = ArtifactBinding.from_transport(_row())
    assert legacy.management_ssh_port == 22
    assert "management_ssh_port" not in legacy.to_transport()
    assert "management_ssh_username" not in legacy.to_transport()


@pytest.mark.parametrize("username", [None, "root;id", "user\nroot", "domain\\admin", "-option", "x" * 33])
def test_rejects_invalid_management_username(username):
    with pytest.raises(ArtifactBindingError, match="management_ssh_username"):
        ArtifactBinding.from_transport(_row(management_ssh_username=username))


@pytest.mark.parametrize("port", [0, -1, 65536, True, 22.5, "22", None])
def test_rejects_invalid_management_port(port):
    with pytest.raises(ArtifactBindingError, match="management_ssh_port"):
        ArtifactBinding.from_transport(_row(management_ssh_port=port))


def test_optional_sizing_defaults():
    binding = ArtifactBinding.from_transport(
        {k: v for k, v in _row().items() if k not in {"machine_type", "disk_size_gb", "disk_type"}}
    )
    assert binding.machine_type == ""
    assert binding.disk_size_gb is None
    assert binding.disk_type == ""


def test_rejects_unknown_key_so_a_secret_cannot_ride_along():
    row = _row(signed_url="https://secret")
    with pytest.raises(ArtifactBindingError, match="unexpected"):
        ArtifactBinding.from_transport(row)


def test_rejects_missing_required_field():
    row = _row()
    del row["image_ref"]
    with pytest.raises(ArtifactBindingError, match="missing"):
        ArtifactBinding.from_transport(row)


def test_rejects_non_canonical_digest():
    row = _row(digest="deadbeef")
    with pytest.raises(ArtifactBindingError, match="digest"):
        ArtifactBinding.from_transport(row)


def test_rejects_unknown_acquisition_and_timing():
    bad_acquisition = _row(acquisition="teleport")
    with pytest.raises(ArtifactBindingError, match="acquisition"):
        ArtifactBinding.from_transport(bad_acquisition)
    bad_timing = _row(timing="whenever")
    with pytest.raises(ArtifactBindingError, match="timing"):
        ArtifactBinding.from_transport(bad_timing)


def test_rejects_non_positive_disk_size():
    row = _row(disk_size_gb=0)
    with pytest.raises(ArtifactBindingError, match="disk_size_gb"):
        ArtifactBinding.from_transport(row)


def test_bound_is_declared():
    assert MAX_ARTIFACT_BINDINGS >= 1
