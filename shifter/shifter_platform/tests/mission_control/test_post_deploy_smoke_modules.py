from __future__ import annotations

import pytest

from cms.post_deploy_smoke.github_issue import SmokeIssuePayload, issue_body, issue_labels, issue_title
from cms.post_deploy_smoke.probe import probe_ssh_endpoint
from cms.post_deploy_smoke.smoke_runner import select_probe_target
from cms.post_deploy_smoke.variants import VARIANTS, parse_variant


def test_parse_variant_linux() -> None:
    variant = parse_variant("linux")
    assert variant.scenario_id == "smoke_linux"
    assert variant.primary_protocol == "ssh"
    assert variant.probe_target_role == "attacker"


def test_parse_variant_windows() -> None:
    variant = parse_variant("windows")
    assert variant.scenario_id == "smoke_windows"
    assert variant.primary_protocol == "rdp"
    assert variant.probe_target_role == "victim"


def test_variants_require_no_agent() -> None:
    # The smoke is platform-only: no variant carries an agent requirement.
    for variant in VARIANTS.values():
        assert not hasattr(variant, "required_agent_keys")


def test_issue_title_and_labels() -> None:
    payload = SmokeIssuePayload(
        environment="dev",
        provider="aws",
        variant="linux",
        commit_sha="abcdef1234567890",
        workflow_run_url="https://example.test/run/1",
        summary="probe failed",
        log_excerpt="line",
    )
    assert issue_title(payload).startswith("[smoke-test][dev][linux]")
    assert "probe failed" in issue_body(payload)
    assert issue_labels() == ["bug", "smoke-test"]


def test_probe_ssh_failure() -> None:
    with pytest.raises(RuntimeError, match="SSH endpoint unreachable"):
        probe_ssh_endpoint("10.0.0.1", 22, connect_fn=lambda _h, _p, _t: False)


def test_parse_variant_unknown() -> None:
    with pytest.raises(ValueError, match="unknown smoke variant"):
        parse_variant("bogus")


def test_issue_body_empty_fields() -> None:
    payload = SmokeIssuePayload(
        environment="dev",
        provider="aws",
        variant="linux",
        commit_sha="abcdef1234567890",
        workflow_run_url="https://example.test/run/1",
        summary="",
        log_excerpt="",
    )
    body = issue_body(payload)
    assert "_No summary provided._" in body
    assert "(empty)" in body


def test_select_probe_target_linux_ssh_attacker() -> None:
    instances = {"attacker": "attacker-1", "victim": "victim-1"}
    assert select_probe_target(VARIANTS["linux"], instances) == ("ssh", "attacker-1")


def test_select_probe_target_windows_rdp_victim() -> None:
    instances = {"attacker": "a", "victim": "w"}
    assert select_probe_target(VARIANTS["windows"], instances) == ("rdp", "w")


def test_select_probe_target_missing_role_raises() -> None:
    with pytest.raises(ValueError, match="expected a 'attacker' instance"):
        select_probe_target(VARIANTS["linux"], {"victim": "v"})
