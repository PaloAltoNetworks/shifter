"""Exact image selection and independent EC2 image/type preflight."""

from unittest.mock import Mock

import pytest
from shared.runtime_plugin_binding import RuntimeTargetImageProfile

from raes_ec2_image import Ec2ImageError, resolve_ec2_image, verify_ec2_image
from raes_plan import RaesPlanImage, RaesPlanNode


def node(**extra):
    return RaesPlanNode(
        **{
            "address": "node.host",
            "name": "host",
            "os_family": "linux",
            "count": 1,
            "network_addresses": (),
            "image": RaesPlanImage(name="container-host", version="1"),
            **extra,
        }
    )


def candidate(**extra):
    return {
        "source_version": "1",
        "image_ref": "ami-0123456789abcdef0",
        "machine_type": "m7i.large",
        "management_ssh_port": 2222,
        **extra,
    }


def client():
    ec2 = Mock()
    ec2.describe_images.return_value = {
        "Images": [
            {
                "ImageId": "ami-0123456789abcdef0",
                "State": "available",
                "Architecture": "x86_64",
                "VirtualizationType": "hvm",
                "RootDeviceType": "ebs",
                "RootDeviceName": "/dev/sda1",
                "BlockDeviceMappings": [
                    {"DeviceName": "/dev/sda1", "Ebs": {"VolumeSize": 30, "SnapshotId": "snap-0123456789abcdef0"}}
                ],
            }
        ]
    }
    ec2.describe_instance_types.return_value = {
        "InstanceTypes": [
            {
                "InstanceType": "m7i.large",
                "ProcessorInfo": {"SupportedArchitectures": ["x86_64"]},
                "VCpuInfo": {"DefaultVCpus": 2},
                "MemoryInfo": {"SizeInMiB": 8192},
                "SupportedVirtualizationTypes": ["hvm"],
            }
        ]
    }
    return ec2


def test_pinned_registry_image_keeps_management_transport_and_source_identity():
    profile = resolve_ec2_image(node(), [candidate()])
    assert profile.image_id == "ami-0123456789abcdef0"
    assert profile.management_ssh_port == 2222
    actual = verify_ec2_image(node(ram_mib=4096, vcpus=2), profile, client())
    assert actual.root_device == "/dev/sda1"
    assert actual.disk_size_gb >= 30
    assert actual.image_id == profile.image_id


def test_image_with_ephemeral_mappings_verifies_the_ebs_root():
    # Virtual (instance-store / ephemeral) mappings carry no snapshot/lifecycle and
    # are not extra disks; a base AMI that declares them must still verify its EBS root.
    ec2 = client()
    ec2.describe_images.return_value["Images"][0]["BlockDeviceMappings"] = [
        {"DeviceName": "/dev/sda1", "Ebs": {"VolumeSize": 30, "SnapshotId": "snap-0123456789abcdef0"}},
        {"DeviceName": "/dev/sdb", "VirtualName": "ephemeral0"},
        {"DeviceName": "/dev/sdc", "VirtualName": "ephemeral1"},
    ]
    actual = verify_ec2_image(node(ram_mib=4096, vcpus=2), resolve_ec2_image(node(), [candidate()]), ec2)
    assert actual.root_device == "/dev/sda1"
    assert actual.disk_size_gb >= 30


def test_image_with_extra_ebs_disk_is_refused():
    # A second EBS disk still fails closed until its lifecycle and evidence are represented.
    ec2 = client()
    ec2.describe_images.return_value["Images"][0]["BlockDeviceMappings"] = [
        {"DeviceName": "/dev/sda1", "Ebs": {"VolumeSize": 30, "SnapshotId": "snap-0123456789abcdef0"}},
        {"DeviceName": "/dev/sdb", "Ebs": {"VolumeSize": 100, "SnapshotId": "snap-0fedcba9876543210"}},
    ]
    with pytest.raises(Ec2ImageError, match="root disk"):
        verify_ec2_image(node(ram_mib=4096, vcpus=2), resolve_ec2_image(node(), [candidate()]), ec2)


def test_adapter_target_profile_selects_an_exact_ami():
    runtime = RuntimeTargetImageProfile(
        provider="aws",
        image_ref="ami-0123456789abcdef0",
        machine_type="m7i.large",
        management_ssh_username="host-admin",
    )
    profile = resolve_ec2_image(node(), [], runtime_profile=runtime)
    assert profile.image_id == runtime.image_ref
    assert profile.management_ssh_username == "host-admin"


@pytest.mark.parametrize(
    "image_ref", ["ami-latest", "ami-0123456789abcdef0 trailing", "ssm:/latest", "projects/x/global/images/host"]
)
def test_registry_cannot_substitute_mutable_or_other_provider_image(image_ref):
    with pytest.raises(Ec2ImageError):
        resolve_ec2_image(node(), [candidate(image_ref=image_ref)])


def test_missing_pin_never_falls_back_to_any_version():
    with pytest.raises(Ec2ImageError):
        resolve_ec2_image(node(), [candidate(source_version="")])


@pytest.mark.parametrize(
    "alter",
    [
        lambda ec2: ec2.describe_images.return_value["Images"][0].update(State="pending"),
        lambda ec2: ec2.describe_images.return_value["Images"][0].update(ImageId="ami-fffffffffffffffff"),
        lambda ec2: ec2.describe_images.return_value["Images"][0].update(Platform="windows"),
        lambda ec2: ec2.describe_images.return_value["Images"][0].update(Architecture="arm64"),
        lambda ec2: ec2.describe_instance_types.return_value["InstanceTypes"][0]["MemoryInfo"].update(SizeInMiB=1024),
        lambda ec2: ec2.describe_instance_types.return_value["InstanceTypes"][0]["VCpuInfo"].update(DefaultVCpus=1),
    ],
)
def test_provider_observation_must_satisfy_requested_image_and_resources(alter):
    ec2 = client()
    alter(ec2)
    with pytest.raises(Ec2ImageError):
        verify_ec2_image(node(ram_mib=4096, vcpus=2), resolve_ec2_image(node(), [candidate()]), ec2)
    assert not ec2.run_instances.called


def test_explicit_disk_cannot_shrink_the_source_snapshot():
    with pytest.raises(Ec2ImageError):
        verify_ec2_image(node(), resolve_ec2_image(node(), [candidate(disk_size_gb=20)]), client())


PRECONFIGURED = {
    "bootstrap_capability": "preconfigured-machine-host",
    "participant_container_name": "workstation",
    "participant_username": "participant",
    "participant_readiness_contract": "participant-readiness/v1",
    "participant_readiness_manifest_sha256": "a" * 64,
}


def test_preconfigured_host_contract_reaches_the_verified_image():
    """#2527: the participant readiness contract survives resolution and preflight."""
    runtime = RuntimeTargetImageProfile(
        provider="aws",
        image_ref="ami-0123456789abcdef0",
        machine_type="m7i.large",
        management_ssh_username="hostadmin",
        management_ssh_port=2222,
        **PRECONFIGURED,
    )
    verified = verify_ec2_image(node(), resolve_ec2_image(node(), [], runtime_profile=runtime), client())
    assert verified.management_ssh_port == 2222
    assert verified.contract.bootstrap_capability == "preconfigured-machine-host"
    assert verified.contract.participant_container_name == "workstation"
    assert verified.contract.participant_readiness_manifest_sha256 == "a" * 64


def test_prepromoted_directory_contract_requires_both_domain_names():
    """#2528: a prepromoted image carries its baked domain identity."""
    runtime = RuntimeTargetImageProfile(
        provider="aws",
        image_ref="ami-0123456789abcdef0",
        bootstrap_capability="prepromoted-domain-controller",
        domain_dns_name="corp.example",
        domain_netbios_name="CORP",
    )
    profile = resolve_ec2_image(node(), [], runtime_profile=runtime)
    assert (profile.contract.domain_dns_name, profile.contract.domain_netbios_name) == ("corp.example", "CORP")


@pytest.mark.parametrize(
    "fields",
    [
        {**PRECONFIGURED, "participant_readiness_manifest_sha256": ""},
        {**PRECONFIGURED, "participant_readiness_contract": "participant-readiness/v2"},
        {"bootstrap_capability": "prepromoted-domain-controller"},
        {"participant_container_name": "workstation"},
        {"bootstrap_capability": "nested-hypervisor"},
    ],
)
def test_incomplete_or_mixed_host_contracts_are_refused(fields):
    resolved = {"management_ssh_username": "hostadmin", **fields}
    with pytest.raises(Ec2ImageError):
        resolve_ec2_image(node(), [candidate(**resolved)])


def test_runtime_profile_cannot_mix_participant_and_domain_contracts():
    runtime = RuntimeTargetImageProfile.model_construct(
        provider="aws",
        image_kind="image",
        image_ref="ami-0123456789abcdef0",
        machine_type="",
        disk_size_gb=None,
        disk_type="",
        management_ssh_username="hostadmin",
        management_ssh_port=2222,
        domain_dns_name="corp.example",
        domain_netbios_name="CORP",
        **PRECONFIGURED,
    )
    with pytest.raises(Ec2ImageError):
        resolve_ec2_image(node(), [], runtime_profile=runtime)


def test_prepromoted_image_must_match_the_authored_windows_domain():
    """#2528: a baked domain that contradicts the node fails before any mutation."""
    from raes_ec2_image import Ec2HostContract, VerifiedEc2Image, assert_image_contract_matches_node

    image = VerifiedEc2Image(
        "ami-0123456789abcdef0",
        "m7i.large",
        "/dev/sda1",
        "snap-0123456789abcdef0",
        100,
        "gp3",
        "x86_64",
        22,
        contract=Ec2HostContract(
            "prepromoted-domain-controller", domain_dns_name="corp.example", domain_netbios_name="CORP"
        ),
    )
    controller = node(os_family="windows", domain_dns_name="corp.example", domain_netbios_name="CORP")
    assert_image_contract_matches_node(controller, image)
    assert_image_contract_matches_node(
        node(os_family="windows", domain_dns_name="Corp.Example.", domain_netbios_name="corp"), image
    )
    # A node that authors no domain leaves the directory to the image, as on GCE.
    assert_image_contract_matches_node(node(os_family="windows"), image)
    for mismatched in (
        node(os_family="windows", domain_dns_name="other.example", domain_netbios_name="CORP"),
        node(os_family="windows", domain_dns_name="corp.example", domain_netbios_name="OTHER"),
        node(os_family="windows", domain_dns_name="corp.example"),
        node(domain_dns_name="corp.example", domain_netbios_name="CORP"),
        node(),
    ):
        with pytest.raises(Ec2ImageError):
            assert_image_contract_matches_node(mismatched, image)
