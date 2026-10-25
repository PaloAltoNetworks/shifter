"""Static checks of the legacy AWS per-range OpenVPN gateway module.

The module is retired by #2481 (AWS moves to the shared OpenVPN pool, #2480);
these checks cover it until then.
"""

from __future__ import annotations

from pathlib import Path


def test_aws_gateway_stays_pending_until_service_and_policy_probe():
    module = Path(__file__).parents[1] / "terraform" / "modules" / "range"
    outputs = (module / "outputs.tf").read_text(encoding="utf-8")
    resources = (module / "vpn.tf").read_text(encoding="utf-8")
    bootstrap = (module / "templates" / "openvpn_gateway_aws.py.tpl").read_text(encoding="utf-8")

    assert "health_port     = 1195" in outputs
    assert "health_endpoint = aws_instance.vpn_gateway[0].private_ip" in outputs
    assert "ready           = false" in outputs
    assert "cidr_blocks = [var.vpn_public_client_cidr]" in resources
    assert "instance.instance_uuid == var.openvpn_access.target_ref" in resources
    assert 'instance.role == "attacker"' not in resources
    assert "cidr_blocks       = [var.portal_vpc_cidr]" in resources
    assert 'resource "aws_lb_listener" "vpn_health"' not in resources
    assert 'protocol            = "TCP"' in resources
    assert 'port                = "1195"' in resources
    assert "shifter-openvpn-health.service" in bootstrap
    assert 'systemctl", "is-active", "--quiet", "openvpn-server@server"' in bootstrap
    assert '"iptables", "-C", "FORWARD", "-i", "tun0"' in bootstrap
    assert 'self.request.sendall(b"ready\\n")' in bootstrap


def test_aws_gateway_bootstrap_uses_the_baked_runtime_without_package_egress():
    module = Path(__file__).parents[1] / "terraform" / "modules" / "range"
    bootstrap = (module / "templates" / "openvpn_gateway_aws.py.tpl").read_text(encoding="utf-8")

    assert "package_update:" not in bootstrap
    assert "\npackages:" not in bootstrap
    assert "apt-get" not in bootstrap
    assert "import boto3" in bootstrap
    assert "  - [python3, /usr/local/sbin/configure-shifter-openvpn.py]" in bootstrap


def test_aws_gateway_secrets_client_uses_the_module_region():
    module = Path(__file__).parents[1] / "terraform" / "modules" / "range"
    bootstrap = (module / "templates" / "openvpn_gateway_aws.py.tpl").read_text(encoding="utf-8")
    resources = (module / "vpn.tf").read_text(encoding="utf-8")

    assert 'boto3.client("secretsmanager", region_name="${region}")' in bootstrap
    assert "region       = substr(var.availability_zone, 0, length(var.availability_zone) - 1)" in resources


def test_aws_gateway_server_uses_ecdh_without_a_static_dh_file():
    module = Path(__file__).parents[1] / "terraform" / "modules" / "range"
    bootstrap = (module / "templates" / "openvpn_gateway_aws.py.tpl").read_text(encoding="utf-8")

    assert "\n      dh none\n" in bootstrap
    assert "dh /etc/openvpn" not in bootstrap
