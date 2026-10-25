"""Platform recipes acquire one integrity-verified file from a pinned npm registry."""

from __future__ import annotations

import base64
import hashlib
import io
import tarfile
from pathlib import Path

import httpx
import pytest

from shared.feature_artifacts.npm import NpmAcquisitionError, fetch_file
from shared.feature_artifacts.recipes import OPEN_VERSION, RecipeError, recipe_for

PACKAGE = "@anthropic-ai/claude-code-linux-x64"
VERSION = "2.1.289"
TARBALL_URL = "https://registry.npmjs.org/@anthropic-ai/claude-code-linux-x64/-/claude-code-linux-x64-2.1.289.tgz"
BINARY = b"\x7fELF" + b"\x00" * 4096


def _tarball(member: str = "package/claude", data: bytes = BINARY, *, symlink: bool = False) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        info = tarfile.TarInfo(member)
        if symlink:
            info.type, info.linkname = tarfile.SYMTYPE, "/etc/passwd"
            archive.addfile(info)
        else:
            info.size, info.mode = len(data), 0o755
            archive.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def _integrity(blob: bytes) -> str:
    return "sha512-" + base64.b64encode(hashlib.sha512(blob).digest()).decode("ascii")


@pytest.fixture
def registry():
    """A fake npm registry at the network boundary; tests tweak ``state``."""
    blob = _tarball()
    state = {"blob": blob, "integrity": _integrity(blob), "tarball": TARBALL_URL, "manifest_status": 200}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith(".tgz"):
            return httpx.Response(200, content=state["blob"])
        if state["manifest_status"] != 200:
            return httpx.Response(state["manifest_status"])
        return httpx.Response(200, json={"dist": {"tarball": state["tarball"], "integrity": state["integrity"]}})

    state["client"] = httpx.Client(transport=httpx.MockTransport(handler))
    yield state
    state["client"].close()


def test_fetch_verifies_integrity_and_extracts_only_the_recipe_member(registry, tmp_path: Path):
    fetched = fetch_file(PACKAGE, VERSION, "package/claude", tmp_path, client=registry["client"])

    assert fetched.path.read_bytes() == BINARY
    assert fetched.sha256 == hashlib.sha256(BINARY).hexdigest()
    assert fetched.byte_count == len(BINARY)
    assert fetched.upstream_ref == f"npm:{PACKAGE}@{VERSION}"
    assert fetched.upstream_integrity == registry["integrity"]
    assert sorted(path.name for path in tmp_path.iterdir()) == ["artifact"]


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"integrity": _integrity(b"other")}, "integrity mismatch"),
        ({"integrity": "sha1-abc"}, "lacks a sha512"),
        ({"tarball": "https://evil.example/pkg.tgz"}, "pinned registry"),
        ({"tarball": TARBALL_URL.replace("https", "http", 1)}, "pinned registry"),
        ({"manifest_status": 404}, "not found"),
        ({"manifest_status": 503}, "HTTP 503"),
    ],
    ids=["integrity-mismatch", "weak-integrity", "foreign-host", "plain-http", "missing-version", "registry-error"],
)
def test_fetch_fails_closed_on_untrusted_or_missing_upstream(registry, tmp_path: Path, change, message):
    registry.update(change)
    with pytest.raises(NpmAcquisitionError, match=message):
        fetch_file(PACKAGE, VERSION, "package/claude", tmp_path, client=registry["client"])
    assert not (tmp_path / "artifact").exists()


@pytest.mark.parametrize(
    ("blob", "message"),
    [
        (_tarball(member="package/other"), "does not contain"),
        (_tarball(symlink=True), "not a regular file"),
    ],
    ids=["missing-member", "symlink-member"],
)
def test_fetch_rejects_packages_without_a_regular_recipe_member(registry, tmp_path: Path, blob, message):
    registry.update({"blob": blob, "integrity": _integrity(blob)})
    with pytest.raises(NpmAcquisitionError, match=message):
        fetch_file(PACKAGE, VERSION, "package/claude", tmp_path, client=registry["client"])


def test_recipes_apply_raes_version_semantics_and_fail_closed():
    recipe = recipe_for("claude-code")

    assert recipe.resolve_version(OPEN_VERSION) == recipe.default_version
    assert recipe.resolve_version("2.0.1") == "2.0.1"
    assert recipe.package_for("linux-x64-glibc") == PACKAGE
    assert recipe.recipe_id == "npm-binary/claude-code/v1"
    for bad in ("latest", "^2.1.0", "2.1", ""):
        with pytest.raises(RecipeError, match="not an exact version"):
            recipe.resolve_version(bad)
    with pytest.raises(RecipeError, match="not available for platform"):
        recipe.package_for("windows-x64")
    with pytest.raises(RecipeError, match="no platform acquisition recipe"):
        recipe_for("arbitrary-url-fetch")
