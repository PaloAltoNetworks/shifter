"""Tests for the pure ACES image resolver (ADR-032-R2).

Exercises the matching rules in isolation (no DB): exact (name, version) match,
unpinned (``*``/blank) -> any-version default row, and -- critically -- that a
PINNED version never silently falls back to the any-version row (authored
specificity is honored; no substitution, matching aces-sdl + the reference).
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

    def test_pinned_version_never_falls_back_to_any_version(self):
        # The author pinned 9.9; only an any-version row exists. Must NOT substitute
        # (an any-version catch-all can't be proven to be 9.9). Regression guard.
        assert resolve_from_candidates([_candidate("", "img-any")], version="9.9") is None

    def test_unpinned_star_uses_any_version_default(self):
        resolved = resolve_from_candidates([_candidate("", "img-any")], version="*")
        assert resolved is not None and resolved.image_ref == "img-any"

    def test_unpinned_star_ignores_versioned_rows_without_default(self):
        # Author unpinned (*), but only a versioned row exists (no blank default).
        # No default to serve -> None (caller fails loud; we do not guess a version).
        assert resolve_from_candidates([_candidate("2.0", "img-v2")], version="*") is None

    def test_exact_preferred_when_both_present(self):
        resolved = resolve_from_candidates([_candidate("", "img-any"), _candidate("2.0", "img-exact")], version="2.0")
        assert resolved is not None and resolved.image_ref == "img-exact"

    def test_no_match_returns_none(self):
        assert resolve_from_candidates([_candidate("1.0", "img")], version="2.0") is None

    def test_empty_candidates_returns_none(self):
        assert resolve_from_candidates([], version="1.0") is None

    def test_version_none_uses_any_version_default(self):
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
