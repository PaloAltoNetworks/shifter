"""Static invariants for AWS zero-egress range posture (#1171 / ADR-026)."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
RUNTIME_MAIN_TF = REPO_ROOT / "shifter/engine/provisioner/terraform/modules/range/main.tf"
RUNTIME_VARS_TF = REPO_ROOT / "shifter/engine/provisioner/terraform/modules/range/variables.tf"


def test_runtime_module_declares_range_egress_mode() -> None:
    content = RUNTIME_VARS_TF.read_text()
    assert 'variable "range_egress_mode"' in content
    assert '"allowlist"' in content
    assert '"none"' in content


def test_firewall_route_gated_on_allowlist_mode() -> None:
    content = RUNTIME_MAIN_TF.read_text()
    assert "resource \"aws_route\" \"firewall\"" in content
    assert "var.range_egress_mode == \"allowlist\"" in content
    assert "var.firewall_endpoint_id != \"\"" in content


def test_s3_endpoint_association_gated_on_allowlist_mode() -> None:
    content = RUNTIME_MAIN_TF.read_text()
    s3_block_start = content.index('resource "aws_vpc_endpoint_route_table_association" "s3"')
    s3_block = content[s3_block_start : content.index("}", s3_block_start) + 1]
    assert 'var.range_egress_mode == "allowlist"' in s3_block
    assert 'var.s3_endpoint_id != ""' in s3_block


def test_runtime_tfvars_keys_declared_in_module_variables() -> None:
    """terraform.tfvars.json keys must match module variable declarations (#1171)."""
    vars_content = RUNTIME_VARS_TF.read_text()
    required = ["range_egress_mode", "firewall_endpoint_id", "s3_endpoint_id"]
    for name in required:
        assert f'variable "{name}"' in vars_content
