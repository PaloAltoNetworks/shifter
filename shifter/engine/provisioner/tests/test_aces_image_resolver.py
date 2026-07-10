"""Tests for the pure ACES image resolver (ADR-032-R2).

Exercises the matching rules in isolation (no DB): exact (name, version) match,
then any-version fallback, exact preferred over fallback, and no-match -> None.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from aces_image_resolver import ResolvedImage, resolve_from_candidates


def _candidate(version: str, image_ref: str, **extra) -> dict:
    return {
        "source_version": version,
        "image_ref": image_ref,
        "machine_type": extra.get("machine_type"),
        "disk_size_gb": extra.get("disk_size_gb"),
        "disk_type": extra.get("disk_type"),
    }


class TestResolveFromCandidates:
    def test_exact_version_match(self):
        resolved = resolve_from_candidates([_candidate("1.0", "img-v1"), _candidate("", "img-any")], version="1.0")
        assert isinstance(resolved, ResolvedImage) and resolved.image_ref == "img-v1"

    def test_any_version_fallback(self):
        resolved = resolve_from_candidates([_candidate("", "img-any")], version="9.9")
        assert resolved is not None and resolved.image_ref == "img-any"

    def test_exact_preferred_over_fallback(self):
        resolved = resolve_from_candidates([_candidate("", "img-any"), _candidate("2.0", "img-exact")], version="2.0")
        assert resolved is not None and resolved.image_ref == "img-exact"

    def test_no_match_returns_none(self):
        assert resolve_from_candidates([_candidate("1.0", "img")], version="2.0") is None

    def test_empty_candidates_returns_none(self):
        assert resolve_from_candidates([], version="1.0") is None

    def test_version_none_matches_fallback(self):
        resolved = resolve_from_candidates([_candidate("", "img-any")], version=None)
        assert resolved is not None and resolved.image_ref == "img-any"

    def test_carries_machine_and_disk_defaults(self):
        resolved = resolve_from_candidates(
            [_candidate("1.0", "img", machine_type="e2-medium", disk_size_gb=40, disk_type="pd-ssd")],
            version="1.0",
        )
        assert resolved is not None
        assert resolved.machine_type == "e2-medium"
        assert resolved.disk_size_gb == 40
        assert resolved.disk_type == "pd-ssd"

    def test_blank_machine_and_disk_normalize_to_none(self):
        resolved = resolve_from_candidates([_candidate("1.0", "img", machine_type="", disk_type="")], version="1.0")
        assert resolved is not None
        assert resolved.machine_type is None and resolved.disk_type is None
