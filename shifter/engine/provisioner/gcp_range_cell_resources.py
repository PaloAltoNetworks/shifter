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
    OpenVpnGatewayPlan,
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
    composition_script: str = "",
) -> list[dict[str, str]]:
    """Render guest metadata: provisioned user key, host key install, host pubkey.

    ``composition_script`` (empty on the cyberscript path) is appended to the guest
    startup script after the host-key install, so the ACES-native path realizes
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
    if config.service_account_email and instance["attach_service_account"]:
        body["service_accounts"] = [
            {
                "email": config.service_account_email,
                "scopes": list(config.service_account_scopes),
            }
        ]
    return body


def openvpn_gateway_address_resource(gateway: OpenVpnGatewayPlan) -> ComputeResource:
    """Render the gateway's deterministic private address reservation."""
    return {
        "name": gateway["address_name"],
        "address_type": "INTERNAL",
        "address": gateway["private_ip"],
        "subnetwork": gateway["subnetwork_link"],
    }


_OPENVPN_GATEWAY_STARTUP_TEMPLATE = '''#!/bin/bash
set -euo pipefail
install -d -m 700 /etc/openvpn/server
python3 - <<'PY'
import base64
import json
import pathlib
import subprocess
import urllib.parse
import urllib.request

metadata = urllib.request.Request(
    "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token",
    headers={{"Metadata-Flavor": "Google"}},
)
with urllib.request.urlopen(metadata, timeout=10) as response:
    token = json.load(response)["access_token"]
name = urllib.parse.quote("projects/{project_id}/secrets/{secret_id}/versions/latest", safe="")
request = urllib.request.Request(
    f"https://secretmanager.googleapis.com/v1/{{name}}:access",
    headers={{"Authorization": f"Bearer {{token}}"}},
)
with urllib.request.urlopen(request, timeout=20) as response:
    material = json.loads(base64.b64decode(json.load(response)["payload"]["data"]))
if set(material) != {{"ca", "certificate", "private_key", "tls_crypt"}}:
    raise RuntimeError("OpenVPN server identity has an invalid shape")
directory = pathlib.Path("/etc/openvpn/server")
for filename, field in (
    ("ca.crt", "ca"),
    ("server.crt", "certificate"),
    ("server.key", "private_key"),
    ("tls-crypt.key", "tls_crypt"),
):
    path = directory / filename
    path.write_text(material[field], encoding="utf-8")
    path.chmod(0o600)
config = """port 1194
proto udp4
dev tun
topology subnet
server 172.30.0.0 255.255.255.0
ca /etc/openvpn/server/ca.crt
cert /etc/openvpn/server/server.crt
key /etc/openvpn/server/server.key
tls-crypt /etc/openvpn/server/tls-crypt.key
verify-client-cert require
remote-cert-eku "TLS Web Client Authentication"
push "route {target_ip} 255.255.255.255"
keepalive 10 60
persist-key
persist-tun
user nobody
group nogroup
auth SHA256
cipher AES-256-GCM
data-ciphers AES-256-GCM:AES-128-GCM
tls-version-min 1.2
explicit-exit-notify 1
verb 3
"""
(directory / "server.conf").write_text(config, encoding="utf-8")
(directory / "server.conf").chmod(0o600)
pathlib.Path("/etc/sysctl.d/90-shifter-openvpn.conf").write_text("net.ipv4.ip_forward=1\\n", encoding="utf-8")
subprocess.run(["sysctl", "--system"], check=True, stdout=subprocess.DEVNULL)
for rule in (
    ["iptables", "-P", "FORWARD", "DROP"],
    ["iptables", "-A", "FORWARD", "-i", "tun0", "-d", "{target_ip}/32", "-j", "ACCEPT"],
    [
        "iptables", "-A", "FORWARD", "-o", "tun0", "-s", "{target_ip}/32",
        "-m", "conntrack", "--ctstate", "ESTABLISHED,RELATED", "-j", "ACCEPT",
    ],
    [
        "iptables", "-t", "nat", "-A", "POSTROUTING", "-s", "172.30.0.0/24",
        "-d", "{target_ip}/32", "-j", "MASQUERADE",
    ],
):
    subprocess.run(rule, check=True)
subprocess.run(["systemctl", "enable", "--now", "openvpn-server@server"], check=True)
health_script = """#!/usr/bin/env python3
import socketserver
import subprocess

TARGET = "{target_ip}/32"

def healthy():
    active = subprocess.run(
        ["systemctl", "is-active", "--quiet", "openvpn-server@server"],
        check=False,
    ).returncode == 0
    policy = subprocess.run(
        ["iptables", "-S", "FORWARD"],
        check=False,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    rules = (
        ["iptables", "-C", "FORWARD", "-i", "tun0", "-d", TARGET, "-j", "ACCEPT"],
        [
            "iptables", "-C", "FORWARD", "-o", "tun0", "-s", TARGET,
            "-m", "conntrack", "--ctstate", "ESTABLISHED,RELATED", "-j", "ACCEPT",
        ],
        [
            "iptables", "-t", "nat", "-C", "POSTROUTING", "-s", "172.30.0.0/24",
            "-d", TARGET, "-j", "MASQUERADE",
        ],
    )
    return active and "-P FORWARD DROP" in policy and all(
        subprocess.run(rule, check=False).returncode == 0 for rule in rules
    )

class Handler(socketserver.BaseRequestHandler):
    def handle(self):
        if healthy():
            self.request.sendall(b"ready\\n")

class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True

with Server(("0.0.0.0", 1195), Handler) as server:
    server.serve_forever()
"""
health_path = pathlib.Path("/usr/local/sbin/shifter-openvpn-health.py")
health_path.write_text(health_script, encoding="utf-8")
health_path.chmod(0o700)
unit = """[Unit]
Description=Shifter OpenVPN service and target-policy readiness
Requires=openvpn-server@server.service
After=openvpn-server@server.service
BindsTo=openvpn-server@server.service

[Service]
Type=simple
ExecStart=/usr/local/sbin/shifter-openvpn-health.py
Restart=on-failure
RestartSec=2

[Install]
WantedBy=multi-user.target
"""
pathlib.Path("/etc/systemd/system/shifter-openvpn-health.service").write_text(unit, encoding="utf-8")
subprocess.run(["systemctl", "daemon-reload"], check=True)
subprocess.run(["systemctl", "enable", "--now", "shifter-openvpn-health"], check=True)
PY
'''


def _openvpn_gateway_startup(plan: RangeCellPlan, gateway: OpenVpnGatewayPlan) -> str:
    """Return a fixed bootstrap that resolves only the server identity secret."""
    secret_id = f"shifter-range-{plan['range_id']}-vpn-{plan['request_uuid'].replace('-', '')}-server"
    return _OPENVPN_GATEWAY_STARTUP_TEMPLATE.format(
        project_id=plan["project_id"],
        secret_id=secret_id,
        target_ip=gateway["target_ip"],
    )


def openvpn_gateway_instance_resource(
    plan: RangeCellPlan,
    gateway: OpenVpnGatewayPlan,
    config: GCERangeCellConfig,
) -> ComputeResource:
    """Render a request-owned forwarding gateway with one public UDP endpoint."""
    profile = gateway["profile"]
    body: ComputeResource = {
        "name": gateway["resource_name"],
        "machine_type": _machine_type_self_link(plan["zone"], profile.machine_type),
        "labels": {**plan["labels"], "role": "vpn-gateway"},
        "tags": {"items": [gateway["tag"]]},
        "can_ip_forward": True,
        "metadata": {"items": [{"key": "startup-script", "value": _openvpn_gateway_startup(plan, gateway)}]},
        "network_interfaces": [
            {
                "subnetwork": gateway["subnetwork_link"],
                "network_i_p": gateway["private_ip"],
                "access_configs": [{"name": "External NAT", "type_": "ONE_TO_ONE_NAT"}],
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
        "service_accounts": [
            {
                "email": gateway["service_account_email"],
                "scopes": list(config.service_account_scopes),
            }
        ],
        "shielded_instance_config": {
            "enable_secure_boot": True,
            "enable_vtpm": True,
            "enable_integrity_monitoring": True,
        },
        "deletion_protection": False,
    }
    return body
