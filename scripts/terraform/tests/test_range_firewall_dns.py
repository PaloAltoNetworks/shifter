"""Static invariants for range VPC DNS egress hardening (#1172)."""

from __future__ import annotations

from pathlib import Path

from _hcl import resource_block

REPO_ROOT = Path(__file__).resolve().parents[3]
FIREWALL_TF = REPO_ROOT / "platform/terraform/modules/range/vpc/firewall.tf"
DNS_RESOLVER_TF = REPO_ROOT / "platform/terraform/modules/range/vpc/dns_resolver.tf"
VARIABLES_TF = REPO_ROOT / "platform/terraform/modules/range/vpc/variables.tf"


def test_firewall_tf_has_no_public_recursive_dns_allow_rules() -> None:
    content = FIREWALL_TF.read_text()
    assert "8.8.8.8" not in content, "firewall.tf must not allow DNS egress to public resolvers"
    assert "allow_dns" not in content, "public-recursive allow_dns rule group must be removed"


def test_dns_resolver_tf_defines_split_horizon_firewall() -> None:
    content = DNS_RESOLVER_TF.read_text()
    assert "aws_route53_resolver_firewall_rule_group" in content
    assert "aws_route53_resolver_firewall_config" in content
    assert "aws_route53_resolver_firewall_rule_group_association" in content

    # Check each rule's action against the domain list it actually references.
    # Asserting that "BLOCK" and block_unlisted appear somewhere in the file
    # passes even if the allowed and catch_all references were swapped, which
    # inverts the control: the scenario and bootstrap domains get blocked and
    # everything else is allowed, the opposite of #1172 (#1846).
    allow = resource_block(content, "aws_route53_resolver_firewall_rule", "allow_listed")
    assert '"ALLOW"' in allow
    assert "aws_route53_resolver_firewall_domain_list.allowed" in allow
    assert "aws_route53_resolver_firewall_domain_list.catch_all" not in allow

    block = resource_block(content, "aws_route53_resolver_firewall_rule", "block_unlisted")
    assert '"BLOCK"' in block
    assert "aws_route53_resolver_firewall_domain_list.catch_all" in block
    assert "aws_route53_resolver_firewall_domain_list.allowed" not in block
    assert "range_dns_allowed_domains" in content
    aws_service_suffix = "." + "amazonaws" + "." + "com"
    default_entry = f'"{aws_service_suffix}",'
    assert any(line.strip() == default_entry for line in VARIABLES_TF.read_text().splitlines()), (
        "range_dns_allowed_domains default must include AWS service suffix for bootstrap DNS"
    )
