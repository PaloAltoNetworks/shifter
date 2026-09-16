"""Artifact identity measures complete raw bytes, never a provider descriptor."""

import hashlib
import importlib.util
import io
from pathlib import Path

import pytest


def module():
    spec = importlib.util.spec_from_file_location(
        "preparation_raw_disk", Path(__file__).parents[1] / "preparation/raw_disk.py"
    )
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def test_raw_identity_includes_every_byte_and_zero_filled_tail():
    data = b"partition and filesystem bytes" + b"\0" * 8192
    result = module().measure_stream(io.BytesIO(data), len(data))
    assert result == {"raw_disk_digest": "sha256:" + hashlib.sha256(data).hexdigest(), "size_bytes": len(data)}
    assert result != module().measure_stream(io.BytesIO(data[:-1]), len(data) - 1)


@pytest.mark.parametrize("data,size", [(b"short", 12), (b"longer", 2), (b"", 0), (b"x", 201 * 1024**3)])
def test_incomplete_or_unbounded_measurements_are_not_artifact_identity(data, size):
    with pytest.raises(ValueError):
        module().measure_stream(io.BytesIO(data), size)


def test_regular_file_cannot_pose_as_read_only_attached_disk(tmp_path):
    regular = tmp_path / "pretend-disk"
    regular.write_bytes(b"not a block device")
    with pytest.raises(ValueError):
        module().measure_device(regular)


def test_sanitization_refuses_private_authorized_keys_and_build_residue(tmp_path):
    root = tmp_path / "candidate"
    (root / "etc").mkdir(parents=True)
    (root / "etc/machine-id").write_text("")
    module().verify_sanitized_root(root)
    (root / "root/.ssh").mkdir(parents=True)
    (root / "root/.ssh/authorized_keys").write_text("fixture public key")
    with pytest.raises(ValueError):
        module().verify_sanitized_root(root)


def test_sanitization_does_not_follow_foreign_root_paths(tmp_path):
    root = tmp_path / "candidate"
    root.mkdir()
    (root / "etc").symlink_to(tmp_path)
    with pytest.raises(ValueError):
        module().verify_sanitized_root(root)


def test_sanitization_rejects_a_separate_persisted_dbus_identity(tmp_path):
    (tmp_path / "etc").mkdir()
    (tmp_path / "etc/machine-id").write_text("")
    (tmp_path / "var/lib/dbus").mkdir(parents=True)
    (tmp_path / "var/lib/dbus/machine-id").write_text("previous-machine-identity")
    with pytest.raises(ValueError):
        module().verify_sanitized_root(tmp_path)


def test_sanitization_rejects_cached_private_metadata_scripts(tmp_path):
    (tmp_path / "tmp/metadata-script123").mkdir(parents=True)
    (tmp_path / "tmp/metadata-script123/startup-script").write_text("private build context")
    with pytest.raises(ValueError, match="metadata script"):
        module().verify_sanitized_root(tmp_path)
