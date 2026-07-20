"""Regression tests for the range-guest DNS pin in the AWS range Terraform.

Range guests intermittently failed to register with SSM because
``systemd-resolved`` came up with no upstream DNS on some boots, so the
system resolver SERVFAILed and the SSM agent looped on
``server misbehaving`` forever (issue #1632). The provisioner range module
now pins the link-local AmazonProvidedDNS in the Linux guest user_data,
defined once as the ``linux_range_dns_pin`` local and injected into both
Linux templates via the ``dns_pin`` variable.

These are structural (text) assertions on the Terraform sources: the range
templates are consumed by ``templatefile()`` at apply time, not by Python,
so this guards the wiring without a live ``terraform`` render (see
``test_terraform_base.py`` for the same text-level approach to this module).
"""

from __future__ import annotations

from pathlib import Path

_RANGE_MODULE = Path(__file__).resolve().parents[1] / "terraform" / "modules" / "range"
_TEMPLATES = _RANGE_MODULE / "templates"
_LINUX_TEMPLATES = ("kali.sh.tpl", "victim_linux.sh.tpl")


def _main_tf() -> str:
    return (_RANGE_MODULE / "main.tf").read_text()


def test_main_tf_defines_dns_pin_local() -> None:
    """The DNS pin is defined once as a local carrying the fix."""
    main_tf = _main_tf()
    assert "linux_range_dns_pin" in main_tf
    # Link-local AmazonProvidedDNS is CIDR-agnostic and reachable in every VPC.
    assert "169.254.169.253" in main_tf
    assert "resolved.conf.d/amazon-vpc-dns.conf" in main_tf
    # Guarded so it is a no-op on hosts without systemd-resolved.
    assert "systemctl cat systemd-resolved.service" in main_tf


def test_linux_templates_inject_dns_pin() -> None:
    """Both Linux guest templates render the injected DNS pin variable."""
    for name in _LINUX_TEMPLATES:
        body = (_TEMPLATES / name).read_text()
        assert "${dns_pin}" in body, f"{name} must inject ${{dns_pin}}"


def test_main_tf_passes_dns_pin_to_linux_templatefiles() -> None:
    """main.tf wires the local into the kali and victim_linux templatefile calls."""
    main_tf = _main_tf()
    # Both Linux templatefile invocations must pass dns_pin; the Windows/DC
    # ones must not (they use a different resolver stack).
    assert (
        main_tf.count("dns_pin    = local.linux_range_dns_pin") + main_tf.count("dns_pin  = local.linux_range_dns_pin")
        >= 2
    )


def test_windows_templates_do_not_reference_dns_pin() -> None:
    """The AmazonProvidedDNS pin is Linux-only; Windows/DC guests are untouched."""
    for name in ("victim_windows.ps1.tpl", "dc_windows.ps1.tpl"):
        body = (_TEMPLATES / name).read_text()
        assert "dns_pin" not in body
        assert "169.254.169.253" not in body
