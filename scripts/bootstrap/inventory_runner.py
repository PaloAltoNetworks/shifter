"""Inventory adapter for the existing dedicated GCP runner root and registration."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from installation.deployment_inventory_types import DeploymentRecord

from bootstrap_core import verified_command_environment
from gcp_runner import GcpRunnerTarget, get_gcp_runner_config, register_runner, verify_runners, wait_for_runner_ssh
from inventory_bootstrap import (
    TERRAFORM_NO_INPUT,
    assert_plan_unchanged,
    file_digest,
    invalid,
    private_command,
    private_json,
    write_private,
)
from inventory_plan import publish_plan

RUNNER_PLAN = "runner.plan"


def runner_tfvars(record: DeploymentRecord) -> dict[str, Any]:
    """Project inventory into the existing single-project runner inputs."""
    if record.gcp is None:
        raise invalid("runner bootstrap requires GCP inventory")
    return {
        "project_id": record.installation.settings["project_id"],
        "environment": record.installation.deployment.name,
        "name_prefix": record.gcp.name_prefix,
        "region": record.installation.settings["region"],
        "zone": record.gcp.runner_zone,
    }


def bootstrap_runner(
    record: DeploymentRecord, directory: Path, env: dict[str, str], *, apply: bool, plan_output: Path
) -> dict[str, Any]:
    """Inspect, preserve and optionally apply the runner plan before registration."""
    state = record.state["runner"]
    write_private(directory / "inventory.auto.tfvars.json", json.dumps(runner_tfvars(record), sort_keys=True))
    private_command(
        [
            "terraform",
            "init",
            TERRAFORM_NO_INPUT,
            "-lockfile=readonly",
            "-reconfigure",
            f"-backend-config=bucket={state.bucket}",
            f"-backend-config=prefix={state.prefix}",
        ],
        cwd=directory,
        env=env,
    )
    private_command(
        ["terraform", "plan", TERRAFORM_NO_INPUT, "-lock-timeout=120s", "-out=runner.plan"], cwd=directory, env=env
    )
    path = directory / RUNNER_PLAN
    digest = file_digest(path)
    plan = private_json(["terraform", "show", "-json", RUNNER_PLAN], cwd=directory, env=env)
    if not plan.get("resource_changes") or any(
        "delete" in item["change"]["actions"] for item in plan["resource_changes"]
    ):
        raise invalid("runner plan is empty or requires a separately reviewed replacement/migration")
    assert_plan_unchanged(path, digest)
    summary = publish_plan("runner", plan, path, plan_output)
    assert_plan_unchanged(path, digest)
    if not apply:
        return summary
    private_command(
        ["terraform", "apply", TERRAFORM_NO_INPUT, "-lock-timeout=120s", RUNNER_PLAN], cwd=directory, env=env
    )
    outputs = private_json(["terraform", "output", "-json"], cwd=directory, env=env)
    with verified_command_environment(env):
        register_inventory_runners(record, outputs)
    return summary


def register_inventory_runners(record: DeploymentRecord, outputs: dict[str, Any]) -> None:
    """Use the existing IAP/token handoff and skip already healthy registrations."""
    if record.gcp is None:
        raise invalid("runner bootstrap requires GCP inventory")
    owner, repository = record.execution.repository.split("/")
    config = get_gcp_runner_config(
        record.installation.deployment.name,
        record.installation.settings["project_id"],
        record.installation.settings["region"],
        record.gcp.runner_zone,
        owner,
        repository,
    )
    instances = outputs.get("runner_instance_names", {}).get("value", [])
    names = outputs.get("runner_names", {}).get("value", [])
    if not instances or len(instances) != len(names):
        raise invalid("runner Terraform outputs are incomplete")
    existing = verify_runners(config, names)
    from gcp_runner import _runner_online_with_label

    for instance, name in zip(instances, names, strict=True):
        if _runner_online_with_label(existing.get(name), config.labels):
            continue
        target = GcpRunnerTarget(
            instance,
            name,
            "https://github.com/" + record.execution.repository,
            record.installation.settings["project_id"],
            record.gcp.runner_zone,
            config.labels,
        )
        wait_for_runner_ssh(target)
        if register_runner(config, target) != 0:
            raise invalid("runner registration failed; resume bootstrap after correcting the reported boundary")
    from gcp_runner import _ONLINE_ATTEMPTS, _ONLINE_DELAY_SECONDS

    for attempt in range(_ONLINE_ATTEMPTS):
        verified = verify_runners(config, names)
        if all(_runner_online_with_label(verified.get(name), config.labels) for name in names):
            return
        if attempt + 1 < _ONLINE_ATTEMPTS:
            time.sleep(_ONLINE_DELAY_SECONDS)
    raise invalid("runner is not online with the required deployment label; retry readback")
