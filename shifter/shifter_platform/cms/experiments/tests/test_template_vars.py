"""Tests for template variable parsing, validation, and resolution."""

import pytest
from cyberscript.template_vars import (
    build_instance_data,
    extract_variables,
    resolve_template,
    validate_template,
)


class TestExtractVariables:
    def test_extracts_single(self):
        result = extract_variables("Attack {{Workstation.ip}}")
        assert result == [("Workstation", "ip")]

    def test_extracts_multiple(self):
        result = extract_variables("From {{Attacker.ip}} to {{Workstation.ip}} via {{DC.ip}}")
        assert len(result) == 3

    def test_no_variables(self):
        result = extract_variables("No variables here")
        assert result == []

    def test_extracts_name_property(self):
        result = extract_variables("Target {{Workstation.name}}")
        assert result == [("Workstation", "name")]


class TestValidateTemplate:
    def test_valid(self):
        errors = validate_template(
            "Attack {{Workstation.ip}}",
            {"Workstation", "Attacker"},
        )
        assert errors == []

    def test_unknown_instance(self):
        errors = validate_template(
            "Attack {{NonExistent.ip}}",
            {"Workstation", "Attacker"},
        )
        assert len(errors) == 1
        assert "Unknown instance" in errors[0]

    def test_unknown_property(self):
        errors = validate_template(
            "{{Workstation.hostname}}",
            {"Workstation"},
        )
        assert len(errors) == 1
        assert "Unknown property" in errors[0]


class TestResolveTemplate:
    def test_resolves_ip(self):
        result = resolve_template(
            "Attack {{Workstation.ip}}",
            {"Workstation": {"ip": "10.1.1.5", "name": "Workstation"}},
        )
        assert result == "Attack 10.1.1.5"

    def test_resolves_multiple(self):
        result = resolve_template(
            "{{Attacker.ip}} -> {{Workstation.ip}}",
            {
                "Attacker": {"ip": "10.1.1.10", "name": "Attacker"},
                "Workstation": {"ip": "10.1.1.5", "name": "Workstation"},
            },
        )
        assert result == "10.1.1.10 -> 10.1.1.5"

    def test_unknown_instance_raises(self):
        with pytest.raises(ValueError, match="instance not found"):
            resolve_template(
                "{{Ghost.ip}}",
                {"Workstation": {"ip": "10.1.1.5"}},
            )

    def test_no_variables_passthrough(self):
        result = resolve_template("plain text", {})
        assert result == "plain text"


class TestBuildInstanceData:
    def test_builds_from_provisioned(self):
        provisioned = {
            "Workstation": {"private_ip": "10.1.1.5", "instance_id": "i-abc123"},
            "Attacker": {"private_ip": "10.1.1.10", "instance_id": "i-def456"},
        }
        result = build_instance_data(provisioned)
        assert result["Workstation"]["ip"] == "10.1.1.5"
        assert result["Workstation"]["name"] == "Workstation"
        assert result["Workstation"]["instance_id"] == "i-abc123"
        assert result["Attacker"]["ip"] == "10.1.1.10"
        assert result["Attacker"]["instance_id"] == "i-def456"

    def test_handles_missing_ip(self):
        result = build_instance_data({"Box": {}})
        assert result["Box"]["ip"] == ""
        assert result["Box"]["name"] == "Box"
        assert result["Box"]["instance_id"] == ""

    def test_instance_id_property_valid(self):
        errors = validate_template(
            "Instance {{Workstation.instance_id}}",
            {"Workstation"},
        )
        assert errors == []

    def test_resolves_instance_id(self):
        result = resolve_template(
            "SSH to {{Workstation.instance_id}}",
            {"Workstation": {"ip": "10.1.1.5", "name": "Workstation", "instance_id": "i-abc123"}},
        )
        assert result == "SSH to i-abc123"
