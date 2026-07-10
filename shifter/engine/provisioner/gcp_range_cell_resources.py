"""Compute Engine API resource bodies for GCE range cells.

Field names are the google-cloud-compute (proto-plus) message field names
(snake_case), not the REST/JSON camelCase, because these dicts are passed to the
``*_resource=`` kwargs of the Compute clients, which construct the proto messages
from them. Note the proto-plus quirks ``I_p_protocol`` (REST ``IPProtocol``) and
``network_i_p`` (REST ``networkIP``).
"""

from __future__ import annotations

from typing import Any, cast

from config import GCERangeCellConfig
from gcp_range_cell_naming import (
    _disk_type_self_link,
    _label_value,
    _machine_type_self_link,
)
from gcp_range_cell_plan import (
    ComputeResource,
    FirewallPlan,
    InstancePlan,
    RangeCellPlan,
    SubnetPlan,
)


# Compute network, subnetwork, firewall, and address resources are NOT labelable
# (the proto has no `labels` field); only instances/disks carry range labels.
def network_resource(plan: RangeCellPlan) -> ComputeResource:
    """Render a Compute Engine network insert body."""
    return {
        "name": plan["network"]["name"],
        "auto_create_subnetworks": False,
        "routing_config": {"routing_mode": "REGIONAL"},
    }


def subnetwork_resource(plan: RangeCellPlan, subnet: SubnetPlan) -> ComputeResource:
    """Render a Compute Engine subnetwork insert body."""
    return {
        "name": subnet["resource_name"],
        "network": subnet["network_link"],
        "ip_cidr_range": subnet["cidr"],
        "region": plan["region"],
        "private_ip_google_access": plan["private_google_access"],
    }


def firewall_resource(plan: RangeCellPlan, firewall: FirewallPlan) -> ComputeResource:
    """Render a Compute Engine firewall insert body."""
    body: ComputeResource = {
        "name": firewall["name"],
        "network": plan["network"]["self_link"],
        "direction": firewall["direction"],
        "priority": firewall["priority"],
        "target_tags": firewall["target_tags"],
    }
    for cidr_key in ("source_ranges", "destination_ranges"):
        value = firewall.get(cidr_key)
        if value:
            body[cidr_key] = value
    for rule_key in ("allowed", "denied"):
        rules = firewall.get(rule_key)
        if rules:
            body[rule_key] = [_firewall_rule(rule) for rule in cast("list[dict[str, Any]]", rules)]
    return body


def _firewall_rule(rule: dict[str, Any]) -> dict[str, Any]:
    """Translate a firewall rule to the proto field names (IPProtocol -> I_p_protocol)."""
    translated: dict[str, Any] = {}
    for field, proto_field in (("IPProtocol", "I_p_protocol"), ("ports", "ports")):
        if field in rule:
            translated[proto_field] = rule[field]
    return translated


def address_resource(instance: InstancePlan) -> ComputeResource:
    """Render a Compute Engine internal address insert body."""
    return {
        "name": instance["address_name"],
        "address_type": "INTERNAL",
        "address": instance["private_ip"],
        "subnetwork": instance["subnetwork_link"],
    }


# Metadata key carrying the provisioner-issued SSH host public key, so a reconcile
# (instance already exists) can recover the host key that was injected at create
# time instead of minting a fresh one that would not match the running guest.
HOST_PUBLIC_KEY_METADATA_KEY = "shifter-host-public-key"


def _linux_host_key_script(host_private_key_b64: str) -> str:
    """Startup script that installs the provisioner-issued SSH host key on Linux.

    The provisioner generates the guest's host keypair and seeds its own
    known_hosts with the public half, so StrictHostKeyChecking validates against
    a trusted side-channel key rather than trust-on-first-use. Runs on every boot
    (idempotent: the same key is reinstalled).
    """
    return (
        "#!/bin/bash\n"
        f"printf %s '{host_private_key_b64}' | base64 -d > /etc/ssh/ssh_host_ed25519_key\n"
        "chmod 600 /etc/ssh/ssh_host_ed25519_key\n"
        "chown root:root /etc/ssh/ssh_host_ed25519_key\n"
        "ssh-keygen -y -f /etc/ssh/ssh_host_ed25519_key > /etc/ssh/ssh_host_ed25519_key.pub\n"
        "chmod 644 /etc/ssh/ssh_host_ed25519_key.pub\n"
        "systemctl restart ssh 2>/dev/null || systemctl restart sshd 2>/dev/null || true\n"
    )


def _windows_boot_script(host_private_key_b64: str, authorized_key: str) -> str:
    """Startup script for a Windows range guest.

    Installs the provisioner-issued SSH host key (with the strict ACLs Windows
    OpenSSH requires, else sshd refuses to start), authorizes the provisioner's
    public key for admin login (Windows OpenSSH ignores the GCE ``ssh-keys``
    metadata for members of the Administrators group and reads
    ``administrators_authorized_keys`` instead), then forces the Windows Firewall
    off and (re)starts sshd. The CTF domain controller serves LDAP/Kerberos/SMB
    firewall-off by design, and a pre-promoted DC can re-enable the firewall after
    promotion; forcing it off each boot keeps the guest reachable regardless of
    the captured firewall state.
    """
    key_path = "C:\\ProgramData\\ssh\\ssh_host_ed25519_key"
    admin_keys = "C:\\ProgramData\\ssh\\administrators_authorized_keys"
    keygen = "C:\\Windows\\System32\\OpenSSH\\ssh-keygen.exe"
    return (
        f"[IO.File]::WriteAllBytes('{key_path}', [Convert]::FromBase64String('{host_private_key_b64}'))\n"
        f"icacls '{key_path}' /inheritance:r /grant 'SYSTEM:(F)' /grant 'BUILTIN\\Administrators:(F)' | Out-Null\n"
        f"& '{keygen}' -y -f '{key_path}' | Out-File -Encoding ascii '{key_path}.pub'\n"
        f"Set-Content -Path '{admin_keys}' -Value '{authorized_key}' -Encoding ascii\n"
        f"icacls '{admin_keys}' /inheritance:r /grant 'SYSTEM:(F)' /grant 'BUILTIN\\Administrators:(F)' | Out-Null\n"
        "Set-NetFirewallProfile -Profile Domain,Public,Private -Enabled False\n"
        "Set-Service -Name sshd -StartupType Automatic -ErrorAction SilentlyContinue\n"
        "Restart-Service -Name sshd -ErrorAction SilentlyContinue\n"
    )


def _metadata_items(
    config: GCERangeCellConfig,
    username: str,
    public_key: str,
    *,
    os_type: str,
    host_private_key_b64: str,
    host_public_key: str,
) -> list[dict[str, str]]:
    """Render guest metadata: provisioned user key, host key install, host pubkey."""
    items = [{"key": key, "value": value} for key, value in config.metadata_items]
    items.append({"key": "ssh-keys", "value": f"{username}:{public_key}"})
    if host_public_key:
        items.append({"key": HOST_PUBLIC_KEY_METADATA_KEY, "value": host_public_key})
    if os_type == "windows":
        items.append(
            {"key": "windows-startup-script-ps1", "value": _windows_boot_script(host_private_key_b64, public_key)}
        )
    elif host_private_key_b64:
        items.append({"key": "startup-script", "value": _linux_host_key_script(host_private_key_b64)})
    return items


def instance_resource(
    plan: RangeCellPlan,
    instance: InstancePlan,
    config: GCERangeCellConfig,
    *,
    ssh_public_key: str,
    host_private_key_b64: str = "",
    host_public_key: str = "",
) -> ComputeResource:
    """Render a Compute Engine instance insert body."""
    profile = instance["profile"]
    body: ComputeResource = {
        "name": instance["resource_name"],
        "machine_type": _machine_type_self_link(plan["zone"], profile.machine_type),
        "labels": {
            **plan["labels"],
            "subnet": _label_value(instance["subnet_name"]),
            "role": _label_value(instance["role"]),
        },
        "tags": {"items": instance["tags"]},
        # Install the provisioned key for the host OS login user the provisioner
        # drives (host_ssh_username), not the participant-facing user. For a
        # Docker-host guest the participant user (e.g. "kali") belongs to the
        # published container, whose authorized_keys the range bootstrap sets;
        # the host OS user (e.g. "ubuntu") is what guest setup connects as. For
        # native guests the two are identical.
        "metadata": {
            "items": _metadata_items(
                config,
                instance["host_ssh_username"],
                ssh_public_key,
                os_type=instance["os_type"],
                host_private_key_b64=host_private_key_b64,
                host_public_key=host_public_key,
            )
        },
        "network_interfaces": [
            {
                "subnetwork": instance["subnetwork_link"],
                "network_i_p": instance["private_ip"],
            }
        ],
        "disks": [
            {
                "boot": True,
                "auto_delete": True,
                "initialize_params": {
                    "source_image": profile.source_image,
                    "disk_size_gb": int(profile.disk_size_gb),
                    "disk_type": _disk_type_self_link(plan["zone"], profile.disk_type),
                },
            }
        ],
        "shielded_instance_config": {
            "enable_secure_boot": True,
            "enable_vtpm": True,
            "enable_integrity_monitoring": True,
        },
        "deletion_protection": False,
    }
    if config.service_account_email:
        body["service_accounts"] = [
            {
                "email": config.service_account_email,
                "scopes": list(config.service_account_scopes),
            }
        ]
    return body
