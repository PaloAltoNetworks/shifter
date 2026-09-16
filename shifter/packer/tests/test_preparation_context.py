"""Exercise installed build-material containment and full-content integrity."""

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


def load_module():
    spec = importlib.util.spec_from_file_location(
        "preparation_context", Path(__file__).parents[1] / "preparation" / "context.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def context(tmp_path):
    root = tmp_path / "contexts"
    directory = root / "example"
    directory.mkdir(parents=True)
    (directory / "build.sh").write_bytes(b"#!/bin/sh\ntrue\n")
    (directory / "verify.sh").write_bytes(b"#!/bin/sh\ntest -f /image/example\n")
    (directory / "verify_boot.py").write_bytes(b"def probe_http(host, nonce):\n    return False\n")
    rows = [
        {"path": name, "sha256": hashlib.sha256((directory / name).read_bytes()).hexdigest()}
        for name in ("build.sh", "verify.sh", "verify_boot.py")
    ]
    digest = "sha256:" + hashlib.sha256(json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return root, directory, digest


def test_verified_context_returns_the_verified_bytes(context):
    module = load_module()
    root, _, digest = context
    files = module.load_context(root, "example", digest)
    assert files["build.sh"] == b"#!/bin/sh\ntrue\n"


@pytest.mark.parametrize("filename", ["build.sh", "verify.sh", "verify_boot.py", "additional-input"])
def test_edit_or_extra_file_invalidates_specification(context, filename):
    module = load_module()
    root, directory, digest = context
    (directory / filename).write_bytes(b"modified")
    with pytest.raises(module.ContextError):
        module.load_context(root, "example", digest)


@pytest.mark.parametrize("filename", ["build.sh", "verify.sh", "verify_boot.py"])
def test_digest_valid_context_must_contain_every_required_entrypoint(context, filename):
    module = load_module()
    root, directory, _ = context
    (directory / filename).unlink()
    files = {path.name: path.read_bytes() for path in directory.iterdir()}
    with pytest.raises(module.ContextError, match="lacks"):
        module.load_context(root, "example", module.context_digest(files))


@pytest.mark.parametrize("specification_id", ["../example", "/example", "example/../example", ".", ".."])
def test_specification_cannot_escape_installed_contexts(context, specification_id):
    module = load_module()
    root, _, digest = context
    with pytest.raises(module.ContextError):
        module.load_context(root, specification_id, digest)


def test_rejects_links_even_when_the_target_is_inside_context(context):
    module = load_module()
    root, directory, digest = context
    (directory / "copy").symlink_to(directory / "build.sh")
    with pytest.raises(module.ContextError):
        module.load_context(root, "example", digest)


def test_read_is_bounded_before_hashing(context):
    module = load_module()
    root, directory, digest = context
    with (directory / "large").open("wb") as stream:
        stream.truncate(module.MAX_CONTEXT_BYTES + 1)
    with pytest.raises(module.ContextError):
        module.load_context(root, "example", digest)
