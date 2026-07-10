"""Tests for RDP credential resolution (engine.services._common).

Covers the seat-user resolution added for TechVault (#1465): a non-DC guest
RDPs in as its recorded ssh_username when present, else the os_type default;
a domain controller keeps its domain-admin login.

These assert observable behavior through the real resolver rather than
mocking first-party internals (ADR-019-R1). The username-selection cases
carry no per-instance secret reference, so the real non-DC password path
returns ``None`` with no credential-store call. The DC case drives the real
``DC_DOMAIN_PASSWORD`` env-var contract.
"""

from engine.services import _common


class TestResolveRdpCredentials:
    """_resolve_rdp_credentials username/password selection."""

    def test_prefers_recorded_ssh_username_over_os_default(self):
        """TechVault: os_type kali but seat user ubuntu -> RDP as ubuntu (#1465)."""
        inst = {"os_type": "kali", "role": "attacker", "ssh_username": "ubuntu"}
        username, password = _common._resolve_rdp_credentials(inst)
        assert username == "ubuntu"
        # No secret reference recorded, so the real resolver reports no password.
        assert password is None

    def test_falls_back_to_os_default_when_no_ssh_username(self):
        """Standard kali host with no recorded seat user -> os_type default."""
        inst = {"os_type": "kali", "role": "attacker"}
        username, _ = _common._resolve_rdp_credentials(inst)
        assert username == "kali"

    def test_domain_controller_keeps_domain_admin(self, monkeypatch):
        """A DC RDPs as the domain admin regardless of any ssh_username."""
        monkeypatch.setenv("CLOUD_PROVIDER", "aws")
        monkeypatch.setenv("DC_DOMAIN_PASSWORD", "dcpw")
        inst = {"os_type": "windows", "role": "dc", "ssh_username": "ignore-me"}
        username, password = _common._resolve_rdp_credentials(inst)
        assert username == "Administrator"
        assert password == "dcpw"
