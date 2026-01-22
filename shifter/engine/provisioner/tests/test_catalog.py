"""Instance catalog tests for Shifter Engine."""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from catalog.instances import (
    INSTANCE_CATALOG,
    InstanceType,
    get_attacker_types,
    get_available_instance_types,
    get_dc_types,
    get_instance_type,
    get_victim_types,
)


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
        assert get_instance_type("nonexistent-type") is None

    def test_get_instance_type_case_sensitive(self):
        """get_instance_type is case-sensitive."""
        assert get_instance_type("KALI-2024") is None
        assert get_instance_type("Kali-2024") is None

    def test_get_available_instance_types(self):
        """get_available_instance_types returns all catalog keys."""
        result = get_available_instance_types()
        assert isinstance(result, list)
        assert len(result) >= 5
        assert "kali-2024" in result

    def test_get_attacker_types_only_attackers(self):
        """get_attacker_types returns only attacker role instances."""
        result = get_attacker_types()
        assert len(result) >= 1
        for name in result:
            assert get_instance_type(name).role == "attacker"

    def test_get_victim_types_only_victims(self):
        """get_victim_types returns only victim role instances."""
        result = get_victim_types()
        assert len(result) >= 4
        for name in result:
            assert get_instance_type(name).role == "victim"

    def test_get_dc_types_only_dcs(self):
        """get_dc_types returns only dc role instances."""
        result = get_dc_types()
        for name in result:
            assert get_instance_type(name).role == "dc"


class TestInstanceTypeDataclass:
    """Tests for InstanceType dataclass behavior."""

    def test_instance_type_reads_from_env_dynamically(self, monkeypatch):
        """default_instance_type reads from environment at access time."""
        monkeypatch.setenv("TEST_INSTANCE_TYPE", "t3.small")

        it = InstanceType(
            name="test-env",
            role="victim",
            _instance_type_getter=lambda: os.environ["TEST_INSTANCE_TYPE"],
            user_data_template="test.sh.j2",
            description="Test instance",
        )
        assert it.default_instance_type == "t3.small"

        monkeypatch.setenv("TEST_INSTANCE_TYPE", "t3.xlarge")
        assert it.default_instance_type == "t3.xlarge"


class TestCatalogConsistency:
    """Tests for catalog consistency."""

    def test_all_templates_exist(self):
        """All referenced user_data_templates exist on disk."""
        templates_dir = Path(__file__).parent.parent / "templates"

        for name, instance_type in INSTANCE_CATALOG.items():
            template_path = templates_dir / instance_type.user_data_template
            assert template_path.exists(), f"Template missing for {name}"

    def test_all_types_covered_by_role_helpers(self):
        """Attacker + victim + dc types should equal all available types."""
        all_types = set(get_available_instance_types())
        combined = set(get_attacker_types()) | set(get_victim_types()) | set(get_dc_types())
        assert combined == all_types

    def test_roles_are_disjoint(self):
        """No instance should belong to multiple role categories."""
        attackers = set(get_attacker_types())
        victims = set(get_victim_types())
        dcs = set(get_dc_types())

        assert len(attackers & victims) == 0
        assert len(attackers & dcs) == 0
        assert len(victims & dcs) == 0
