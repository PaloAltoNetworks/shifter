"""Image sanitization removes default guest identities as well as build staging."""

import os
from pathlib import Path

import pytest

from preparation.sanitize_guest import sanitize_root


def test_all_guest_home_ssh_material_is_removed_without_touching_service_bytes(tmp_path):
    for name in ("root", "home/ubuntu", "home/private-user"):
        path = tmp_path / name / ".ssh"
        path.mkdir(parents=True)
        (path / "authorized_keys").write_text("fixture public key")
    for relative in ("var/lib/shifter-preparation", "var/lib/cloud/instances", "tmp/metadata-script123"):
        path = tmp_path / relative
        path.mkdir(parents=True)
        (path / "private-source").write_text("contained build source")
    (tmp_path / "etc/ssh").mkdir(parents=True)
    (tmp_path / "etc/ssh/ssh_host_rsa_key").write_text("fixture key")
    (tmp_path / "etc/machine-id").write_text("old identity")
    (tmp_path / "var/lib/dbus").mkdir(parents=True)
    (tmp_path / "var/lib/dbus/machine-id").write_text("old dbus identity")
    service = tmp_path / "opt/service"
    service.parent.mkdir()
    service.write_text("required service bytes")
    previous_mask = os.umask(0o077)
    try:
        sanitize_root(tmp_path)
    finally:
        os.umask(previous_mask)
    assert service.read_text() == "required service bytes"
    assert not list(tmp_path.glob("home/*/.ssh"))
    assert not (tmp_path / "root/.ssh").exists()
    assert not (tmp_path / "var/lib/shifter-preparation").exists()
    assert not (tmp_path / "var/lib/cloud/instances").exists()
    assert not list((tmp_path / "tmp").iterdir())
    assert not list((tmp_path / "etc/ssh").glob("ssh_host_*"))
    assert (tmp_path / "etc/machine-id").read_bytes() == b""
    assert (tmp_path / "etc/machine-id").stat().st_mode & 0o777 == 0o644
    assert (tmp_path / "var/lib/dbus/machine-id").readlink() == Path("../../../etc/machine-id")


def test_sanitization_never_traverses_a_redirected_temporary_directory(tmp_path):
    root = tmp_path / "candidate"
    (root / "etc").mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    private = outside / "metadata-script-owned-elsewhere"
    private.write_text("must survive")
    (root / "tmp").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError):
        sanitize_root(root)
    assert private.read_text() == "must survive"
