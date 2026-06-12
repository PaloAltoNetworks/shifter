"""Portal readiness and instance replacement health-source invariants (#919)."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
EC2_MAIN_TF = REPO_ROOT / "platform" / "terraform" / "modules" / "portal" / "ec2" / "main.tf"


def test_portal_asg_uses_ec2_health_while_alb_target_group_handles_readiness() -> None:
    text = EC2_MAIN_TF.read_text(encoding="utf-8")

    assert 'health_check_type         = "EC2"' in text
    assert "target_group_arns         = [var.target_group_arn]" in text
    assert 'health_check_type         = "ELB"' not in text
