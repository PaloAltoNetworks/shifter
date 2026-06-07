"""Structural dependency security checks for shifter_platform."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
ASYNCSSH_MIN_VERSION = (2, 23, 0)


def _release_tuple(version: str) -> tuple[int, int, int]:
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)", version)
    assert match is not None, f"Expected numeric version, got {version!r}"
    return tuple(int(part) for part in match.groups())


def test_asyncssh_direct_dependency_declares_patched_floor() -> None:
    pyproject = tomllib.loads((PACKAGE_ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert "asyncssh>=2.23.0" in pyproject["project"]["dependencies"]


def test_asyncssh_lock_uses_patched_release() -> None:
    lock = tomllib.loads((PACKAGE_ROOT / "uv.lock").read_text(encoding="utf-8"))
    locked_versions = {package["name"]: package["version"] for package in lock["package"]}

    assert _release_tuple(locked_versions["asyncssh"]) >= ASYNCSSH_MIN_VERSION
