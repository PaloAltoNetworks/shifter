"""OpenVPN forwarding-gateway Compute Engine resource bodies for GCE range cells.

Split out of ``gcp_range_cell_resources`` (which owns the range guest/network
bodies) so each module stays reviewable; the public renderers are re-exported
from that module, so importers are unaffected. The same proto-plus field-name
rules apply here (``network_i_p`` for REST ``networkIP``).
"""

from __future__ import annotations

from config import GCERangeCellConfig
from gcp_range_cell_naming import (
    _disk_type_self_link,
    _machine_type_self_link,
)
from gcp_range_cell_plan import (
    ComputeResource,
    OpenVpnGatewayPlan,
    RangeCellPlan,
)


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
import urllib.request

metadata = urllib.request.Request(
    "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token",
    headers={{"Metadata-Flavor": "Google"}},
)
with urllib.request.urlopen(metadata, timeout=10) as response:
    token = json.load(response)["access_token"]
name = "projects/{project_id}/secrets/{secret_id}/versions/latest"
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
dh none
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
            self.request.sendall(b"ready\\\\n")

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
