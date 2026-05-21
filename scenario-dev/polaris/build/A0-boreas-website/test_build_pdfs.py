"""Tests for the A0 Boreas PDF generator.

Run with the repo test venv:
    python -m pytest scenario-dev/polaris/build/A0-boreas-website/test_build_pdfs.py

Guards the regression from #619: the annual report's flag-6 payload went
missing from the rendered PDF and a clean-checkout rebake kept reintroducing
the Ottawa bug. These tests pin the flag into the artifact and pin the
challenge-board contract that supplies it.
"""

import importlib.util
import json
import sys
from pathlib import Path

import pytest
from pdfminer.high_level import extract_text

_HERE = Path(__file__).resolve().parent
_SPEC = importlib.util.spec_from_file_location("build_pdfs", _HERE / "build_pdfs.py")
build_pdfs = importlib.util.module_from_spec(_SPEC)
sys.modules["build_pdfs"] = build_pdfs
_SPEC.loader.exec_module(build_pdfs)

REPO_CHALLENGES = _HERE.parent / "ctfd-challenges.json"
CANONICAL_FLAG_6 = "FLAG{c6f8d2b3e91a4507}"


def _write_challenges(tmp_path, challenges):
    path = tmp_path / "ctfd-challenges.json"
    path.write_text(json.dumps({"challenges": challenges}))
    return path


def test_flag_for_returns_static_flag(tmp_path):
    path = _write_challenges(
        tmp_path,
        [{"id": 6, "flags": [{"type": "static", "content": "FLAG{abc12345}"}]}],
    )
    assert build_pdfs.flag_for(6, path) == "FLAG{abc12345}"


def test_flag_for_missing_challenge_raises(tmp_path):
    path = _write_challenges(
        tmp_path,
        [{"id": 5, "flags": [{"type": "static", "content": "FLAG{x}"}]}],
    )
    with pytest.raises(ValueError, match="6"):
        build_pdfs.flag_for(6, path)


def test_flag_for_non_static_raises(tmp_path):
    path = _write_challenges(
        tmp_path,
        [{"id": 6, "flags": [{"type": "regex", "content": "(?i)kursk"}]}],
    )
    with pytest.raises(ValueError, match="static"):
        build_pdfs.flag_for(6, path)


def test_flag_for_duplicate_challenge_raises(tmp_path):
    path = _write_challenges(
        tmp_path,
        [
            {"id": 6, "flags": [{"type": "static", "content": "FLAG{a}"}]},
            {"id": 6, "flags": [{"type": "static", "content": "FLAG{b}"}]},
        ],
    )
    with pytest.raises(ValueError, match="duplicate"):
        build_pdfs.flag_for(6, path)


def test_flag_for_multiple_flags_raises(tmp_path):
    path = _write_challenges(
        tmp_path,
        [
            {
                "id": 6,
                "flags": [
                    {"type": "static", "content": "FLAG{a}"},
                    {"type": "static", "content": "FLAG{b}"},
                ],
            }
        ],
    )
    with pytest.raises(ValueError):
        build_pdfs.flag_for(6, path)


def test_repo_challenges_supplies_canonical_flag_6():
    """The checked-in board contract must carry the canonical flag 6."""
    assert build_pdfs.flag_for(6, REPO_CHALLENGES) == CANONICAL_FLAG_6


def test_annual_report_embeds_flag_6(tmp_path):
    out = tmp_path / "boreas-annual-2025.pdf"
    build_pdfs.make_annual_report(str(out), CANONICAL_FLAG_6)
    text = extract_text(str(out))
    assert "Kursk Heavy Industries" in text
    assert CANONICAL_FLAG_6 in text


def test_main_renders_annual_report_with_flag(tmp_path):
    """End-to-end: main() reads the repo board contract and bakes the flag."""
    build_pdfs.main([str(tmp_path), str(REPO_CHALLENGES)])
    text = extract_text(str(tmp_path / "internal" / "boreas-annual-2025.pdf"))
    assert CANONICAL_FLAG_6 in text
