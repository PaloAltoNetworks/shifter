"""Tests for the bake-time baked-flag verifier.

Run with the repo test venv:
    python -m pytest scenario-dev/polaris/build/test_verify_flags_baked.py
"""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_SPEC = importlib.util.spec_from_file_location(
    "verify_flags_baked", _HERE / "verify_flags_baked.py"
)
vfb = importlib.util.module_from_spec(_SPEC)
sys.modules["verify_flags_baked"] = vfb
_SPEC.loader.exec_module(vfb)

_PDF_SPEC = importlib.util.spec_from_file_location(
    "build_pdfs", _HERE / "A0-boreas-website" / "build_pdfs.py"
)
build_pdfs = importlib.util.module_from_spec(_PDF_SPEC)
sys.modules["build_pdfs"] = build_pdfs
_PDF_SPEC.loader.exec_module(build_pdfs)

REPO_CHALLENGES = _HERE / "ctfd-challenges.json"
CANONICAL_FLAG_6 = "FLAG{c6f8d2b3e91a4507}"


def _board(tmp_path, challenges):
    path = tmp_path / "ctfd-challenges.json"
    path.write_text(json.dumps({"challenges": challenges}))
    return path


def test_static_flag_returns_content(tmp_path):
    board = json.loads(
        _board(
            tmp_path,
            [{"id": 6, "flags": [{"type": "static", "content": "FLAG{x}"}]}],
        ).read_text()
    )
    assert vfb.static_flag(board, 6) == "FLAG{x}"


def test_static_flag_non_static_raises():
    board = {"challenges": [{"id": 6, "flags": [{"type": "regex", "content": "k"}]}]}
    with pytest.raises(ValueError):
        vfb.static_flag(board, 6)


def test_verify_passes_when_flag_present(tmp_path):
    board = _board(
        tmp_path, [{"id": 6, "flags": [{"type": "static", "content": "FLAG{abc99}"}]}]
    )
    root = tmp_path / "art"
    (root / "internal").mkdir(parents=True)
    (root / "internal" / "rep.txt").write_text("expenses... PO ref: FLAG{abc99}\n")
    misses = vfb.verify(board, root, {"internal/rep.txt": 6})
    assert misses == []


def test_verify_fails_when_flag_absent(tmp_path):
    board = _board(
        tmp_path, [{"id": 6, "flags": [{"type": "static", "content": "FLAG{abc99}"}]}]
    )
    root = tmp_path / "art"
    (root / "internal").mkdir(parents=True)
    (root / "internal" / "rep.txt").write_text("expenses, no flag here\n")
    misses = vfb.verify(board, root, {"internal/rep.txt": 6})
    assert len(misses) == 1


def test_verify_fails_when_artifact_missing(tmp_path):
    board = _board(
        tmp_path, [{"id": 6, "flags": [{"type": "static", "content": "FLAG{abc99}"}]}]
    )
    root = tmp_path / "art"
    root.mkdir()
    misses = vfb.verify(board, root, {"internal/rep.txt": 6})
    assert len(misses) == 1


def test_verify_real_annual_pdf(tmp_path):
    """End-to-end: a freshly generated annual PDF passes the verifier."""
    root = tmp_path / "out"
    (root / "internal").mkdir(parents=True)
    build_pdfs.make_annual_report(
        str(root / "internal" / "boreas-annual-2025.pdf"), CANONICAL_FLAG_6
    )
    misses = vfb.verify(
        REPO_CHALLENGES, root, {"internal/boreas-annual-2025.pdf": 6}
    )
    assert misses == []


def test_main_returns_zero_on_pass(tmp_path):
    root = tmp_path / "out"
    (root / "internal").mkdir(parents=True)
    build_pdfs.make_annual_report(
        str(root / "internal" / "boreas-annual-2025.pdf"), CANONICAL_FLAG_6
    )
    assert vfb.main([str(REPO_CHALLENGES), str(root)]) == 0


def test_main_returns_one_on_miss(tmp_path):
    root = tmp_path / "out"
    (root / "internal").mkdir(parents=True)
    build_pdfs.make_annual_report(
        str(root / "internal" / "boreas-annual-2025.pdf"), "FLAG{wrongflag}"
    )
    assert vfb.main([str(REPO_CHALLENGES), str(root)]) == 1
