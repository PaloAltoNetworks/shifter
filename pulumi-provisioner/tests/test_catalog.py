"""Instance catalog tests for Pulumi provisioner.

Tests the instance type catalog which defines available instance configurations.
These are pure Python tests with no external dependencies.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from catalog.instances import (
    INSTANCE_CATALOG,
    InstanceType,
    get_attacker_types,
    get_available_instance_types,
    get_instance_type,
    get_victim_types,
)


class TestInstanceTypeCatalog:
    """Tests for the instance type catalog definitions."""

    def test_kali_instance_type(self):
        """Kali instance has correct configuration."""
        kali = INSTANCE_CATALOG.get("kali-2024")
        assert kali is not None
        assert kali.name == "kali-2024"
        assert kali.role == "attacker"
        assert kali.default_instance_type == "t3.small"
        assert kali.user_data_template == "kali.sh.j2"
        assert kali.ssh_user == "kali"
        assert kali.requires_agent is False
        assert kali.ami_lookup is not None
        assert "kali" in kali.ami_lookup.get("name", "").lower()

    def test_ubuntu_22_instance_type(self):
        """Ubuntu 22.04 victim instance has correct configuration."""
        ubuntu = INSTANCE_CATALOG.get("ubuntu-22.04-victim")
        assert ubuntu is not None
        assert ubuntu.name == "ubuntu-22.04-victim"
        assert ubuntu.role == "victim"
        assert ubuntu.default_instance_type == "t3.micro"
        assert ubuntu.user_data_template == "victim_linux.sh.j2"
        assert ubuntu.ssh_user == "ubuntu"
        assert ubuntu.requires_agent is True
        assert ubuntu.ami_lookup is not None
        assert "jammy" in ubuntu.ami_lookup.get("name", "").lower()

    def test_ubuntu_24_instance_type(self):
        """Ubuntu 24.04 victim instance has correct configuration."""
        ubuntu = INSTANCE_CATALOG.get("ubuntu-24.04-victim")
        assert ubuntu is not None
        assert ubuntu.name == "ubuntu-24.04-victim"
        assert ubuntu.role == "victim"
        assert ubuntu.default_instance_type == "t3.micro"
        assert ubuntu.user_data_template == "victim_linux.sh.j2"
        assert ubuntu.ssh_user == "ubuntu"
        assert ubuntu.requires_agent is True
        assert ubuntu.ami_lookup is not None
        assert "noble" in ubuntu.ami_lookup.get("name", "").lower()

    def test_windows_instance_type(self):
        """Windows Server 2022 victim instance has correct configuration."""
        windows = INSTANCE_CATALOG.get("windows-server-2022-victim")
        assert windows is not None
        assert windows.name == "windows-server-2022-victim"
        assert windows.role == "victim"
        assert windows.default_instance_type == "t3.medium"
        assert windows.user_data_template == "victim_windows.ps1.j2"
        assert windows.ssh_user == "Administrator"
        assert windows.requires_agent is True
        assert windows.ami_lookup is not None
        assert "Windows" in windows.ami_lookup.get("name", "")

    def test_amazon_linux_instance_type(self):
        """Amazon Linux 2023 victim instance has correct configuration."""
        amzn = INSTANCE_CATALOG.get("amazon-linux-2023-victim")
        assert amzn is not None
        assert amzn.name == "amazon-linux-2023-victim"
        assert amzn.role == "victim"
        assert amzn.default_instance_type == "t3.micro"
        assert amzn.user_data_template == "victim_linux.sh.j2"
        assert amzn.ssh_user == "ec2-user"
        assert amzn.requires_agent is True
        assert amzn.ami_lookup is not None
        assert "al2023" in amzn.ami_lookup.get("name", "").lower()


class TestInstanceTypeRoles:
    """Tests for instance role assignments."""

    def test_all_attackers_have_role_attacker(self):
        """All attacker types should have role='attacker'."""
        attacker_types = get_attacker_types()
        assert len(attacker_types) >= 1, "Should have at least one attacker type"

        for name in attacker_types:
            instance_type = get_instance_type(name)
            assert instance_type is not None
            assert instance_type.role == "attacker", f"{name} should have role='attacker'"

    def test_all_victims_have_role_victim(self):
        """All victim types should have role='victim'."""
        victim_types = get_victim_types()
        assert len(victim_types) >= 1, "Should have at least one victim type"

        for name in victim_types:
            instance_type = get_instance_type(name)
            assert instance_type is not None
            assert instance_type.role == "victim", f"{name} should have role='victim'"

    def test_all_victims_require_agent(self):
        """All victim types should require XDR agent."""
        victim_types = get_victim_types()

        for name in victim_types:
            instance_type = get_instance_type(name)
            assert instance_type is not None
            assert (
                instance_type.requires_agent is True
            ), f"{name} should require agent"

    def test_attacker_does_not_require_agent(self):
        """Attacker types should NOT require XDR agent."""
        attacker_types = get_attacker_types()

        for name in attacker_types:
            instance_type = get_instance_type(name)
            assert instance_type is not None
            assert (
                instance_type.requires_agent is False
            ), f"{name} should not require agent"


class TestLookupFunctions:
    """Tests for catalog lookup functions."""

    def test_get_instance_type_exists(self):
        """get_instance_type returns InstanceType for known name."""
        result = get_instance_type("kali-2024")
        assert result is not None
        assert isinstance(result, InstanceType)
        assert result.name == "kali-2024"

    def test_get_instance_type_not_found(self):
        """get_instance_type returns None for unknown name."""
        result = get_instance_type("nonexistent-type")
        assert result is None

    def test_get_instance_type_case_sensitive(self):
        """get_instance_type is case-sensitive."""
        # These should fail (wrong case)
        assert get_instance_type("KALI-2024") is None
        assert get_instance_type("Kali-2024") is None

    def test_get_available_instance_types(self):
        """get_available_instance_types returns all catalog keys."""
        result = get_available_instance_types()
        assert isinstance(result, list)
        assert len(result) >= 5, "Should have at least 5 instance types"
        assert "kali-2024" in result
        assert "ubuntu-22.04-victim" in result
        assert "ubuntu-24.04-victim" in result
        assert "windows-server-2022-victim" in result
        assert "amazon-linux-2023-victim" in result

    def test_get_attacker_types(self):
        """get_attacker_types returns only attacker types."""
        result = get_attacker_types()
        assert isinstance(result, list)
        assert len(result) >= 1
        assert "kali-2024" in result

        # Should not contain any victim types
        for name in result:
            instance_type = get_instance_type(name)
            assert instance_type.role == "attacker"

    def test_get_victim_types(self):
        """get_victim_types returns only victim types."""
        result = get_victim_types()
        assert isinstance(result, list)
        assert len(result) >= 4  # ubuntu22, ubuntu24, windows, amazon-linux

        # Should not contain any attacker types
        for name in result:
            instance_type = get_instance_type(name)
            assert instance_type.role == "victim"

    def test_attacker_and_victim_types_disjoint(self):
        """Attacker and victim types should have no overlap."""
        attackers = set(get_attacker_types())
        victims = set(get_victim_types())

        overlap = attackers & victims
        assert len(overlap) == 0, f"Found overlapping types: {overlap}"

    def test_all_types_covered(self):
        """Attacker + victim types should equal all available types."""
        all_types = set(get_available_instance_types())
        attackers = set(get_attacker_types())
        victims = set(get_victim_types())

        combined = attackers | victims
        assert combined == all_types, "Some instance types are neither attacker nor victim"


class TestInstanceTypeDataclass:
    """Tests for the InstanceType dataclass."""

    def test_instance_type_defaults(self):
        """InstanceType has correct default values."""
        it = InstanceType(
            name="test",
            role="victim",
            default_instance_type="t3.micro",
            user_data_template="test.sh.j2",
            description="Test instance",
        )
        assert it.ami_lookup is None
        assert it.requires_agent is False
        assert it.ssh_user == "ubuntu"

    def test_instance_type_all_fields(self):
        """InstanceType can be created with all fields populated."""
        it = InstanceType(
            name="test-full",
            role="attacker",
            default_instance_type="t3.large",
            user_data_template="custom.sh.j2",
            description="Fully configured instance",
            ami_lookup={"name": "test-ami-*", "owner": "123456789"},
            requires_agent=True,
            ssh_user="admin",
        )
        assert it.name == "test-full"
        assert it.role == "attacker"
        assert it.default_instance_type == "t3.large"
        assert it.user_data_template == "custom.sh.j2"
        assert it.description == "Fully configured instance"
        assert it.ami_lookup == {"name": "test-ami-*", "owner": "123456789"}
        assert it.requires_agent is True
        assert it.ssh_user == "admin"


class TestCatalogConsistency:
    """Tests for catalog consistency and correctness."""

    def test_all_templates_exist(self):
        """All referenced user_data_templates should be valid filenames."""
        templates_dir = Path(__file__).parent.parent / "templates"

        for name, instance_type in INSTANCE_CATALOG.items():
            template_path = templates_dir / instance_type.user_data_template
            assert template_path.exists(), f"Template {instance_type.user_data_template} not found for {name}"

    def test_all_have_description(self):
        """All instance types should have a description."""
        for name, instance_type in INSTANCE_CATALOG.items():
            assert instance_type.description, f"{name} should have a description"
            assert len(instance_type.description) > 10, f"{name} description too short"

    def test_all_have_ami_lookup(self):
        """All instance types should have AMI lookup configuration."""
        for name, instance_type in INSTANCE_CATALOG.items():
            assert instance_type.ami_lookup is not None, f"{name} should have ami_lookup"
            assert "name" in instance_type.ami_lookup, f"{name} ami_lookup should have 'name'"
            assert "owner" in instance_type.ami_lookup, f"{name} ami_lookup should have 'owner'"

    def test_linux_victims_use_linux_template(self):
        """Linux victim instances should use the Linux template."""
        linux_victims = ["ubuntu-22.04-victim", "ubuntu-24.04-victim", "amazon-linux-2023-victim"]

        for name in linux_victims:
            instance_type = get_instance_type(name)
            assert instance_type is not None
            assert instance_type.user_data_template == "victim_linux.sh.j2"

    def test_windows_victim_uses_windows_template(self):
        """Windows victim instance should use the Windows template."""
        windows = get_instance_type("windows-server-2022-victim")
        assert windows is not None
        assert windows.user_data_template == "victim_windows.ps1.j2"

    def test_kali_uses_kali_template(self):
        """Kali instance should use the Kali template."""
        kali = get_instance_type("kali-2024")
        assert kali is not None
        assert kali.user_data_template == "kali.sh.j2"
