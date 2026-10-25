"""Native guests have pinned identity, private transport, and no provider role."""

import hashlib
import json
from dataclasses import asdict, replace
from unittest.mock import Mock
from uuid import UUID

import pytest

from ec2_guest_instance import Ec2GuestError, Ec2GuestPlan, ensure_ec2_guest, guest_request, observe_ec2_guest
from raes_ec2_image import Ec2HostContract, VerifiedEc2Image
from utils.crypto import generate_ssh_host_keypair, generate_ssh_keypair


def plan():
    return Ec2GuestPlan(
        environment="test",
        request_id=UUID(int=1),
        generation=UUID(int=2),
        range_id=7,
        instance_key="node.host#0",
        name="host",
        os_family="linux",
        subnet_id="subnet-" + "0" * 17,
        private_ip="10.9.0.10",
        security_group_id="sg-0123456789abcdef0",
        image=VerifiedEc2Image(
            "ami-0123456789abcdef0", "m7i.large", "/dev/sda1", "snap-0123456789abcdef0", 30, "gp3", "x86_64", 2222
        ),
    )


def observed(p):
    return {
        "InstanceId": "i-0123456789abcdef0",
        "ImageId": p.image.image_id,
        "InstanceType": p.image.instance_type,
        "SubnetId": p.subnet_id,
        "PrivateIpAddress": p.private_ip,
        "State": {"Name": "running"},
        "NetworkInterfaces": [
            {
                "SubnetId": p.subnet_id,
                "PrivateIpAddress": p.private_ip,
                "Groups": [{"GroupId": p.security_group_id}],
                "Attachment": {"DeviceIndex": 0, "DeleteOnTermination": True},
                "PrivateIpAddresses": [{"PrivateIpAddress": p.private_ip, "Primary": True}],
                "Ipv6Addresses": [],
            }
        ],
        "Architecture": p.image.architecture,
        "Tags": p.tags(),
        "SecurityGroups": [{"GroupId": p.security_group_id}],
        "MetadataOptions": {"HttpTokens": "required", "HttpPutResponseHopLimit": 1},
        "RootDeviceName": p.image.root_device,
        "BlockDeviceMappings": [
            {
                "DeviceName": p.image.root_device,
                "Ebs": {"VolumeId": "vol-0123456789abcdef0", "DeleteOnTermination": True},
            }
        ],
    }


def test_creation_request_has_no_cloud_role_or_public_interface_and_pins_host_identity():
    p = plan()
    private, _ = generate_ssh_host_keypair()
    _, public = generate_ssh_keypair()
    request = guest_request(p, host_private_key=private, management_public_key=public)
    assert "IamInstanceProfile" not in request
    assert request["MinCount"] == request["MaxCount"] == 1
    assert request["NetworkInterfaces"][0]["AssociatePublicIpAddress"] is False
    assert request["NetworkInterfaces"][0]["PrivateIpAddress"] == p.private_ip
    assert request["MetadataOptions"]["HttpTokens"] == "required"
    assert request["MetadataOptions"]["HttpPutResponseHopLimit"] == 1
    assert request["BlockDeviceMappings"][0]["Ebs"]["Encrypted"] is True
    assert len(request["UserData"].encode()) <= 16384
    assert "2222" in request["UserData"]
    assert (
        request["ClientToken"]
        != guest_request(replace(p, generation=UUID(int=3)), host_private_key=private, management_public_key=public)[
            "ClientToken"
        ]
    )


def test_windows_user_data_preserves_profiles_and_uses_the_image_management_port():
    private, _ = generate_ssh_host_keypair()
    _, public = generate_ssh_keypair()
    request = guest_request(
        replace(plan(), os_family="windows"), host_private_key=private, management_public_key=public
    )
    script = request["UserData"]
    assert "Set-NetFirewallProfile" not in script
    assert "-LocalPort 2222" in script
    assert "-Direction Inbound -Action Allow -Protocol TCP" in script
    assert "administrators_authorized_keys" in script
    assert "<persist>true</persist>" in script


@pytest.mark.parametrize(
    "patch",
    [
        {"PublicIpAddress": "203.0.113.7"},
        {"NetworkInterfaces": []},
        {"NetworkInterfaces": [{"Ipv6Addresses": [{"Ipv6Address": "2001:db8::7"}]}]},
        {"IamInstanceProfile": {"Arn": "unexpected"}},
        {"ImageId": "ami-fffffffffffffffff"},
        {"SubnetId": "subnet-" + "f" * 17},
        {"PrivateIpAddress": "10.9.1.10"},
        {"Tags": []},
        {"SecurityGroups": [{"GroupId": "sg-fffffffffffffffff"}]},
        {"MetadataOptions": {"HttpTokens": "optional", "HttpPutResponseHopLimit": 2}},
    ],
)
def test_reconciliation_rejects_drift_before_publishing_guest_access(patch):
    p = plan()
    ec2 = Mock()
    ec2.describe_instances.return_value = {"Reservations": [{"Instances": [{**observed(p), **patch}]}]}
    with pytest.raises(Ec2GuestError):
        observe_ec2_guest(p, ec2, "i-0123456789abcdef0")
    ec2.run_instances.assert_not_called()


def reuse_mocks(p, initial_state="running"):
    ec2 = Mock()
    row = observed(p)
    row["State"]["Name"] = initial_state
    ec2.describe_instances.return_value = {"Reservations": [{"Instances": [row]}]}
    ec2.get_waiter.return_value.wait.side_effect = lambda **kwargs: row["State"].update(Name="running")
    ec2.describe_volumes.return_value = {
        "Volumes": [
            {
                "VolumeId": "vol-0123456789abcdef0",
                "SnapshotId": p.image.root_snapshot,
                "Encrypted": True,
                "Size": 30,
                "VolumeType": "gp3",
                "Attachments": [
                    {
                        "InstanceId": "i-0123456789abcdef0",
                        "Device": p.image.root_device,
                        "State": "attached",
                        "VolumeId": "vol-0123456789abcdef0",
                        "DeleteOnTermination": True,
                        "AttachTime": "2026-09-17T00:00:00Z",
                    }
                ],
            }
        ]
    }
    secrets = Mock()
    secrets.host_ssh.return_value = ("host-secret-ref", "ssh-rsa TEST")
    secrets.host_identity.return_value = ("private", "ssh-ed25519 TEST")
    return ec2, secrets


@pytest.mark.parametrize("initial_state", ["running", "pending"])
def test_exact_existing_guest_is_reused_without_mutation(initial_state):
    p = plan()
    ec2, secrets = reuse_mocks(p, initial_state)
    result = ensure_ec2_guest(p, ec2, secrets)
    secrets.host_ssh.assert_called_once_with(p.range_id, p.instance_key, create=False)
    secrets.host_identity.assert_called_once_with(p.range_id, p.instance_key, create=False)
    assert result["asset_type"] == "ec2_vm"
    assert result["host_ssh_port"] == 2222
    assert result["host_public_key"] == "ssh-ed25519 TEST"
    assert result["host_ssh_key_secret_ref"] == "host-secret-ref"
    ec2.run_instances.assert_not_called()


@pytest.mark.parametrize("change", ["secondary_address", "ipv6", "extra_nic", "wrong_group", "retained_nic"])
def test_guest_interface_readback_rejects_unadmitted_address_or_attachment(change):
    p = plan()
    row = observed(p)
    interface = row["NetworkInterfaces"][0]
    if change == "secondary_address":
        interface["PrivateIpAddresses"].append({"PrivateIpAddress": "10.9.0.11", "Primary": False})
    elif change == "ipv6":
        interface["Ipv6Addresses"] = [{"Ipv6Address": "2001:db8::7"}]
    elif change == "extra_nic":
        row["NetworkInterfaces"].append(dict(interface))
    elif change == "wrong_group":
        interface["Groups"] = [{"GroupId": "sg-" + "f" * 17}]
    else:
        interface["Attachment"]["DeleteOnTermination"] = False
    ec2 = Mock()
    ec2.describe_instances.return_value = {"Reservations": [{"Instances": [row]}]}
    with pytest.raises(Ec2GuestError):
        observe_ec2_guest(p, ec2, row["InstanceId"])


def test_standard_image_digest_is_unchanged_by_image_contracts():
    """Guests created before image contracts existed keep resuming (#2527)."""
    p = plan()
    legacy = asdict(p.image)
    legacy.pop("contract")
    tag = next(tag["Value"] for tag in p.tags() if tag["Key"] == "shifter:image")
    assert tag == hashlib.sha256(json.dumps(legacy, sort_keys=True).encode()).hexdigest()
    contracted = replace(
        p, image=replace(p.image, contract=Ec2HostContract("preconfigured-machine-host", "ws", "u", "c", "d"))
    )
    assert next(tag["Value"] for tag in contracted.tags() if tag["Key"] == "shifter:image") != tag


def test_preconfigured_host_outputs_carry_the_neutral_readiness_contract():
    """#2527: readiness and access consumers read provider-neutral contract keys."""
    contract = Ec2HostContract(
        "preconfigured-machine-host", "workstation", "participant", "participant-readiness/v1", "a" * 64
    )
    p = replace(plan(), image=replace(plan().image, management_ssh_username="hostadmin", contract=contract))
    ec2, secrets = reuse_mocks(p)
    result = ensure_ec2_guest(p, ec2, secrets)
    assert result["host_ssh_username"] == "hostadmin"
    assert result["bootstrap_capability"] == "preconfigured-machine-host"
    assert result["participant_container_name"] == "workstation"
    assert result["participant_username"] == "participant"
    assert result["participant_readiness_manifest_sha256"] == "a" * 64
    assert result["participant_sftp_enabled"] is False
    standard = ensure_ec2_guest(plan(), *reuse_mocks(plan()))
    assert "bootstrap_capability" not in standard
