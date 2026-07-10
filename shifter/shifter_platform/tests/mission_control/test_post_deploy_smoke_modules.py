from __future__ import annotations

import pytest

from cms.post_deploy_smoke.github_issue import SmokeIssuePayload, issue_body, issue_labels, issue_title
from cms.post_deploy_smoke.probe import probe_ssh_endpoint
from cms.post_deploy_smoke.smoke_runner import build_agents_by_os, select_probe_target
from cms.post_deploy_smoke.variants import VARIANTS, parse_variant


def test_parse_variant_linux() -> None:
    variant = parse_variant("linux")
    assert variant.scenario_id == "basic"


def test_build_agents_by_os_windows_requires_agent_ids() -> None:
    with pytest.raises(ValueError, match="SMOKE_WINDOWS_AGENT_ID"):
        build_agents_by_os(VARIANTS["windows"], env={})


def test_build_agents_by_os_linux_requires_agent_id() -> None:
    # basic has a from_agent victim, so the linux smoke must supply a linux agent.
    with pytest.raises(ValueError, match="SMOKE_LINUX_AGENT_ID"):
        build_agents_by_os(VARIANTS["linux"], env={})


def test_build_agents_by_os_linux_success() -> None:
    agents = build_agents_by_os(VARIANTS["linux"], env={"SMOKE_LINUX_AGENT_ID": "8"})
    assert agents == {"linux": 8}


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


def test_build_agents_by_os_windows_success() -> None:
    agents = build_agents_by_os(
        VARIANTS["windows"],
        env={"SMOKE_WINDOWS_AGENT_ID": "7", "SMOKE_LINUX_AGENT_ID": "8"},
    )
    assert agents == {"windows": 7, "linux": 8}


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


def test_select_probe_target_linux() -> None:
    assert select_probe_target(VARIANTS["linux"], attacker_uuid="attacker-1") == (
        "ssh",
        "attacker-1",
    )


def test_select_probe_target_windows() -> None:
    assert select_probe_target(
        VARIANTS["windows"],
        attacker_uuid="a",
        windows_uuid="w",
    ) == ("rdp", "w")
