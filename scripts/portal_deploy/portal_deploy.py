#!/usr/bin/env python3
"""AWS portal deploy topology checks used by the platform workflow."""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


Runner = Callable[..., subprocess.CompletedProcess[str]]
SleepFn = Callable[[float], None]


class PortalDeployError(RuntimeError):
    """Raised when the portal deploy topology is inconsistent."""


@dataclass(frozen=True)
class TerraformTopology:
    enable_autoscaling: bool
    ec2_instance_id: str
    asg_name: str


@dataclass(frozen=True)
class ResolvedTopology:
    mode: str
    enable_autoscaling: bool
    instance_id: str = ""
    asg_name: str = ""

    @property
    def enable_autoscaling_output(self) -> str:
        return "true" if self.enable_autoscaling else "false"


def _run(
    command: list[str],
    *,
    cwd: str | None = None,
    runner: Runner = subprocess.run,
) -> subprocess.CompletedProcess[str]:
    return runner(
        command,
        cwd=cwd,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def _terraform_output_value(outputs: dict[str, object], name: str) -> object:
    entry = outputs.get(name)
    if not isinstance(entry, dict) or "value" not in entry:
        raise PortalDeployError(f"Terraform output {name!r} is required")
    return entry["value"]


def _terraform_output_value_optional(outputs: dict[str, object], name: str) -> object | None:
    entry = outputs.get(name)
    if not isinstance(entry, dict) or "value" not in entry:
        return None
    return entry["value"]


def parse_terraform_outputs(raw_json: str) -> TerraformTopology:
    try:
        outputs = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        raise PortalDeployError("terraform output -json returned invalid JSON") from exc
    if not isinstance(outputs, dict):
        raise PortalDeployError("terraform output -json must return an object")

    enable_autoscaling = _terraform_output_value(outputs, "enable_autoscaling")
    if not isinstance(enable_autoscaling, bool):
        raise PortalDeployError("Terraform output 'enable_autoscaling' must be a boolean")

    ec2_instance_id = _terraform_output_value(outputs, "ec2_instance_id")
    asg_name = _terraform_output_value(outputs, "asg_name")
    return TerraformTopology(
        enable_autoscaling=enable_autoscaling,
        ec2_instance_id=str(ec2_instance_id or ""),
        asg_name=str(asg_name or ""),
    )


def parse_text_ids(stdout: str) -> list[str]:
    return [item for item in stdout.split() if item and item != "None"]


def resolve_topology(
    topology: TerraformTopology,
    *,
    running_instance_ids: list[str],
    asg_exists: bool,
) -> ResolvedTopology:
    if topology.enable_autoscaling:
        if topology.ec2_instance_id:
            raise PortalDeployError(
                "Terraform reports ASG mode but ec2_instance_id is populated; "
                "refusing to choose a deploy path"
            )
        if not topology.asg_name:
            raise PortalDeployError(
                "Terraform reports ASG mode but asg_name is empty; refusing to deploy"
            )
        if not asg_exists:
            raise PortalDeployError(
                f"Terraform reports ASG mode but ASG {topology.asg_name!r} was not found"
            )
        return ResolvedTopology(
            mode="asg",
            enable_autoscaling=True,
            asg_name=topology.asg_name,
        )

    if topology.asg_name:
        raise PortalDeployError(
            "Terraform reports single-instance mode but asg_name is populated; "
            "refusing to choose a deploy path"
        )
    if not topology.ec2_instance_id:
        raise PortalDeployError(
            "Terraform reports single-instance mode but ec2_instance_id is empty; refusing to deploy"
        )
    if len(running_instance_ids) != 1:
        raise PortalDeployError(
            f"Single-instance deploy requires exactly one running instance tagged for "
            f"the portal; found {len(running_instance_ids)}"
        )
    observed_instance_id = running_instance_ids[0]
    if observed_instance_id != topology.ec2_instance_id:
        raise PortalDeployError(
            f"Tagged running instance {observed_instance_id!r} does not match Terraform "
            f"ec2_instance_id {topology.ec2_instance_id!r}"
        )
    return ResolvedTopology(
        mode="single",
        enable_autoscaling=False,
        instance_id=topology.ec2_instance_id,
    )


def _running_instance_ids(instance_tag: str, *, runner: Runner) -> list[str]:
    result = _run(
        [
            "aws",
            "ec2",
            "describe-instances",
            "--filters",
            f"Name=tag:Name,Values={instance_tag}",
            "Name=instance-state-name,Values=running",
            "--query",
            "Reservations[].Instances[].InstanceId",
            "--output",
            "text",
        ],
        runner=runner,
    )
    return parse_text_ids(result.stdout)


def _asg_exists(asg_name: str, *, runner: Runner) -> bool:
    result = _run(
        [
            "aws",
            "autoscaling",
            "describe-auto-scaling-groups",
            "--auto-scaling-group-names",
            asg_name,
            "--query",
            "length(AutoScalingGroups)",
            "--output",
            "text",
        ],
        runner=runner,
    )
    return result.stdout.strip() == "1"


def _write_github_output(output_path: str, topology: ResolvedTopology) -> None:
    if not output_path:
        return
    with Path(output_path).open("a", encoding="utf-8") as handle:
        handle.write(f"enable_autoscaling={topology.enable_autoscaling_output}\n")
        handle.write(f"instance_id={topology.instance_id}\n")
        handle.write(f"asg_name={topology.asg_name}\n")


def resolve_topology_from_commands(
    *,
    terraform_dir: str,
    backend_config: str,
    instance_tag: str,
    github_output: str,
    runner: Runner = subprocess.run,
) -> ResolvedTopology:
    _run(
        ["terraform", "init", f"-backend-config={backend_config}"],
        cwd=terraform_dir,
        runner=runner,
    )
    terraform_outputs = _run(
        ["terraform", "output", "-json"],
        cwd=terraform_dir,
        runner=runner,
    )
    topology = parse_terraform_outputs(terraform_outputs.stdout)
    running_instance_ids = (
        _running_instance_ids(instance_tag, runner=runner)
        if not topology.enable_autoscaling
        else []
    )
    asg_exists = (
        _asg_exists(topology.asg_name, runner=runner)
        if topology.enable_autoscaling
        else False
    )
    resolved = resolve_topology(
        topology,
        running_instance_ids=running_instance_ids,
        asg_exists=asg_exists,
    )
    _write_github_output(github_output, resolved)
    return resolved


def _in_service_asg_instance_ids(asg_name: str, *, runner: Runner) -> list[str]:
    result = _run(
        [
            "aws",
            "autoscaling",
            "describe-auto-scaling-groups",
            "--auto-scaling-group-names",
            asg_name,
            "--query",
            "AutoScalingGroups[0].Instances[?LifecycleState=='InService'].InstanceId",
            "--output",
            "text",
        ],
        runner=runner,
    )
    return parse_text_ids(result.stdout)


def _image_check_script(image_digest: str) -> str:
    quoted_digest = shlex.quote(image_digest)
    return "\n".join(
        [
            "set -euo pipefail",
            f"EXPECTED_IMAGE_DIGEST={quoted_digest}",
            # A just-in-service instance right after a refresh may still be
            # starting containers; wait (bounded) for the portal container to
            # exist before inspecting so verification does not race startup
            # (#1397). A genuinely-missing container still fails after the wait.
            "for _ in $(seq 1 45); do",
            "  docker inspect --format '{{.Config.Image}}' portal >/dev/null 2>&1 && break",
            "  sleep 2",
            "done",
            "IMAGE=$(docker inspect --format '{{.Config.Image}}' portal)",
            'case "$IMAGE" in',
            '  *"@${EXPECTED_IMAGE_DIGEST}") echo "portal image digest verified: ${IMAGE}" ;;',
            '  *) echo "Expected portal image digest ${EXPECTED_IMAGE_DIGEST}, found ${IMAGE}" >&2; exit 1 ;;',
            "esac",
        ]
    )


def verify_asg_image_digest(
    *,
    asg_name: str,
    image_digest: str,
    runner: Runner = subprocess.run,
    max_attempts: int = 5,
    retry_delay: float = 20.0,
    sleep: SleepFn = time.sleep,
) -> list[str]:
    if not asg_name:
        raise PortalDeployError("ASG image verification requires a non-empty ASG name")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", image_digest):
        raise PortalDeployError("ASG image verification requires a sha256 image digest")

    instance_ids = _in_service_asg_instance_ids(asg_name, runner=runner)
    if not instance_ids:
        raise PortalDeployError(f"No in-service instances found in ASG {asg_name!r}")

    parameters = json.dumps({"commands": [_image_check_script(image_digest)]})

    # Retry the whole SSM check: right after a refresh a just-in-service host
    # can still be finishing container/SSM-agent startup, so a single attempt
    # flakes with a non-Success status even though the digest is correct
    # (#1397). Only a persistent failure across all attempts fails the deploy.
    last_failure = ""
    for attempt in range(1, max_attempts + 1):
        send_command = _run(
            [
                "aws",
                "ssm",
                "send-command",
                "--document-name",
                "AWS-RunShellScript",
                "--instance-ids",
                *instance_ids,
                "--parameters",
                parameters,
                "--timeout-seconds",
                "120",
                "--query",
                "Command.CommandId",
                "--output",
                "text",
            ],
            runner=runner,
        )
        command_id = send_command.stdout.strip()
        if not command_id or command_id == "None":
            raise PortalDeployError("SSM did not return a command id for ASG image verification")

        failure = ""
        for instance_id in instance_ids:
            # The waiter exits non-zero when the command reaches a terminal
            # non-Success state; suppress that so we can read the real status
            # (and retry) rather than aborting the deploy on it.
            with contextlib.suppress(subprocess.CalledProcessError):
                _run(
                    [
                        "aws",
                        "ssm",
                        "wait",
                        "command-executed",
                        "--command-id",
                        command_id,
                        "--instance-id",
                        instance_id,
                    ],
                    runner=runner,
                )
            status = _run(
                [
                    "aws",
                    "ssm",
                    "get-command-invocation",
                    "--command-id",
                    command_id,
                    "--instance-id",
                    instance_id,
                    "--query",
                    "Status",
                    "--output",
                    "text",
                ],
                runner=runner,
            ).stdout.strip()
            if status != "Success":
                failure = f"{instance_id}: SSM status {status}"
                break

        if not failure:
            return instance_ids

        last_failure = failure
        if attempt < max_attempts:
            sleep(retry_delay)

    raise PortalDeployError(
        f"ASG image verification failed after {max_attempts} attempts ({last_failure})"
    )


_DEFAULT_WORKER_CONTAINERS = (
    "worker-cms",
    "worker-engine",
    "worker-mc",
    "worker-outbox-drainer",
    "worker-reconciler",
    "ctf-scheduler",
    "guacamole-bootstrap-prune",
)


def _worker_health_check_script(containers: tuple[str, ...]) -> str:
    names = " ".join(shlex.quote(c) for c in containers)
    return "\n".join(
        [
            "set -euo pipefail",
            f"CONTAINERS=({names})",
            'bad=""',
            'for c in "${CONTAINERS[@]}"; do',
            # Mirror the worker-health supervisor's read (modules/portal/ec2/
            # worker-health): missing container or unhealthy status counts as bad.
            "  st=$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' \"$c\" 2>/dev/null || echo missing)",
            '  [ "$st" = healthy ] || bad="$bad $c=$st"',
            "done",
            'if [ -n "$bad" ]; then echo "unhealthy workers:$bad" >&2; exit 1; fi',
            'echo "all workers healthy"',
        ]
    )


def verify_asg_worker_health(
    *,
    asg_name: str,
    runner: Runner = subprocess.run,
    containers: tuple[str, ...] = _DEFAULT_WORKER_CONTAINERS,
    max_attempts: int = 10,
    retry_delay: float = 30.0,
    sleep: SleepFn = time.sleep,
) -> list[str]:
    """Fail the deploy when worker/scheduler containers do not reach healthy.

    The post-deploy portal checks (image digest + ALB /health/) never inspect the
    async worker/scheduler containers, so crash-looping workers ship green
    (#1398). This SSM-checks each in-service instance's worker containers and, to
    tolerate the health-start-period and a single transient restart, retries with
    backoff; only a container that never reaches healthy across all attempts
    (crash loop / missing) fails the deploy.
    """
    if not asg_name:
        raise PortalDeployError("ASG worker health verification requires a non-empty ASG name")

    instance_ids = _in_service_asg_instance_ids(asg_name, runner=runner)
    if not instance_ids:
        raise PortalDeployError(f"No in-service instances found in ASG {asg_name!r}")

    parameters = json.dumps({"commands": [_worker_health_check_script(containers)]})
    last_failure = ""
    for attempt in range(1, max_attempts + 1):
        send_command = _run(
            [
                "aws",
                "ssm",
                "send-command",
                "--document-name",
                "AWS-RunShellScript",
                "--instance-ids",
                *instance_ids,
                "--parameters",
                parameters,
                "--timeout-seconds",
                "60",
                "--query",
                "Command.CommandId",
                "--output",
                "text",
            ],
            runner=runner,
        )
        command_id = send_command.stdout.strip()
        if not command_id or command_id == "None":
            raise PortalDeployError("SSM did not return a command id for ASG worker health verification")

        failure = ""
        for instance_id in instance_ids:
            with contextlib.suppress(subprocess.CalledProcessError):
                _run(
                    [
                        "aws",
                        "ssm",
                        "wait",
                        "command-executed",
                        "--command-id",
                        command_id,
                        "--instance-id",
                        instance_id,
                    ],
                    runner=runner,
                )
            status = _run(
                [
                    "aws",
                    "ssm",
                    "get-command-invocation",
                    "--command-id",
                    command_id,
                    "--instance-id",
                    instance_id,
                    "--query",
                    "Status",
                    "--output",
                    "text",
                ],
                runner=runner,
            ).stdout.strip()
            if status != "Success":
                failure = f"{instance_id}: SSM status {status}"
                break

        if not failure:
            return instance_ids

        last_failure = failure
        if attempt < max_attempts:
            sleep(retry_delay)

    raise PortalDeployError(
        f"ASG worker health verification failed after {max_attempts} attempts ({last_failure})"
    )


@dataclass(frozen=True)
class PostDeployVerification:
    domain_name: str
    portal_target_group_arn: str
    guacamole_target_group_arn: str = ""
    guacamole_ecs_cluster_name: str = ""
    guacd_service_name: str = ""
    guacamole_client_service_name: str = ""


def parse_post_deploy_outputs(raw_json: str) -> PostDeployVerification:
    try:
        outputs = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        raise PortalDeployError("terraform output -json returned invalid JSON") from exc
    if not isinstance(outputs, dict):
        raise PortalDeployError("terraform output -json must return an object")

    domain_name = str(_terraform_output_value(outputs, "domain_name") or "")
    portal_target_group_arn = str(
        _terraform_output_value(outputs, "portal_target_group_arn") or ""
    )
    if not domain_name:
        raise PortalDeployError("Terraform output 'domain_name' is required for post-deploy verification")
    if not portal_target_group_arn:
        raise PortalDeployError(
            "Terraform output 'portal_target_group_arn' is required for post-deploy verification"
        )

    return PostDeployVerification(
        domain_name=domain_name,
        portal_target_group_arn=portal_target_group_arn,
        guacamole_target_group_arn=str(
            _terraform_output_value_optional(outputs, "guacamole_target_group_arn") or ""
        ),
        guacamole_ecs_cluster_name=str(
            _terraform_output_value_optional(outputs, "guacamole_ecs_cluster_name") or ""
        ),
        guacd_service_name=str(_terraform_output_value_optional(outputs, "guacd_service_name") or ""),
        guacamole_client_service_name=str(
            _terraform_output_value_optional(outputs, "guacamole_client_service_name") or ""
        ),
    )


def _target_health_states(target_group_arn: str, *, runner: Runner) -> list[str]:
    result = _run(
        [
            "aws",
            "elbv2",
            "describe-target-health",
            "--target-group-arn",
            target_group_arn,
            "--output",
            "json",
        ],
        runner=runner,
    )
    payload = json.loads(result.stdout)
    descriptions = payload.get("TargetHealthDescriptions", [])
    if not isinstance(descriptions, list):
        raise PortalDeployError("Unexpected target health response shape")
    states: list[str] = []
    for item in descriptions:
        if not isinstance(item, dict):
            continue
        health = item.get("TargetHealth")
        if isinstance(health, dict) and isinstance(health.get("State"), str):
            states.append(health["State"])
    return states


def wait_target_group_healthy(
    target_group_arn: str,
    *,
    runner: Runner = subprocess.run,
    sleep_fn: SleepFn = time.sleep,
    timeout_seconds: int = 600,
    poll_interval_seconds: int = 15,
) -> None:
    if not target_group_arn:
        raise PortalDeployError("Target group health verification requires a target group ARN")

    deadline = time.monotonic() + timeout_seconds
    last_states: list[str] = []
    while True:
        last_states = _target_health_states(target_group_arn, runner=runner)
        if last_states and all(state == "healthy" for state in last_states):
            print(f"Target group healthy ({len(last_states)} target(s)): {target_group_arn}")
            return
        if time.monotonic() >= deadline:
            states_summary = ", ".join(last_states) if last_states else "no registered targets"
            raise PortalDeployError(
                f"Target group did not become healthy within {timeout_seconds}s "
                f"({states_summary})"
            )
        sleep_fn(poll_interval_seconds)


def verify_https_endpoint(
    url: str,
    *,
    expected_status_codes: set[int],
    runner: Runner = subprocess.run,
) -> None:
    result = runner(
        ["curl", "-sS", "-o", "/dev/null", "-w", "%{http_code}", url],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    status_text = result.stdout.strip()
    if result.returncode != 0 or not status_text.isdigit():
        raise PortalDeployError(
            f"HTTPS probe failed for {url} (exit={result.returncode}, code={status_text or 'n/a'})"
        )
    status_code = int(status_text)
    if status_code not in expected_status_codes:
        expected = ", ".join(str(code) for code in sorted(expected_status_codes))
        raise PortalDeployError(
            f"HTTPS probe for {url} returned {status_code}; expected one of [{expected}]"
        )
    print(f"HTTPS probe succeeded for {url} (HTTP {status_code})")


def _ecs_cluster_status(cluster_name: str, *, runner: Runner) -> str:
    result = _run(
        [
            "aws",
            "ecs",
            "describe-clusters",
            "--clusters",
            cluster_name,
            "--query",
            "clusters[0].status",
            "--output",
            "text",
        ],
        runner=runner,
    )
    return result.stdout.strip()


def _ecs_primary_rollout_state(
    cluster_name: str,
    service_name: str,
    *,
    runner: Runner,
) -> str:
    result = _run(
        [
            "aws",
            "ecs",
            "describe-services",
            "--cluster",
            cluster_name,
            "--services",
            service_name,
            "--query",
            "services[0].deployments[?status=='PRIMARY'] | [0].rolloutState",
            "--output",
            "text",
        ],
        runner=runner,
    )
    return result.stdout.strip() or "UNKNOWN"


def wait_ecs_services_stable(
    *,
    cluster_name: str,
    service_names: list[str],
    runner: Runner = subprocess.run,
    sleep_fn: SleepFn = time.sleep,
    timeout_seconds: int = 1200,
    poll_interval_seconds: int = 30,
) -> None:
    if not cluster_name or not service_names:
        raise PortalDeployError("ECS stability verification requires a cluster and service names")

    deadline = time.monotonic() + timeout_seconds
    while True:
        states = {
            service_name: _ecs_primary_rollout_state(cluster_name, service_name, runner=runner)
            for service_name in service_names
        }
        print("ECS rollout states: " + ", ".join(f"{name}={state}" for name, state in states.items()))
        if all(state == "COMPLETED" for state in states.values()):
            return
        if any(state == "FAILED" for state in states.values()):
            raise PortalDeployError(
                f"Guacamole ECS deployment failed on cluster {cluster_name}: {states}"
            )
        if time.monotonic() >= deadline:
            raise PortalDeployError(
                f"Guacamole ECS services did not stabilize within {timeout_seconds}s: {states}"
            )
        sleep_fn(poll_interval_seconds)


def verify_post_deploy(
    verification: PostDeployVerification,
    *,
    runner: Runner = subprocess.run,
    sleep_fn: SleepFn = time.sleep,
    portal_target_timeout_seconds: int = 600,
    guacamole_target_timeout_seconds: int = 600,
    ecs_timeout_seconds: int = 1200,
) -> None:
    wait_target_group_healthy(
        verification.portal_target_group_arn,
        runner=runner,
        sleep_fn=sleep_fn,
        timeout_seconds=portal_target_timeout_seconds,
    )
    verify_https_endpoint(
        f"https://{verification.domain_name}/health/",
        expected_status_codes={200},
        runner=runner,
    )

    if not (
        verification.guacamole_ecs_cluster_name
        and verification.guacamole_target_group_arn
        and verification.guacd_service_name
        and verification.guacamole_client_service_name
    ):
        print("Guacamole outputs are incomplete; skipping Guacamole post-deploy verification")
        return

    cluster_status = _ecs_cluster_status(
        verification.guacamole_ecs_cluster_name,
        runner=runner,
    )
    if cluster_status != "ACTIVE":
        raise PortalDeployError(
            "Guacamole cluster "
            f"{verification.guacamole_ecs_cluster_name!r} is {cluster_status!r}; "
            "post-deploy verification requires an ACTIVE cluster"
        )

    wait_ecs_services_stable(
        cluster_name=verification.guacamole_ecs_cluster_name,
        service_names=[
            verification.guacd_service_name,
            verification.guacamole_client_service_name,
        ],
        runner=runner,
        sleep_fn=sleep_fn,
        timeout_seconds=ecs_timeout_seconds,
    )
    wait_target_group_healthy(
        verification.guacamole_target_group_arn,
        runner=runner,
        sleep_fn=sleep_fn,
        timeout_seconds=guacamole_target_timeout_seconds,
    )
    verify_https_endpoint(
        f"https://{verification.domain_name}/guacamole/",
        expected_status_codes={200, 302},
        runner=runner,
    )


def _portal_manage_script(manage_args: list[str], env: dict[str, str] | None = None) -> str:
    if not manage_args:
        raise PortalDeployError("run-manage-on-portal requires at least one manage.py argument")
    quoted_args = " ".join(shlex.quote(arg) for arg in manage_args)
    # Forward extra env into the container via `docker exec -e KEY=VALUE`. The
    # in-container `/proc/1/environ` import below only carries the app runtime
    # env, so deploy-time values (e.g. SMOKE_TEST_USER_EMAIL) must be passed
    # explicitly (#1417). Keys here must not collide with the app runtime env.
    exec_flags = "".join(
        f" -e {shlex.quote(f'{key}={value}')}" for key, value in sorted((env or {}).items())
    )
    return "\n".join(
        [
            "set -euo pipefail",
            f"sudo docker exec{exec_flags} portal bash -c '",
            "set -euo pipefail",
            "while IFS= read -r -d \"\" kv; do export \"$kv\"; done < /proc/1/environ",
            "cd /app",
            f"python manage.py {quoted_args}",
            "'",
        ]
    )


def _wait_ssm_command(
    *,
    command_id: str,
    instance_id: str,
    timeout_seconds: int,
    runner: Runner = subprocess.run,
    sleep_fn: SleepFn = time.sleep,
    poll_interval_seconds: int = 15,
) -> dict[str, object]:
    deadline = time.monotonic() + timeout_seconds
    last_status = ""
    while time.monotonic() < deadline:
        invocation = _run(
            [
                "aws",
                "ssm",
                "get-command-invocation",
                "--command-id",
                command_id,
                "--instance-id",
                instance_id,
                "--output",
                "json",
            ],
            runner=runner,
        )
        payload = json.loads(invocation.stdout)
        status = str(payload.get("Status") or "")
        last_status = status
        if status in {"Success", "Cancelled", "TimedOut", "Failed", "Cancelling"}:
            return payload
        sleep_fn(poll_interval_seconds)
    raise PortalDeployError(
        f"SSM command {command_id} on {instance_id} did not reach a terminal state "
        f"within {timeout_seconds}s (last status={last_status or 'unknown'})"
    )


def run_manage_on_portal(
    *,
    instance_id: str = "",
    asg_name: str = "",
    manage_args: list[str],
    timeout_seconds: int = 7200,
    env: dict[str, str] | None = None,
    runner: Runner = subprocess.run,
) -> str:
    """Run ``python manage.py …`` inside the portal container via SSM."""
    if instance_id:
        instance_ids = [instance_id]
    elif asg_name:
        instance_ids = _in_service_asg_instance_ids(asg_name, runner=runner)
        if not instance_ids:
            raise PortalDeployError(f"No in-service instances found in ASG {asg_name!r}")
        instance_ids = instance_ids[:1]
    else:
        raise PortalDeployError("run-manage-on-portal requires instance_id or asg_name")

    parameters = json.dumps({"commands": [_portal_manage_script(manage_args, env)]})
    send_command = _run(
        [
            "aws",
            "ssm",
            "send-command",
            "--document-name",
            "AWS-RunShellScript",
            "--instance-ids",
            *instance_ids,
            "--parameters",
            parameters,
            "--timeout-seconds",
            str(timeout_seconds),
            "--query",
            "Command.CommandId",
            "--output",
            "text",
        ],
        runner=runner,
    )
    command_id = send_command.stdout.strip()
    if not command_id or command_id == "None":
        raise PortalDeployError("SSM did not return a command id for portal manage command")

    target_instance_id = instance_ids[0]
    payload = _wait_ssm_command(
        command_id=command_id,
        instance_id=target_instance_id,
        timeout_seconds=timeout_seconds,
        runner=runner,
    )
    status = str(payload.get("Status") or "")
    stdout = str(payload.get("StandardOutputContent") or "")
    stderr = str(payload.get("StandardErrorContent") or "")
    if status != "Success":
        raise PortalDeployError(
            f"Portal manage command failed on {target_instance_id}: status={status} stderr={stderr[-2000:]}"
        )
    return stdout


def verify_post_deploy_from_commands(
    *,
    terraform_dir: str,
    backend_config: str,
    runner: Runner = subprocess.run,
    sleep_fn: SleepFn = time.sleep,
) -> None:
    _run(
        ["terraform", "init", f"-backend-config={backend_config}"],
        cwd=terraform_dir,
        runner=runner,
    )
    terraform_outputs = _run(
        ["terraform", "output", "-json"],
        cwd=terraform_dir,
        runner=runner,
    )
    verification = parse_post_deploy_outputs(terraform_outputs.stdout)
    verify_post_deploy(verification, runner=runner, sleep_fn=sleep_fn)
    print("Post-deploy health verification succeeded")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    resolve_parser = subparsers.add_parser("resolve-topology")
    resolve_parser.add_argument("--terraform-dir", required=True)
    resolve_parser.add_argument("--backend-config", required=True)
    resolve_parser.add_argument("--instance-tag", required=True)
    resolve_parser.add_argument(
        "--github-output",
        default=os.environ.get("GITHUB_OUTPUT", ""),
    )

    verify_parser = subparsers.add_parser("verify-asg-image")
    verify_parser.add_argument("--asg-name", required=True)
    verify_parser.add_argument("--image-digest", required=True)

    verify_workers_parser = subparsers.add_parser("verify-asg-workers")
    verify_workers_parser.add_argument("--asg-name", required=True)

    verify_post_deploy_parser = subparsers.add_parser("verify-post-deploy")
    verify_post_deploy_parser.add_argument("--terraform-dir", required=True)
    verify_post_deploy_parser.add_argument("--backend-config", required=True)

    run_manage_parser = subparsers.add_parser("run-manage-on-portal")
    run_manage_parser.add_argument("--instance-id", default="")
    run_manage_parser.add_argument("--asg-name", default="")
    run_manage_parser.add_argument(
        "--env",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Extra environment variable to set in the container for the manage command (repeatable).",
    )
    run_manage_parser.add_argument(
        "manage_args",
        nargs=argparse.REMAINDER,
        help="Arguments passed to manage.py after the subcommand name",
    )
    run_manage_parser.add_argument("--timeout-seconds", type=int, default=7200)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.command == "resolve-topology":
            resolved = resolve_topology_from_commands(
                terraform_dir=args.terraform_dir,
                backend_config=args.backend_config,
                instance_tag=args.instance_tag,
                github_output=args.github_output,
            )
            print(f"Resolved portal deploy mode: {resolved.mode}")
        elif args.command == "verify-asg-image":
            instance_ids = verify_asg_image_digest(
                asg_name=args.asg_name,
                image_digest=args.image_digest,
            )
            print(f"Verified portal image digest on {len(instance_ids)} ASG instance(s)")
        elif args.command == "verify-asg-workers":
            instance_ids = verify_asg_worker_health(asg_name=args.asg_name)
            print(f"Verified worker container health on {len(instance_ids)} ASG instance(s)")
        elif args.command == "verify-post-deploy":
            verify_post_deploy_from_commands(
                terraform_dir=args.terraform_dir,
                backend_config=args.backend_config,
            )
        elif args.command == "run-manage-on-portal":
            manage_args = [arg for arg in args.manage_args if arg != "--"]
            env_overrides: dict[str, str] = {}
            for item in args.env:
                if "=" not in item:
                    raise PortalDeployError(f"--env expects KEY=VALUE, got {item!r}")
                key, value = item.split("=", 1)
                env_overrides[key] = value
            output = run_manage_on_portal(
                instance_id=args.instance_id,
                asg_name=args.asg_name,
                manage_args=manage_args,
                timeout_seconds=args.timeout_seconds,
                env=env_overrides,
            )
            if output.strip():
                print(output.rstrip())
        return 0
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        print(f"::error::Command failed: {exc.cmd[0]} {stderr}", file=sys.stderr)
        return 1
    except PortalDeployError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
