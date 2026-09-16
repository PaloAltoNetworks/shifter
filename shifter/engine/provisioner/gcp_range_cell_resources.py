"""Compute Engine API resource bodies for GCE range cells.

Field names are the google-cloud-compute (proto-plus) message field names
(snake_case), not the REST/JSON camelCase, because these dicts are passed to the
``*_resource=`` kwargs of the Compute clients, which construct the proto messages
from them. Note the proto-plus quirks ``I_p_protocol`` (REST ``IPProtocol``) and
``network_i_p`` (REST ``networkIP``).

The OpenVPN forwarding-gateway bodies live in ``_gcp_range_cell_openvpn`` and are
re-exported here, so importers see the same surface as before that split.
"""

from __future__ import annotations

from typing import Any, cast

from _gcp_range_cell_openvpn import (
    openvpn_gateway_address_resource,
    openvpn_gateway_instance_resource,
)
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

__all__ = [
    "HOST_PUBLIC_KEY_METADATA_KEY",
    "address_resource",
    "firewall_resource",
    "instance_resource",
    "network_resource",
    "openvpn_gateway_address_resource",
    "openvpn_gateway_instance_resource",
    "router_nat_resource",
    "subnetwork_resource",
]


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


def router_nat_resource(plan: RangeCellPlan) -> ComputeResource:
    """Render a range-owned Cloud Router + Cloud NAT insert body (PLAT-238, ADR-026-R6).

    The NAT is scoped to exactly this range's participant subnets
    (``LIST_OF_SUBNETWORKS``) with automatic NAT-IP allocation, so a range's egress
    path is range-owned and independent -- a ``none`` range simply has no router/NAT
    and therefore no NAT path, and range jobs never patch a shared Terraform-owned
    NAT object concurrently.
    """
    router_nat = plan["router_nat"]
    return {
        "name": router_nat["router_name"],
        "network": plan["network"]["self_link"],
        "region": plan["region"],
        "nats": [
            {
                "name": router_nat["nat_name"],
                "nat_ip_allocate_option": "AUTO_ONLY",
                "source_subnetwork_ip_ranges_to_nat": "LIST_OF_SUBNETWORKS",
                "subnetworks": [
                    {"name": self_link, "source_ip_ranges_to_nat": ["ALL_IP_RANGES"]}
                    for self_link in router_nat["subnetwork_self_links"]
                ],
            }
        ],
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

    The script is written to fail *loudly* and to converge. The previous version
    redirected every error to ``/dev/null`` and ended in ``|| true``, and wrote
    the key by truncating the live file in place. That combination turns any
    failure — a partial write, an invalid decode, a refused restart, or another
    boot unit regenerating host keys afterwards — into a guest that serves a key
    the portal does not trust, with nothing in the serial log to say so. The
    portal then rejects every terminal session for the life of the range with
    ``HostKeyNotVerifiable``, which is exactly the failure observed on range 6
    (issue #987): the recorded key and the served key had diverged, silently.

    So: decode to a temporary file, validate it before it can replace anything,
    install it atomically, then verify that sshd is actually serving the intended
    key and retry the restart once if it is not. Every step logs a
    ``shifter-hostkey:`` marker to stdout, which the guest agent forwards to the
    serial console, so a future divergence is diagnosable instead of invisible.

    The whole body is a single function invoked once, and it never calls
    ``exit``: the range composition script is *concatenated* onto this one, so an
    early exit here would silently skip building the range's content.
    """
    return (
        "#!/bin/bash\n"
        "shifter_install_host_key() {\n"
        "  local tmp want got attempt\n"
        '  log() { echo "shifter-hostkey: $*"; }\n'
        "  restart_ssh() { systemctl restart ssh 2>/dev/null || systemctl restart sshd 2>/dev/null; }\n"
        "  tmp=$(mktemp)\n"
        f"  if ! printf %s '{host_private_key_b64}' | base64 -d > \"$tmp\"; then\n"
        '    log "FAILED to decode host key material"; rm -f "$tmp"; return 1\n'
        "  fi\n"
        '  chmod 600 "$tmp"\n'
        # Validate before install: a corrupt key must never replace a working one.
        '  if ! want=$(ssh-keygen -y -f "$tmp" 2>/dev/null); then\n'
        '    log "FAILED decoded host key is not a valid private key"; rm -f "$tmp"; return 1\n'
        "  fi\n"
        '  install -o root -g root -m 600 "$tmp" /etc/ssh/ssh_host_ed25519_key\n'
        '  rm -f "$tmp"\n'
        '  printf "%s\\n" "$want" > /etc/ssh/ssh_host_ed25519_key.pub\n'
        "  chmod 644 /etc/ssh/ssh_host_ed25519_key.pub\n"
        "  chown root:root /etc/ssh/ssh_host_ed25519_key.pub\n"
        '  if ! restart_ssh; then log "WARNING could not restart the ssh service"; fi\n'
        # Converge: confirm sshd actually serves the intended key, once it is up.
        "  for attempt in 1 2 3 4 5; do\n"
        "    got=$(ssh-keyscan -t ed25519 -T 5 127.0.0.1 2>/dev/null | awk '{print $2\" \"$3}' | tail -n1)\n"
        '    if [ "$got" = "$want" ]; then log "OK serving the provisioner-issued host key"; return 0; fi\n'
        "    sleep 3\n"
        '    if [ "$attempt" = 3 ]; then log "retrying ssh restart"; restart_ssh || true; fi\n'
        "  done\n"
        '  log "FAILED sshd is not serving the provisioner-issued host key"\n'
        "  return 1\n"
        "}\n"
        "shifter_install_host_key || true\n"
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
    composition_script: str = "",
) -> list[dict[str, str]]:
    """Render guest metadata: provisioned user key, host key install, host pubkey.

    ``composition_script`` (empty on the cyberscript path) is appended to the guest
    startup script after the host-key install, so the RAES-native path realizes
    node content/features/accounts as part of the same idempotent bootstrap.
    """
    items = [{"key": key, "value": value} for key, value in config.metadata_items]
    items.append({"key": "ssh-keys", "value": f"{username}:{public_key}"})
    if host_public_key:
        items.append({"key": HOST_PUBLIC_KEY_METADATA_KEY, "value": host_public_key})
    if os_type == "windows":
        boot = _windows_boot_script(host_private_key_b64, public_key) + composition_script
        items.append({"key": "windows-startup-script-ps1", "value": boot})
    elif host_private_key_b64:
        items.append(
            {"key": "startup-script", "value": _linux_host_key_script(host_private_key_b64) + composition_script}
        )
    return items


def instance_resource(
    plan: RangeCellPlan,
    instance: InstancePlan,
    config: GCERangeCellConfig,
    *,
    ssh_public_key: str,
    host_private_key_b64: str = "",
    host_public_key: str = "",
    composition_script: str = "",
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
            "image-key": _label_value(instance["image_key"] or "default"),
            "image-profile": instance["image_profile_fingerprint"],
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
                composition_script=composition_script,
            )
        },
        "network_interfaces": [
            {
                "subnetwork": instance["subnetwork_link"],
                "network_i_p": instance["private_ip"],
            }
        ],
        "deletion_protection": False,
        "can_ip_forward": False,
    }
    if profile.source_machine_image:
        # The machine image supplies every captured disk. Network, metadata,
        # identity, labels, tags, machine type, and external-IP posture are all
        # explicitly replaced by the body above.
        body["advanced_machine_features"] = {"enable_nested_virtualization": True}
    else:
        body["disks"] = [
            {
                "boot": True,
                "auto_delete": True,
                "initialize_params": {
                    "source_image": profile.source_image,
                    "disk_size_gb": int(profile.disk_size_gb),
                    "disk_type": _disk_type_self_link(plan["zone"], profile.disk_type),
                },
            }
        ]
        body["shielded_instance_config"] = {
            "enable_secure_boot": True,
            "enable_vtpm": True,
            "enable_integrity_monitoring": True,
        }
    service_account_email = str(instance.get("service_account_email") or "")
    if not service_account_email and config.service_account_email and instance["attach_service_account"]:
        service_account_email = config.service_account_email
    if service_account_email:
        body["service_accounts"] = [
            {
                "email": service_account_email,
                "scopes": list(config.service_account_scopes),
            }
        ]
    return body
