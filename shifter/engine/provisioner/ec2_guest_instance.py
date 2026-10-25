"""Private EC2 guest creation and strict provider-observed reconciliation."""

from __future__ import annotations

import base64
import hashlib
import ipaddress
import json
import re
from dataclasses import asdict, dataclass
from typing import Any
from uuid import UUID

from botocore.client import BaseClient
from shared.model_access.network import RFC1918_IPV4_NETWORKS
from shared.raes.image_policy import validate_management_ssh_username

from config import BOOTSTRAP_PRECONFIGURED_MACHINE_HOST, BOOTSTRAP_PREPROMOTED_DC
from ec2_guest_secrets import Ec2GuestSecrets
from guest_host_keys import linux_host_key_script, windows_host_key_script
from raes_ec2_image import Ec2HostContract, VerifiedEc2Image
from raes_identity import RESERVED_MANAGEMENT_LOGIN


class Ec2GuestError(ValueError):
    """The observed EC2 guest cannot prove the intended ownership or containment."""


@dataclass(frozen=True)
class Ec2GuestPlan:
    """Validated placement supplied by the trusted network realizer."""

    environment: str
    request_id: UUID
    generation: UUID
    range_id: int
    instance_key: str
    name: str
    os_family: str
    subnet_id: str
    private_ip: str
    security_group_id: str
    image: VerifiedEc2Image

    def __post_init__(self) -> None:
        validate_management_ssh_username(self.image.management_ssh_username)
        if (
            not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", self.environment)
            or type(self.range_id) is not int
            or self.range_id <= 0
            or not isinstance(self.request_id, UUID)
            or not isinstance(self.generation, UUID)
            or not 1 <= len(self.instance_key) <= 1024
            or not 1 <= len(self.name) <= 255
        ):
            raise Ec2GuestError("EC2 guest placement is invalid")
        self._validate_placement()

    def _validate_placement(self) -> None:
        """Require one private IPv4 interface in the admitted subnet and group."""
        address = ipaddress.ip_address(self.private_ip)
        private = any(address in network for network in RFC1918_IPV4_NETWORKS)
        if (
            self.os_family not in {"linux", "windows"}
            or not private
            or address.version != 4
            or not re.fullmatch(r"subnet-[0-9a-f]{8}(?:[0-9a-f]{9})?", self.subnet_id)
            or not re.fullmatch(r"sg-[0-9a-f]{8}(?:[0-9a-f]{9})?", self.security_group_id)
        ):
            raise Ec2GuestError("EC2 guest placement is invalid")

    @property
    def username(self) -> str:
        return self.image.management_ssh_username or (
            "Administrator" if self.os_family == "windows" else RESERVED_MANAGEMENT_LOGIN
        )

    @property
    def token(self) -> str:
        return hashlib.sha256(f"{self.request_id}:{self.generation}:{self.instance_key}".encode()).hexdigest()

    def tags(self) -> list[dict[str, str]]:
        """Opaque subject tags avoid copying authored/private identities into inventory."""
        image_digest = hashlib.sha256(json.dumps(_image_identity(self.image), sort_keys=True).encode()).hexdigest()
        values = {
            "ManagedBy": "shifter",
            "shifter:system": "shifter",
            "shifter:environment": self.environment,
            "shifter:request_id": str(self.request_id),
            "shifter:range_id": str(self.range_id),
            "shifter:generation": str(self.generation),
            "shifter:subject": hashlib.sha256(self.instance_key.encode()).hexdigest(),
            "shifter:image": image_digest,
        }
        return [{"Key": key, "Value": value} for key, value in values.items()]


def _image_identity(image: VerifiedEc2Image) -> dict[str, Any]:
    """The image facts a guest is bound to; a standard contract adds nothing.

    Omitting the default contract keeps the digest of guests created before
    image contracts existed, so they still resume.
    """
    identity = asdict(image)
    if image.contract == Ec2HostContract():
        identity.pop("contract")
    return identity


def _contract_output(image: VerifiedEc2Image) -> dict[str, Any]:
    """Provider-neutral image-contract fields for readiness and access consumers."""
    contract = image.contract
    if contract.bootstrap_capability == BOOTSTRAP_PRECONFIGURED_MACHINE_HOST:
        return {
            "bootstrap_capability": contract.bootstrap_capability,
            "participant_container_name": contract.participant_container_name,
            "participant_username": contract.participant_username,
            "participant_readiness_contract": contract.participant_readiness_contract,
            "participant_readiness_manifest_sha256": contract.participant_readiness_manifest_sha256,
            # The participant desktop lives in the container; the host's own
            # management sshd must never be offered the participant password.
            "participant_sftp_enabled": False,
        }
    if contract.bootstrap_capability == BOOTSTRAP_PREPROMOTED_DC:
        return {
            "bootstrap_capability": contract.bootstrap_capability,
            "domain_dns_name": contract.domain_dns_name,
            "domain_netbios_name": contract.domain_netbios_name,
        }
    return {}


def _bootstrap(plan: Ec2GuestPlan, host_private_key: str, management_public_key: str) -> str:
    """Render the pinned management identity bootstrap for the admitted operating system."""
    if not re.fullmatch(r"ssh-rsa [A-Za-z0-9+/=]+", management_public_key):
        raise Ec2GuestError("EC2 management public key is invalid")
    encoded = base64.b64encode(host_private_key.encode()).decode()
    if plan.os_family == "windows":
        body = "<powershell>\n$ErrorActionPreference = 'Stop'\n" + windows_host_key_script(
            encoded, management_public_key, plan.image.management_ssh_port
        )
        return body + "</powershell>\n<persist>true</persist>\n"
    username = plan.username
    body = f"""#!/bin/bash
set -eu
id -u {username} >/dev/null 2>&1 || useradd --create-home --shell /bin/bash {username}
management_home=$(getent passwd {username} | cut -d: -f6)
case "$management_home" in /*) ;; *) exit 1;; esac
test "$management_home" != /
install -d -o {username} -g {username} -m 700 "$management_home/.ssh"
printf '%s\\n' '{management_public_key}' > "$management_home/.ssh/authorized_keys"
chown {username}:{username} "$management_home/.ssh/authorized_keys"
chmod 600 "$management_home/.ssh/authorized_keys"
printf '%s\\n' '{username} ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/90-shifter-management
chmod 440 /etc/sudoers.d/90-shifter-management
"""
    return body + linux_host_key_script(encoded, plan.image.management_ssh_port)


def guest_request(plan: Ec2GuestPlan, *, host_private_key: str, management_public_key: str) -> dict[str, Any]:
    """Render a no-role, encrypted, private-only EC2 request with a retry token."""
    user_data = _bootstrap(plan, host_private_key, management_public_key)
    if len(user_data.encode()) > 16384:
        raise Ec2GuestError("EC2 management bootstrap exceeds the user-data limit")
    return {
        "ImageId": plan.image.image_id,
        "InstanceType": plan.image.instance_type,
        "MinCount": 1,
        "MaxCount": 1,
        "ClientToken": plan.token,
        "NetworkInterfaces": [
            {
                "DeviceIndex": 0,
                "SubnetId": plan.subnet_id,
                "PrivateIpAddress": plan.private_ip,
                "AssociatePublicIpAddress": False,
                "DeleteOnTermination": True,
                "Groups": [plan.security_group_id],
            }
        ],
        "MetadataOptions": {"HttpTokens": "required", "HttpPutResponseHopLimit": 1, "InstanceMetadataTags": "disabled"},
        "BlockDeviceMappings": [
            {
                "DeviceName": plan.image.root_device,
                "Ebs": {
                    "Encrypted": True,
                    "VolumeSize": plan.image.disk_size_gb,
                    "VolumeType": plan.image.disk_type,
                    "DeleteOnTermination": True,
                },
            }
        ],
        "TagSpecifications": [
            {"ResourceType": kind, "Tags": plan.tags()} for kind in ("instance", "volume", "network-interface")
        ],
        "UserData": user_data,
    }


def _instances(response: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten only a complete bounded EC2 instance observation."""
    if response.get("NextToken"):
        raise Ec2GuestError("EC2 guest ownership observation exceeded its bound")
    return [row for reservation in response.get("Reservations", []) for row in reservation.get("Instances", [])]


def observe_ec2_guest(plan: Ec2GuestPlan, ec2: BaseClient, instance_id: str) -> dict[str, Any]:
    """Independently verify VM identity, containment and root snapshot provenance."""
    rows = _instances(ec2.describe_instances(InstanceIds=[instance_id]))
    if len(rows) != 1:
        raise Ec2GuestError("EC2 guest observation is unavailable or ambiguous")
    row = rows[0]
    _verify_interface(plan, row)
    _verify_identity(plan, row, instance_id)
    _verify_metadata_containment(row)
    disks = row.get("BlockDeviceMappings", [])
    if (
        row.get("RootDeviceName") != plan.image.root_device
        or len(disks) != 1
        or disks[0].get("DeviceName") != plan.image.root_device
        or disks[0].get("Ebs", {}).get("DeleteOnTermination") is not True
    ):
        raise Ec2GuestError("EC2 guest root disk differs from the admitted plan")
    _verify_boot_volume(plan, ec2, instance_id, disks[0]["Ebs"]["VolumeId"])
    return row


def _verify_boot_volume(plan: Ec2GuestPlan, ec2: BaseClient, instance_id: str, volume_id: str) -> None:
    """Verify the sole attached root volume against the admitted snapshot and sizing."""
    volumes = ec2.describe_volumes(VolumeIds=[volume_id]).get("Volumes", [])
    if len(volumes) != 1:
        raise Ec2GuestError("EC2 guest boot volume observation is unavailable")
    volume = volumes[0]
    attachments = volume.get("Attachments", [])
    expected_attachment = {"InstanceId": instance_id, "Device": plan.image.root_device, "State": "attached"}
    if (
        volume.get("VolumeId") != volume_id
        or volume.get("SnapshotId") != plan.image.root_snapshot
        or volume.get("Encrypted") is not True
        or volume.get("Size") != plan.image.disk_size_gb
        or volume.get("VolumeType") != plan.image.disk_type
        or len(attachments) != 1
        or any(attachments[0].get(key) != value for key, value in expected_attachment.items())
    ):
        raise Ec2GuestError("EC2 guest boot volume provenance or encryption differs")


def _verify_identity(plan: Ec2GuestPlan, row: dict[str, Any], instance_id: str) -> None:
    """Require exact VM identity, ownership tags and private-only instance metadata."""
    expected = {
        "InstanceId": instance_id,
        "ImageId": plan.image.image_id,
        "InstanceType": plan.image.instance_type,
        "SubnetId": plan.subnet_id,
        "PrivateIpAddress": plan.private_ip,
        "Architecture": plan.image.architecture,
    }
    tags = {item["Key"]: item["Value"] for item in row.get("Tags", [])}
    if (
        any(row.get(key) != value for key, value in expected.items())
        or any(tags.get(item["Key"]) != item["Value"] for item in plan.tags())
        or row.get("State", {}).get("Name") != "running"
        or {group["GroupId"] for group in row.get("SecurityGroups", [])} != {plan.security_group_id}
    ):
        raise Ec2GuestError("EC2 guest identity or containment differs from the admitted plan")


def _verify_metadata_containment(row: dict[str, Any]) -> None:
    """Require hop-limited authenticated metadata and no public interface association."""
    metadata = row.get("MetadataOptions", {})
    if (
        row.get("PublicIpAddress")
        or row.get("IamInstanceProfile")
        or metadata.get("HttpTokens") != "required"
        or metadata.get("HttpPutResponseHopLimit") != 1
        or any(interface.get("Association", {}).get("PublicIp") for interface in row.get("NetworkInterfaces", []))
    ):
        raise Ec2GuestError("EC2 guest identity or containment differs from the admitted plan")


def _verify_interface(plan: Ec2GuestPlan, row: dict[str, Any]) -> None:
    """Reject extra addresses, public exposure or unadmitted interface attachments."""
    interfaces = row.get("NetworkInterfaces", [])
    if len(interfaces) != 1:
        raise Ec2GuestError("EC2 guest interface inventory differs from intent")
    interface = interfaces[0]
    _verify_primary_address(interface, plan.private_ip)
    if (
        interface.get("SubnetId") != plan.subnet_id
        or interface.get("PrivateIpAddress") != plan.private_ip
        or any(interface.get(field) for field in ("Ipv6Addresses", "Ipv4Prefixes", "Ipv6Prefixes", "Association"))
        or interface.get("Attachment", {}).get("DeviceIndex") != 0
        or interface.get("Attachment", {}).get("DeleteOnTermination") is not True
        or {group["GroupId"] for group in interface.get("Groups", [])} != {plan.security_group_id}
    ):
        raise Ec2GuestError("EC2 guest interface has unadmitted addressing or attachment")


def _verify_primary_address(interface: dict[str, Any], private_ip: str) -> None:
    """Permit exactly the admitted primary private address, with no public association."""
    addresses = interface.get("PrivateIpAddresses", [])
    if (
        len(addresses) != 1
        or addresses[0].get("PrivateIpAddress") != private_ip
        or addresses[0].get("Primary") is not True
        or addresses[0].get("Association")
    ):
        raise Ec2GuestError("EC2 guest interface has unadmitted addressing or attachment")


def _resume_guest(plan: Ec2GuestPlan, ec2: BaseClient, row: dict[str, Any]) -> str:
    """Reuse only the exact tagged generation and verify its running state."""
    instance_id = row["InstanceId"]
    tags = {item["Key"]: item["Value"] for item in row.get("Tags", [])}
    if any(tags.get(item["Key"]) != item["Value"] for item in plan.tags()):
        raise Ec2GuestError("EC2 guest belongs to another range or generation")
    if row.get("State", {}).get("Name") == "pending":
        ec2.get_waiter("instance_running").wait(InstanceIds=[instance_id], WaiterConfig={"Delay": 5, "MaxAttempts": 60})
    observe_ec2_guest(plan, ec2, instance_id)
    return instance_id


def ensure_ec2_guest(plan: Ec2GuestPlan, ec2: BaseClient, secrets: Ec2GuestSecrets) -> dict[str, Any]:
    """Converge only this operation generation's guest, then return management facts."""
    filters = [
        {"Name": f"tag:{item['Key']}", "Values": [item["Value"]]}
        for item in plan.tags()
        if item["Key"] not in {"shifter:generation", "shifter:image"}
    ]
    filters.append(
        {"Name": "instance-state-name", "Values": ["pending", "running", "stopping", "stopped", "shutting-down"]}
    )
    # No MaxResults: EC2 derives NextToken from its account-wide instance scan, not
    # these tag filters, so a bounded page spuriously reports incompleteness once the
    # account holds more instances than the page. The server-side filters already scope
    # the result to this range's few instances; _instances still rejects a genuine
    # NextToken (a result set larger than one default page).
    rows = _instances(ec2.describe_instances(Filters=filters))
    if len(rows) > 1:
        raise Ec2GuestError("EC2 guest ownership is ambiguous")
    if rows:
        instance_id = _resume_guest(plan, ec2, rows[0])
    host_ref, public = secrets.host_ssh(plan.range_id, plan.instance_key, create=not rows)
    private, host_public = secrets.host_identity(plan.range_id, plan.instance_key, create=not rows)
    if not rows:
        response = ec2.run_instances(**guest_request(plan, host_private_key=private, management_public_key=public))
        created = response.get("Instances", [])
        if len(created) != 1:
            raise Ec2GuestError("EC2 creation returned an ambiguous result")
        instance_id = created[0]["InstanceId"]
        ec2.get_waiter("instance_running").wait(InstanceIds=[instance_id], WaiterConfig={"Delay": 5, "MaxAttempts": 60})
        observe_ec2_guest(plan, ec2, instance_id)
    return {
        "uuid": plan.instance_key,
        "name": plan.name,
        "os": plan.os_family,
        "asset_type": "ec2_vm",
        "instance_id": instance_id,
        "private_ip": plan.private_ip,
        "host_ssh_username": plan.username,
        "host_ssh_port": plan.image.management_ssh_port,
        "host_ssh_key_secret_ref": host_ref,
        "host_public_key": host_public,
        "participant_access_channels": [],
        "participant_access_usernames": {},
        **_contract_output(plan.image),
    }
