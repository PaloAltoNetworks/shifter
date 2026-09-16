"""One canonical RAES image-matching policy shared by both deployables (#1581).

The exact-version / any-version resolution rules used to live only in the
provisioner (``raes_image_resolver``). Editor realizability assessment (#1581)
needs the same rules in the portal to report a missing image-supply gap, so the
policy moved to :mod:`shared.raes.image_policy` -- the dependency-light shared
module both the portal and the separately deployed provisioner execute.

These tests pin the policy itself. ``tests/shared/raes/test_image_policy_parity``
below pins the property that matters architecturally: there is exactly one
implementation, and the provisioner consumes it rather than carrying a copy.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from shared.raes.image_policy import ResolvedImage, is_concrete_image_ref, resolve_from_candidates

_REPO_ROOT = Path(__file__).resolve().parents[4]
_PROVISIONER = _REPO_ROOT / "engine" / "provisioner"


def _candidate(source_version: str, image_ref: str, **extra: Any) -> dict[str, Any]:
    """Build a registry candidate row for the resolver."""
    return {"source_version": source_version, "image_ref": image_ref, **extra}


class TestPinnedVersionResolution:
    """A pinned authored version matches exactly and never substitutes."""

    def test_pinned_version_matches_exact_row(self) -> None:
        resolved = resolve_from_candidates([_candidate("1.0", "img-v1"), _candidate("", "img-any")], version="1.0")
        assert isinstance(resolved, ResolvedImage)
        assert resolved.image_ref == "img-v1"

    def test_pinned_version_never_falls_back_to_any_version_row(self) -> None:
        # Substituting a catch-all for a pinned artifact would silently violate
        # authored intent, so an unmatched pin resolves to nothing.
        assert resolve_from_candidates([_candidate("", "img-any")], version="9.9") is None

    def test_pinned_version_prefers_exact_over_any_regardless_of_order(self) -> None:
        resolved = resolve_from_candidates([_candidate("", "img-any"), _candidate("2.0", "img-exact")], version="2.0")
        assert resolved is not None
        assert resolved.image_ref == "img-exact"


class TestUnpinnedVersionResolution:
    """An unpinned authored version uses the any-version default row."""

    @pytest.mark.parametrize("version", ["*", "", None])
    def test_unpinned_sentinels_use_any_version_row(self, version: str | None) -> None:
        resolved = resolve_from_candidates([_candidate("", "img-any")], version=version)
        assert resolved is not None
        assert resolved.image_ref == "img-any"

    def test_unpinned_does_not_borrow_a_pinned_row(self) -> None:
        assert resolve_from_candidates([_candidate("2.0", "img-v2")], version="*") is None


class TestNoMatch:
    """No match leaves passthrough / fail-loud to the caller."""

    def test_empty_candidates_resolve_to_none(self) -> None:
        assert resolve_from_candidates([], version="1.0") is None

    def test_unrelated_version_resolves_to_none(self) -> None:
        assert resolve_from_candidates([_candidate("1.0", "img")], version="2.0") is None


class TestSizingProjection:
    """Blank sizing fields project to None rather than empty strings."""

    def test_blank_sizing_fields_become_none(self) -> None:
        resolved = resolve_from_candidates(
            [_candidate("", "img-any", machine_type="", disk_type="", disk_size_gb=None)], version="*"
        )
        assert resolved is not None
        assert resolved.machine_type is None
        assert resolved.disk_type is None
        assert resolved.disk_size_gb is None

    def test_populated_sizing_fields_are_carried(self) -> None:
        resolved = resolve_from_candidates(
            [_candidate("", "img-any", machine_type="n2-standard-4", disk_type="pd-ssd", disk_size_gb=100)],
            version="*",
        )
        assert resolved is not None
        assert resolved.machine_type == "n2-standard-4"
        assert resolved.disk_type == "pd-ssd"
        assert resolved.disk_size_gb == 100


class TestConcreteReferencePassthrough:
    """Concrete-reference policy is shared and provider-parameterized.

    Realization passes an already-concrete image ref straight through when no
    registry mapping matches. Editor assessment must apply the same rule or it
    would report a false "missing image mapping" gap for a pack that launches.
    """

    @pytest.mark.parametrize(
        "name",
        [
            "projects/my-proj/global/images/img-1",
            "projects/debian-cloud/global/images/family/debian-12",
            "https://www.googleapis.com/compute/v1/projects/p/global/images/i",
        ],
    )
    def test_concrete_gce_refs_are_recognized(self, name: str) -> None:
        assert is_concrete_image_ref(name, provider="gce") is True

    @pytest.mark.parametrize("name", ["alpine", "ubuntu-22-04", "", "my-image"])
    def test_bare_source_names_are_not_concrete(self, name: str) -> None:
        assert is_concrete_image_ref(name, provider="gce") is False

    def test_unknown_provider_never_claims_concrete(self) -> None:
        # Fail closed: an unmodelled provider must not silently pass refs through
        # and must not imply an adapter exists for it.
        assert is_concrete_image_ref("projects/p/global/images/i", provider="aws") is False


class TestSingleCanonicalImplementation:
    """The provisioner consumes the shared policy instead of carrying a copy."""

    def test_provisioner_no_longer_ships_a_local_resolver_module(self) -> None:
        # A second copy is the failure mode #1581 must not introduce: the portal
        # and the provisioner must resolve images identically by construction.
        assert not (_PROVISIONER / "raes_image_resolver.py").exists()

    def test_provisioner_image_builder_imports_the_shared_policy(self) -> None:
        source = (_PROVISIONER / "raes_gce_image.py").read_text(encoding="utf-8")
        assert "from shared.raes.image_policy import" in source

    def test_shared_policy_stays_dependency_light(self) -> None:
        # The provisioner image copies `shared/` onto PYTHONPATH without the
        # portal's dependencies, so this module must import stdlib only.
        import shared.raes.image_policy as policy

        source = Path(policy.__file__).read_text(encoding="utf-8")
        for line in source.splitlines():
            if line.startswith(("import ", "from ")) and "__future__" not in line:
                assert not line.split()[1].startswith(("django", "cms", "engine", "raes_")), line
