"""Behavior tests for the object-storage-backed ACES pack staging resolver (#1567).

Drives the real ``stage_object_pack`` against an injected fake ``ObjectStorage``
and real tar archives built in-memory, so the security-critical extraction
guards (size / entry-count caps, traversal / symlink / special-file rejection,
single-pack-root shape) and the always-clean-up contract are exercised through
the real code path. No cloud SDK is touched.
"""

from __future__ import annotations

import io
import tarfile
from pathlib import Path

import pytest

from shared.aces.object_source import _reject_unsafe_member, stage_object_pack
from shared.aces.package_loader import AcesPackageError
from shared.cloud.exceptions import CloudStorageError, ObjectPreconditionError

_MAX_ARCHIVE = 1_048_576
_MAX_UNCOMPRESSED = 4_194_304
_MAX_ENTRIES = 1000


class _FakeStorage:
    """Injected ObjectStorage stand-in that serves one in-memory archive."""

    def __init__(self, archive: bytes, *, identity: dict | None = None, download_error: Exception | None = None):
        self._archive = archive
        self._identity = identity or {"content_length": len(archive), "etag": "etag-1", "generation": 7}
        self._download_error = download_error
        self.download_calls: list[dict] = []

    def head_object(self, bucket: str, key: str) -> dict:
        return dict(self._identity)

    def download_object(self, bucket, key, dest_path, *, max_bytes, expected_identity=None):
        self.download_calls.append({"expected_identity": expected_identity, "max_bytes": max_bytes})
        if self._download_error is not None:
            raise self._download_error
        if len(self._archive) > max_bytes:
            raise CloudStorageError("archive exceeds max_bytes")
        Path(dest_path).write_bytes(self._archive)
        return {"content_length": len(self._archive), "etag": self._identity.get("etag", "e")}


def _tar(members: list[tarfile.TarInfo | tuple[str, bytes]], *, mode: str = "w:gz") -> bytes:
    """Build a tar archive; tuple entries become regular files, TarInfo added raw."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode=mode) as tar:
        for member in members:
            if isinstance(member, tuple):
                name, content = member
                info = tarfile.TarInfo(name)
                info.size = len(content)
                tar.addfile(info, io.BytesIO(content))
            else:
                tar.addfile(member, io.BytesIO(b"") if member.isreg() else None)
    return buf.getvalue()


def _good_pack(root: str = "mypack") -> bytes:
    return _tar(
        [
            (f"{root}/pack.yaml", b"name: mypack\n"),
            (f"{root}/sdl/scenario.sdl.yaml", b"nodes: []\n"),
        ]
    )


def _stage(storage, **overrides):
    kwargs = {
        "storage": storage,
        "bucket": "pkgs",
        "key": "mypack.tar.gz",
        "max_archive_bytes": _MAX_ARCHIVE,
        "max_uncompressed_bytes": _MAX_UNCOMPRESSED,
        "max_entries": _MAX_ENTRIES,
    }
    kwargs.update(overrides)
    return stage_object_pack(**kwargs)


class TestStageObjectPackHappyPath:
    def test_yields_single_pack_root_with_contents(self):
        storage = _FakeStorage(_good_pack("mypack"))
        with _stage(storage) as pack_root:
            assert pack_root.name == "mypack"
            assert (pack_root / "pack.yaml").read_text() == "name: mypack\n"
            assert (pack_root / "sdl" / "scenario.sdl.yaml").exists()

    def test_binds_download_to_head_identity(self):
        storage = _FakeStorage(_good_pack())
        with _stage(storage):
            pass
        assert storage.download_calls[0]["expected_identity"]["generation"] == 7

    def test_staging_dir_removed_on_exit(self):
        # Observe the real cleanup: the private staging dir (pack_root's
        # grandparent, <staging>/pack/<packname>) must not survive the context.
        storage = _FakeStorage(_good_pack())
        with _stage(storage) as pack_root:
            staging_root = pack_root.parents[1]
            assert staging_root.is_dir()
        assert not staging_root.exists()

    def test_staging_dir_removed_even_when_body_raises(self):
        storage = _FakeStorage(_good_pack())
        captured = {}
        with pytest.raises(RuntimeError), _stage(storage) as pack_root:
            captured["staging_root"] = pack_root.parents[1]
            raise RuntimeError("caller blew up")
        assert not captured["staging_root"].exists()


class TestStageObjectPackFailsClosed:
    def test_unconfigured_bucket_or_key(self):
        storage = _FakeStorage(_good_pack())
        with pytest.raises(AcesPackageError), _stage(storage, bucket=""):
            pass
        with pytest.raises(AcesPackageError), _stage(storage, key=""):
            pass

    def test_head_size_over_cap_fails_before_download(self):
        storage = _FakeStorage(_good_pack(), identity={"content_length": _MAX_ARCHIVE + 1, "etag": "e"})
        with pytest.raises(AcesPackageError), _stage(storage):
            pass
        assert storage.download_calls == []

    def test_too_many_entries(self):
        members = [(f"mypack/f{i}", b"x") for i in range(5)]
        storage = _FakeStorage(_tar(members))
        with pytest.raises(AcesPackageError), _stage(storage, max_entries=3):
            pass

    def test_uncompressed_size_over_cap(self):
        storage = _FakeStorage(_tar([("mypack/big.bin", b"x" * 4096)]))
        with pytest.raises(AcesPackageError), _stage(storage, max_uncompressed_bytes=1024):
            pass

    def test_rejects_path_traversal_entry(self):
        storage = _FakeStorage(_tar([("mypack/pack.yaml", b"x"), ("../escape", b"evil")]))
        with pytest.raises(AcesPackageError), _stage(storage):
            pass

    def test_rejects_absolute_path_entry(self):
        storage = _FakeStorage(_tar([("mypack/pack.yaml", b"x"), ("/etc/evil", b"evil")]))
        with pytest.raises(AcesPackageError), _stage(storage):
            pass

    def test_rejects_symlink_entry(self):
        link = tarfile.TarInfo("mypack/link")
        link.type = tarfile.SYMTYPE
        link.linkname = "/etc/passwd"
        storage = _FakeStorage(_tar([("mypack/pack.yaml", b"x"), link]))
        with pytest.raises(AcesPackageError), _stage(storage):
            pass

    def test_rejects_hardlink_entry(self):
        link = tarfile.TarInfo("mypack/hard")
        link.type = tarfile.LNKTYPE
        link.linkname = "mypack/pack.yaml"
        storage = _FakeStorage(_tar([("mypack/pack.yaml", b"x"), link]))
        with pytest.raises(AcesPackageError), _stage(storage):
            pass

    def test_rejects_device_entry(self):
        dev = tarfile.TarInfo("mypack/dev")
        dev.type = tarfile.CHRTYPE
        storage = _FakeStorage(_tar([("mypack/pack.yaml", b"x"), dev]))
        with pytest.raises(AcesPackageError), _stage(storage):
            pass

    def test_rejects_multiple_top_level_entries(self):
        storage = _FakeStorage(_tar([("mypack/pack.yaml", b"x"), ("other/f", b"y")]))
        with pytest.raises(AcesPackageError), _stage(storage):
            pass

    def test_rejects_single_top_level_file(self):
        storage = _FakeStorage(_tar([("loose.yaml", b"x")]))
        with pytest.raises(AcesPackageError), _stage(storage):
            pass

    def test_precondition_change_during_retrieval(self):
        storage = _FakeStorage(_good_pack(), download_error=ObjectPreconditionError("changed"))
        with pytest.raises(AcesPackageError), _stage(storage):
            pass

    def test_storage_failure_maps_to_aces_error(self):
        storage = _FakeStorage(_good_pack(), download_error=CloudStorageError("boom"))
        with pytest.raises(AcesPackageError), _stage(storage):
            pass

    def test_non_tar_archive(self):
        storage = _FakeStorage(b"this is not a tar archive at all")
        with pytest.raises(AcesPackageError), _stage(storage):
            pass


class TestRejectUnsafeMember:
    """Pin the custom pre-scan guard directly, independent of stdlib
    ``tarfile`` ``filter="data"``. The end-to-end tests above prove the overall
    fail-closed contract; these prove ``_reject_unsafe_member`` itself is what
    rejects each unsafe member type, so removing it (as a "redundant with the
    stdlib filter" simplification) fails here."""

    def test_allows_regular_file_and_directory(self):
        reg = tarfile.TarInfo("mypack/pack.yaml")
        directory = tarfile.TarInfo("mypack/sub")
        directory.type = tarfile.DIRTYPE
        # No exception for the two permitted member kinds.
        _reject_unsafe_member(reg)
        _reject_unsafe_member(directory)

    def test_rejects_path_traversal(self):
        member = tarfile.TarInfo("mypack/../escape")
        with pytest.raises(AcesPackageError):
            _reject_unsafe_member(member)

    def test_rejects_absolute_path(self):
        member = tarfile.TarInfo("/etc/evil")
        with pytest.raises(AcesPackageError):
            _reject_unsafe_member(member)

    def test_rejects_symlink_even_with_in_bounds_target(self):
        # Stricter than the stdlib filter: a symlink whose target stays inside
        # the destination is still rejected outright by the custom guard.
        link = tarfile.TarInfo("mypack/link")
        link.type = tarfile.SYMTYPE
        link.linkname = "mypack/pack.yaml"
        with pytest.raises(AcesPackageError):
            _reject_unsafe_member(link)

    def test_rejects_hardlink(self):
        link = tarfile.TarInfo("mypack/hard")
        link.type = tarfile.LNKTYPE
        link.linkname = "mypack/pack.yaml"
        with pytest.raises(AcesPackageError):
            _reject_unsafe_member(link)

    def test_rejects_char_device(self):
        dev = tarfile.TarInfo("mypack/dev")
        dev.type = tarfile.CHRTYPE
        with pytest.raises(AcesPackageError):
            _reject_unsafe_member(dev)

    def test_rejects_block_device(self):
        dev = tarfile.TarInfo("mypack/dev")
        dev.type = tarfile.BLKTYPE
        with pytest.raises(AcesPackageError):
            _reject_unsafe_member(dev)

    def test_rejects_fifo(self):
        fifo = tarfile.TarInfo("mypack/pipe")
        fifo.type = tarfile.FIFOTYPE
        with pytest.raises(AcesPackageError):
            _reject_unsafe_member(fifo)
