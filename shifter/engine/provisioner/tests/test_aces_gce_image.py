"""Tests for GCE image/sizing resolution on the ACES-native path (ADR-032-R1/R2).

Exercises the composed backend policy: registry match (exact / any-version),
passthrough of an already-concrete GCE ref, resources -> custom machine type, and
fail-loud when nothing resolves. Registry candidates are passed in (pure).
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from aces_gce_image import AcesGceImageError, resolve_gce_image
from aces_plan import AcesPlanImage, AcesPlanNode


def _node(*, image=None, ram_mib=None, vcpus=None, address="node.a") -> AcesPlanNode:
    return AcesPlanNode(
        address=address,
        name=address.rsplit(".", 1)[-1],
        os_family="linux",
        count=1,
        network_addresses=(),
        ram_mib=ram_mib,
        vcpus=vcpus,
        image=image,
    )


def _candidate(version: str, image_ref: str, **extra) -> dict:
    return {
        "source_version": version,
        "image_ref": image_ref,
        "machine_type": extra.get("machine_type"),
        "disk_size_gb": extra.get("disk_size_gb"),
        "disk_type": extra.get("disk_type"),
    }


class TestRegistryResolution:
    def test_exact_version_uses_registry_image_and_sizing(self):
        node = _node(image=AcesPlanImage(name="kali", version="2024.1"))
        candidates = [
            _candidate(
                "2024.1",
                "projects/x/global/images/kali-1",
                machine_type="e2-standard-4",
                disk_size_gb=50,
                disk_type="pd-ssd",
            )
        ]
        profile = resolve_gce_image(node, candidates)
        assert profile.source_image == "projects/x/global/images/kali-1"
        assert profile.machine_type == "e2-standard-4"
        assert profile.disk_size_gb == 50
        assert profile.disk_type == "pd-ssd"

    def test_unpinned_uses_any_version_default(self):
        # No authored version -> the any-version (blank) registry row is the default.
        node = _node(image=AcesPlanImage(name="kali"))
        profile = resolve_gce_image(node, [_candidate("", "projects/x/global/images/kali-latest")])
        assert profile.source_image == "projects/x/global/images/kali-latest"

    def test_pinned_version_with_only_any_version_row_fails_loud(self):
        # Author pinned 9.9; only an any-version row exists. Must NOT substitute it.
        node = _node(image=AcesPlanImage(name="kali", version="9.9"))
        arg = [_candidate("", "projects/x/global/images/kali-latest")]
        with pytest.raises(AcesGceImageError):
            resolve_gce_image(node, arg)

    def test_registry_without_machine_type_derives_custom_from_resources(self):
        node = _node(image=AcesPlanImage(name="kali"), ram_mib=2048, vcpus=2)
        profile = resolve_gce_image(node, [_candidate("", "img")])
        assert profile.machine_type == "e2-custom-2-2048"

    def test_registry_without_machine_type_or_resources_uses_default(self):
        node = _node(image=AcesPlanImage(name="kali"))
        profile = resolve_gce_image(node, [_candidate("", "img")])
        assert profile.machine_type == "e2-medium"

    def test_registry_disk_defaults_when_omitted(self):
        node = _node(image=AcesPlanImage(name="kali"))
        profile = resolve_gce_image(node, [_candidate("", "img")])
        assert profile.disk_size_gb == 30 and profile.disk_type == "pd-balanced"

    def test_ram_is_aligned_up_to_256_boundary(self):
        node = _node(image=AcesPlanImage(name="kali"), ram_mib=2000, vcpus=2)
        profile = resolve_gce_image(node, [_candidate("", "img")])
        assert profile.machine_type == "e2-custom-2-2048"  # 2000 -> 2048


class TestPassthroughAndFailLoud:
    def test_concrete_gce_ref_passthrough(self):
        node = _node(image=AcesPlanImage(name="projects/x/global/images/custom-1"))
        profile = resolve_gce_image(node, [])
        assert profile.source_image == "projects/x/global/images/custom-1"

    def test_unresolvable_source_fails_loud(self):
        node = _node(image=AcesPlanImage(name="kali", version="2024.1"))
        with pytest.raises(AcesGceImageError):
            resolve_gce_image(node, [])

    def test_source_less_node_uses_base_os_from_registry(self):
        # A node with no source gets a base OS image resolved by os_family.
        node = _node(image=None)  # os_family linux
        profile = resolve_gce_image(node, [_candidate("", "projects/x/global/images/ubuntu-base")])
        assert profile.source_image == "projects/x/global/images/ubuntu-base"

    def test_source_less_node_without_base_os_fails_loud(self):
        node_2 = _node(image=None)
        with pytest.raises(AcesGceImageError, match="base-OS"):
            resolve_gce_image(node_2, [])

    def test_wrong_version_no_fallback_fails_loud(self):
        node = _node(image=AcesPlanImage(name="kali", version="2024.1"))
        arg = [_candidate("2023.1", "img")]
        with pytest.raises(AcesGceImageError):
            resolve_gce_image(node, arg)
