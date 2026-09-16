"""The provisioner resolves RAES images through the shared policy (ADR-032-R2, #1581).

The matching rules moved to ``shared.raes.image_policy`` so the portal's Scenario
Editor realizability assessment and the separately deployed provisioner resolve
images identically -- a second copy could drift and let the editor call a pack
realizable that realization would then reject.

The full rule matrix is owned by the platform suite
(``shifter_platform/tests/shared/raes/test_image_policy.py``), beside the module.
What is pinned *here* is the cross-deployable guarantee that suite cannot give:
the shared policy imports and behaves correctly inside the provisioner's own
import environment, which ships ``shifter_platform/shared`` on ``PYTHONPATH``
without the portal's dependencies.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from shared.raes.image_policy import ResolvedImage, resolve_from_candidates


def _candidate(version: str, image_ref: str, **extra) -> dict:
    return {
        "source_version": version,
        "image_ref": image_ref,
        "machine_type": extra.get("machine_type"),
        "disk_size_gb": extra.get("disk_size_gb"),
        "disk_type": extra.get("disk_type"),
    }


class TestSharedPolicyInProvisionerEnvironment:
    def test_exact_version_match(self):
        resolved = resolve_from_candidates([_candidate("1.0", "img-v1"), _candidate("", "img-any")], version="1.0")
        assert isinstance(resolved, ResolvedImage)
        assert resolved.image_ref == "img-v1"

    def test_pinned_version_never_falls_back_to_any_version(self):
        # The author pinned 9.9; only an any-version row exists. Must NOT substitute
        # (an any-version catch-all can't be proven to be 9.9). Regression guard.
        assert resolve_from_candidates([_candidate("", "img-any")], version="9.9") is None

    def test_unpinned_star_uses_any_version_default(self):
        resolved = resolve_from_candidates([_candidate("", "img-any")], version="*")
        assert resolved is not None
        assert resolved.image_ref == "img-any"

    def test_no_match_returns_none(self):
        assert resolve_from_candidates([_candidate("1.0", "img")], version="2.0") is None

    def test_carries_machine_and_disk_defaults(self):
        resolved = resolve_from_candidates(
            [_candidate("1.0", "img", machine_type="e2-medium", disk_size_gb=40, disk_type="pd-ssd")],
            version="1.0",
        )
        assert resolved is not None
        assert resolved.machine_type == "e2-medium"
        assert resolved.disk_size_gb == 40
        assert resolved.disk_type == "pd-ssd"
