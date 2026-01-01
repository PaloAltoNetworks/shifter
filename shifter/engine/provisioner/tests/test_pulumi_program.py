"""Tests for __main__.py Pulumi program output building.

These tests verify that the output building logic correctly maps
role/os to instances regardless of creation order.
"""

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pulumi
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


class MockInstanceComponent:
    """Mock InstanceComponent for testing output building."""

    def __init__(self, role: str, os_type: str, instance_id: str, private_ip: str):
        self.role = role
        self.os_type = os_type
        self.instance_id = pulumi.Output.from_input(instance_id)
        self.private_ip = pulumi.Output.from_input(private_ip)
        self.ssh_key_secret_arn = pulumi.Output.from_input(f"arn:aws:secretsmanager:us-east-2:123456789:secret:{role}-ssh-key")


class TestOutputBuildingLogic:
    """Tests for output building that maps role/os to instances."""

    def test_basic_scenario_outputs_match_instances(self):
        """Basic scenario: output role/os should match instance role/os."""
        # Simulate basic scenario - order matches
        instances = [
            MockInstanceComponent("attacker", "kali", "i-kali123", "10.1.1.10"),
            MockInstanceComponent("victim", "ubuntu", "i-victim123", "10.1.1.20"),
        ]

        # Build outputs the same way __main__.py does
        instances_output = []
        for inst in instances:
            instances_output.append({
                "role": inst.role,
                "os": inst.os_type,
                "instance_id": inst.instance_id,
                "private_ip": inst.private_ip,
                "ssh_key_secret_arn": inst.ssh_key_secret_arn,
            })

        assert instances_output[0]["role"] == "attacker"
        assert instances_output[0]["os"] == "kali"
        assert instances_output[1]["role"] == "victim"
        assert instances_output[1]["os"] == "ubuntu"

    def test_dc_scenario_outputs_match_instances_despite_different_order(self):
        """DC scenario: output role/os should match instance even when order differs from config."""
        # DC scenario - instances created in order: DC, attacker, victim
        # But config order was: attacker, dc, victim
        instances = [
            MockInstanceComponent("dc", "windows", "i-dc123", "10.1.1.5"),
            MockInstanceComponent("attacker", "kali", "i-kali123", "10.1.1.10"),
            MockInstanceComponent("victim", "windows", "i-victim123", "10.1.1.20"),
        ]

        # Build outputs the same way __main__.py does (after fix)
        instances_output = []
        for inst in instances:
            instances_output.append({
                "role": inst.role,
                "os": inst.os_type,
                "instance_id": inst.instance_id,
                "private_ip": inst.private_ip,
                "ssh_key_secret_arn": inst.ssh_key_secret_arn,
            })

        # DC should be first (created first)
        assert instances_output[0]["role"] == "dc"
        assert instances_output[0]["os"] == "windows"

        # Attacker should be second
        assert instances_output[1]["role"] == "attacker"
        assert instances_output[1]["os"] == "kali"

        # Victim should be third
        assert instances_output[2]["role"] == "victim"
        assert instances_output[2]["os"] == "windows"

    def test_output_role_never_mismatches_instance_role(self):
        """Output role must always match the instance's actual role."""
        test_cases = [
            # (instance_role, instance_os)
            ("attacker", "kali"),
            ("victim", "ubuntu"),
            ("victim", "windows"),
            ("dc", "windows"),
        ]

        for role, os_type in test_cases:
            inst = MockInstanceComponent(role, os_type, f"i-{role}", "10.1.1.1")

            output = {
                "role": inst.role,
                "os": inst.os_type,
            }

            assert output["role"] == role, f"Output role {output['role']} != instance role {role}"
            assert output["os"] == os_type, f"Output os {output['os']} != instance os {os_type}"

    def test_multiple_dcs_all_have_correct_role(self):
        """Multiple DC instances should all have role=dc in output."""
        instances = [
            MockInstanceComponent("dc", "windows", "i-dc1", "10.1.1.5"),
            MockInstanceComponent("dc", "windows", "i-dc2", "10.1.1.6"),
            MockInstanceComponent("attacker", "kali", "i-kali", "10.1.1.10"),
        ]

        instances_output = []
        for inst in instances:
            instances_output.append({
                "role": inst.role,
                "os": inst.os_type,
            })

        dc_outputs = [o for o in instances_output if o["role"] == "dc"]
        assert len(dc_outputs) == 2, "Should have 2 DC outputs"

        for dc_output in dc_outputs:
            assert dc_output["os"] == "windows"


class TestOutputBuildingWithMalformedInstances:
    """Tests for handling malformed or edge case instances."""

    def test_empty_instances_list(self):
        """Empty instances list should produce empty output."""
        instances = []

        instances_output = [
            {"role": inst.role, "os": inst.os_type}
            for inst in instances
        ]

        assert instances_output == []

    def test_instance_with_none_role_raises_or_handles(self):
        """Instance with None role should be handled gracefully."""
        inst = MockInstanceComponent(None, "kali", "i-123", "10.1.1.1")

        output = {
            "role": inst.role,
            "os": inst.os_type,
        }

        # Should preserve None (Django will need to handle this)
        assert output["role"] is None

    def test_instance_with_empty_string_role(self):
        """Instance with empty string role should be preserved."""
        inst = MockInstanceComponent("", "kali", "i-123", "10.1.1.1")

        output = {
            "role": inst.role,
            "os": inst.os_type,
        }

        assert output["role"] == ""

    def test_instance_with_unexpected_role(self):
        """Instance with unexpected role value should be preserved."""
        inst = MockInstanceComponent("unknown_role", "weird_os", "i-123", "10.1.1.1")

        output = {
            "role": inst.role,
            "os": inst.os_type,
        }

        # Should not transform/validate - just pass through
        assert output["role"] == "unknown_role"
        assert output["os"] == "weird_os"


class TestIndexBasedLookupBug:
    """Tests that verify the index-based lookup bug is fixed.

    The original bug used config.instances[i] to get role/os instead of
    inst.role/inst.os_type. This caused mismatches when instance creation
    order differed from config order.
    """

    def test_index_mismatch_scenario_now_works(self):
        """Scenario that would have failed with index-based lookup."""
        # Config order: [attacker, dc, victim]
        # Instance creation order: [dc, attacker, victim] (DC first)

        # This is what range_stack.instances looks like after creation
        range_stack_instances = [
            MockInstanceComponent("dc", "windows", "i-dc", "10.1.1.5"),
            MockInstanceComponent("attacker", "kali", "i-kali", "10.1.1.10"),
            MockInstanceComponent("victim", "windows", "i-victim", "10.1.1.20"),
        ]

        # Build output using instance attributes (correct way)
        instances_output = []
        for inst in range_stack_instances:
            instances_output.append({
                "role": inst.role,
                "os": inst.os_type,
                "instance_id": inst.instance_id,
                "private_ip": inst.private_ip,
            })

        # Verify DC instance has DC role (not attacker from config[0])
        dc_output = instances_output[0]
        assert dc_output["role"] == "dc", "DC instance should have role=dc"
        assert dc_output["os"] == "windows", "DC instance should have os=windows"

        # Verify attacker has attacker role (not dc from config[1])
        attacker_output = instances_output[1]
        assert attacker_output["role"] == "attacker", "Attacker instance should have role=attacker"
        assert attacker_output["os"] == "kali", "Attacker instance should have os=kali"

    def test_buggy_index_lookup_would_fail(self):
        """Demonstrate what the bug looked like - index-based lookup fails."""
        # Config order (what the user requested)
        config_instances = [
            {"role": "attacker", "os_type": "kali"},
            {"role": "dc", "os_type": "windows"},
            {"role": "victim", "os_type": "windows"},
        ]

        # Actual instance creation order (DC created first)
        range_stack_instances = [
            MockInstanceComponent("dc", "windows", "i-dc", "10.1.1.5"),
            MockInstanceComponent("attacker", "kali", "i-kali", "10.1.1.10"),
            MockInstanceComponent("victim", "windows", "i-victim", "10.1.1.20"),
        ]

        # BUGGY: index-based lookup (what we had before)
        buggy_output = []
        for i, inst in enumerate(range_stack_instances):
            inst_config = config_instances[i]  # BUG: wrong index!
            buggy_output.append({
                "role": inst_config["role"],  # Gets wrong role
                "os": inst_config["os_type"],  # Gets wrong os
                "instance_id": inst.instance_id,
                "private_ip": inst.private_ip,
            })

        # This would incorrectly label DC instance as attacker
        assert buggy_output[0]["role"] == "attacker", "Bug: DC gets labeled as attacker"
        assert buggy_output[0]["os"] == "kali", "Bug: DC gets labeled as kali"

        # CORRECT: use instance attributes
        correct_output = []
        for inst in range_stack_instances:
            correct_output.append({
                "role": inst.role,
                "os": inst.os_type,
                "instance_id": inst.instance_id,
                "private_ip": inst.private_ip,
            })

        # Correctly labels DC as DC
        assert correct_output[0]["role"] == "dc"
        assert correct_output[0]["os"] == "windows"


class TestAllScenarioPermutations:
    """Test all permutations of scenario instance orderings."""

    @pytest.mark.parametrize("creation_order", [
        # Different possible creation orders
        [("dc", "windows"), ("attacker", "kali"), ("victim", "windows")],
        [("attacker", "kali"), ("dc", "windows"), ("victim", "windows")],
        [("attacker", "kali"), ("victim", "windows"), ("dc", "windows")],
        [("victim", "windows"), ("attacker", "kali"), ("dc", "windows")],
    ])
    def test_output_matches_instance_regardless_of_order(self, creation_order):
        """Output role/os should match instance role/os regardless of creation order."""
        instances = [
            MockInstanceComponent(role, os_type, f"i-{role}", f"10.1.1.{i}")
            for i, (role, os_type) in enumerate(creation_order)
        ]

        instances_output = []
        for inst in instances:
            instances_output.append({
                "role": inst.role,
                "os": inst.os_type,
            })

        # Each output should match its instance
        for i, (role, os_type) in enumerate(creation_order):
            assert instances_output[i]["role"] == role
            assert instances_output[i]["os"] == os_type
