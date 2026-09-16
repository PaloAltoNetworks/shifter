"""Participant-readiness contract tests for preconfigured machine hosts."""

import os
import shutil
import subprocess

import pytest

from orchestrators.setup_orchestrator import SetupOrchestrator
from plans.preconfigured_machine_host import (
    PARTICIPANT_READINESS_EXECUTABLE,
    PreconfiguredMachineHostPlan,
)


def _instance() -> dict[str, str]:
    return {
        "gcp_participant_container_name": "participant-desktop",
        "gcp_participant_username": "operator",
        "gcp_participant_readiness_contract": "participant-readiness/v1",
        "gcp_participant_readiness_manifest_sha256": "a" * 64,
    }


def test_plan_runs_image_canary_after_boot_liveness():
    plan = PreconfiguredMachineHostPlan()

    assert [step.name for step in plan.steps] == [
        "wait_for_preconfigured_machine_host",
        "verify_participant_readiness",
    ]
    canary = plan.steps[1]
    assert canary.is_verification is True
    assert PARTICIPANT_READINESS_EXECUTABLE in canary.script
    assert 'docker exec --user "${participant_user}"' in canary.script
    assert ">/dev/null 2>&1" in canary.script
    assert "participant-readiness: passed" in canary.script
    assert "participant-readiness: canary-failed" in canary.script


def test_plan_context_carries_only_closed_canary_inputs():
    context = PreconfiguredMachineHostPlan.get_context(_instance())

    assert context == {
        "participant_container_name": "participant-desktop",
        "participant_user": "operator",
        "participant_readiness_contract": "participant-readiness/v1",
        "participant_readiness_manifest_sha256": "a" * 64,
    }


_BASH = shutil.which("bash")


def _run_canary(tmp_path, *, docker_exit: int):
    docker = tmp_path / "docker"
    docker.write_text(
        '#!/bin/bash\nprintf "sensitive-guest-output\\n"\nprintf "%s\\n" "$@" > "$FAKE_DOCKER_ARGS"\n'
        'exit "$FAKE_DOCKER_EXIT"\n',
        encoding="utf-8",
    )
    docker.chmod(0o755)
    args_path = tmp_path / "docker.args"
    plan = PreconfiguredMachineHostPlan()
    script = SetupOrchestrator._render_script(plan.steps[1].script, plan.get_context(_instance()), plan.steps[1].name)
    env = {
        **os.environ,
        "PATH": f"{tmp_path}:{os.environ['PATH']}",
        "FAKE_DOCKER_ARGS": str(args_path),
        "FAKE_DOCKER_EXIT": str(docker_exit),
    }
    result = subprocess.run(  # noqa: S603 -- fixed bash path; test-controlled PATH contains the fake docker
        [_BASH, "-se"],
        input=script.encode(),
        capture_output=True,
        timeout=5,
        check=False,
        env=env,
    )
    return result, args_path


@pytest.mark.skipif(_BASH is None, reason="bash not available")
def test_canary_executes_as_participant_and_emits_only_bounded_success(tmp_path):
    result, args_path = _run_canary(tmp_path, docker_exit=0)

    assert result.returncode == 0
    assert result.stdout == b"participant-readiness: passed\n"
    assert result.stderr == b""
    assert args_path.read_text(encoding="utf-8").splitlines() == [
        "exec",
        "--user",
        "operator",
        "participant-desktop",
        PARTICIPANT_READINESS_EXECUTABLE,
        "--contract",
        "participant-readiness/v1",
        "--manifest-sha256",
        "a" * 64,
    ]


@pytest.mark.skipif(_BASH is None, reason="bash not available")
def test_canary_failure_is_fail_closed_and_does_not_leak_guest_output(tmp_path):
    result, _args_path = _run_canary(tmp_path, docker_exit=7)

    assert result.returncode == 1
    assert result.stdout == b""
    assert result.stderr == b"participant-readiness: canary-failed\n"
    assert b"sensitive-guest-output" not in result.stdout + result.stderr
