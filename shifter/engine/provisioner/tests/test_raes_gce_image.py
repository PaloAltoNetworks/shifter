"""Tests for GCE image/sizing resolution on the RAES-native path (ADR-032-R1/R2).

Exercises the composed backend policy: registry match (exact / any-version),
passthrough of an already-concrete GCE ref, resources -> custom machine type, and
fail-loud when nothing resolves. Registry candidates are passed in (pure).
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from shared.runtime_plugin_binding import RuntimeTargetImageProfile

from raes_gce_image import RaesGceImageError, resolve_gce_image, resolve_gce_image_from_runtime_profile
from raes_plan import RaesPlanImage, RaesPlanNode


def _node(*, image=None, ram_mib=None, vcpus=None, address="node.a") -> RaesPlanNode:
    return RaesPlanNode(
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
    @pytest.mark.parametrize("image_ref", ["family/nested-host", "projects/example/global/images/family/nested-host"])
    def test_adapter_custom_host_requires_exact_image(self, image_ref):
        with pytest.raises(ValueError, match="exact custom-image"):
            RuntimeTargetImageProfile(
                provider="gcp",
                image_kind="image",
                image_ref=image_ref,
                bootstrap_capability="preconfigured-machine-host",
                management_ssh_username="host-admin",
                participant_container_name="participant-desktop",
                participant_username="student",
                participant_readiness_contract="participant-readiness/v1",
                participant_readiness_manifest_sha256="a" * 64,
            )

    def test_adapter_target_preconfigured_custom_image_is_retained(self):
        runtime = RuntimeTargetImageProfile(
            provider="gcp",
            image_kind="image",
            image_ref="projects/example/global/images/nested-host-v1",
            machine_type="n2-standard-8",
            disk_size_gb=220,
            bootstrap_capability="preconfigured-machine-host",
            management_ssh_username="host-admin",
            participant_container_name="participant-desktop",
            participant_username="student",
            participant_readiness_contract="participant-readiness/v1",
            participant_readiness_manifest_sha256="a" * 64,
        )
        profile = resolve_gce_image_from_runtime_profile(_node(), runtime)
        assert profile.source_image == runtime.image_ref
        assert profile.source_machine_image == ""
        assert profile.bootstrap_capability == "preconfigured-machine-host"

    def test_adapter_target_profile_is_a_first_class_image_source(self):
        runtime = RuntimeTargetImageProfile(
            provider="gcp",
            image_kind="machine-image",
            image_ref="projects/example/global/machineImages/nested-host-v1",
            machine_type="e2-standard-8",
            bootstrap_capability="preconfigured-machine-host",
            management_ssh_username="host-admin",
            participant_container_name="participant-desktop",
            participant_username="student",
            participant_readiness_contract="participant-readiness/v1",
            participant_readiness_manifest_sha256="a" * 64,
            allow_public_web_egress=True,
        )
        profile = resolve_gce_image_from_runtime_profile(_node(), runtime)
        assert profile.source_machine_image == runtime.image_ref
        assert profile.machine_type == "e2-standard-8"
        assert profile.allow_public_web_egress is True

    def test_adapter_target_profile_defaults_to_no_public_web_egress(self):
        runtime = RuntimeTargetImageProfile(
            provider="gcp",
            image_ref="projects/example/global/images/desktop-v1",
        )
        profile = resolve_gce_image_from_runtime_profile(_node(), runtime)
        assert profile.allow_public_web_egress is False

    def test_aws_adapter_profile_cannot_enable_gcp_public_web_egress(self):
        with pytest.raises(ValueError, match="AWS image profiles do not support public web egress"):
            RuntimeTargetImageProfile(
                provider="aws",
                image_ref="ami-0123456789abcdef0",
                allow_public_web_egress=True,
            )

    def test_adapter_profile_requires_a_boolean_public_web_choice(self):
        with pytest.raises(ValueError):
            RuntimeTargetImageProfile(
                provider="gcp",
                image_ref="projects/example/global/images/desktop-v1",
                allow_public_web_egress="true",
            )

    def test_adapter_target_profile_preserves_prepromoted_directory_contract(self):
        runtime = RuntimeTargetImageProfile(
            provider="gcp",
            image_ref="projects/example/global/images/directory-v1",
            bootstrap_capability="prepromoted-domain-controller",
            domain_dns_name="example.test",
            domain_netbios_name="EXAMPLE",
        )
        profile = resolve_gce_image_from_runtime_profile(_node(), runtime)
        assert profile.source_image == runtime.image_ref
        assert profile.bootstrap_capability == "prepromoted-domain-controller"
        assert profile.domain_dns_name == "example.test"
        assert profile.domain_netbios_name == "EXAMPLE"

    def test_machine_host_profile_is_resolved_from_tenant_registry(self):
        node = _node(image=RaesPlanImage(name="nested-host"))
        candidate = _candidate("", "projects/example/global/machineImages/nested-host-v1")
        candidate.update(
            {
                "image_kind": "machine-image",
                "bootstrap_capability": "preconfigured-machine-host",
                "management_ssh_username": "host-admin",
                "participant_container_name": "participant-desktop",
                "participant_username": "student",
                "participant_readiness_contract": "participant-readiness/v1",
                "participant_readiness_manifest_sha256": "a" * 64,
            }
        )
        profile = resolve_gce_image(node, [candidate])
        assert profile.source_image == ""
        assert profile.source_machine_image.endswith("/machineImages/nested-host-v1")
        assert profile.bootstrap_capability == "preconfigured-machine-host"
        assert profile.participant_container_name == "participant-desktop"
        assert profile.host_ssh_username == "host-admin"

    @pytest.mark.parametrize("image", [None, RaesPlanImage(name="container-host")])
    def test_registry_management_port_is_preserved(self, image):
        candidate = _candidate("", "projects/x/global/images/container-host")
        candidate["management_ssh_port"] = 2222
        candidate["management_ssh_username"] = "image-admin"
        profile = resolve_gce_image(_node(image=image), [candidate])
        assert profile.host_ssh_port == 2222
        assert profile.host_ssh_username == "image-admin"

    def test_exact_version_uses_registry_image_and_sizing(self):
        node = _node(image=RaesPlanImage(name="kali", version="2024.1"))
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
        node = _node(image=RaesPlanImage(name="kali"))
        profile = resolve_gce_image(node, [_candidate("", "projects/x/global/images/kali-latest")])
        assert profile.source_image == "projects/x/global/images/kali-latest"

    def test_pinned_version_with_only_any_version_row_fails_loud(self):
        # Author pinned 9.9; only an any-version row exists. Must NOT substitute it.
        node = _node(image=RaesPlanImage(name="kali", version="9.9"))
        arg = [_candidate("", "projects/x/global/images/kali-latest")]
        with pytest.raises(RaesGceImageError):
            resolve_gce_image(node, arg)

    def test_registry_without_machine_type_derives_custom_from_resources(self):
        node = _node(image=RaesPlanImage(name="kali"), ram_mib=2048, vcpus=2)
        profile = resolve_gce_image(node, [_candidate("", "img")])
        assert profile.machine_type == "e2-custom-2-2048"

    def test_registry_without_machine_type_or_resources_uses_default(self):
        node = _node(image=RaesPlanImage(name="kali"))
        profile = resolve_gce_image(node, [_candidate("", "img")])
        assert profile.machine_type == "e2-medium"

    def test_registry_disk_defaults_when_omitted(self):
        node = _node(image=RaesPlanImage(name="kali"))
        profile = resolve_gce_image(node, [_candidate("", "img")])
        assert profile.disk_size_gb == 30
        assert profile.disk_type == "pd-balanced"

    def test_ram_is_aligned_up_to_256_boundary(self):
        node = _node(image=RaesPlanImage(name="kali"), ram_mib=2000, vcpus=2)
        profile = resolve_gce_image(node, [_candidate("", "img")])
        assert profile.machine_type == "e2-custom-2-2048"  # 2000 -> 2048


class TestPassthroughAndFailLoud:
    def test_concrete_gce_ref_passthrough(self):
        node = _node(image=RaesPlanImage(name="projects/x/global/images/custom-1"))
        profile = resolve_gce_image(node, [])
        assert profile.source_image == "projects/x/global/images/custom-1"

    def test_unresolvable_source_fails_loud(self):
        node = _node(image=RaesPlanImage(name="kali", version="2024.1"))
        with pytest.raises(RaesGceImageError):
            resolve_gce_image(node, [])

    def test_source_less_node_uses_base_os_from_registry(self):
        # A node with no source gets a base OS image resolved by os_family.
        node = _node(image=None)  # os_family linux
        profile = resolve_gce_image(node, [_candidate("", "projects/x/global/images/ubuntu-base")])
        assert profile.source_image == "projects/x/global/images/ubuntu-base"

    def test_source_less_node_without_base_os_fails_loud(self):
        node_2 = _node(image=None)
        with pytest.raises(RaesGceImageError, match="base-OS"):
            resolve_gce_image(node_2, [])

    def test_wrong_version_no_fallback_fails_loud(self):
        node = _node(image=RaesPlanImage(name="kali", version="2024.1"))
        arg = [_candidate("2023.1", "img")]
        with pytest.raises(RaesGceImageError):
            resolve_gce_image(node, arg)
