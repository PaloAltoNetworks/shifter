"""Common inventory bootstrap primitives and the GCP identity plan/apply flow."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess  # nosec B404 - allowlisted argv, no shell execution
from pathlib import Path
from typing import Any

from installation.deployment_identity_gcp import identity_tfvars, subject, trust_condition
from installation.deployment_inventory_types import DeploymentRecord
from installation.errors import ConfigIssue, InstallationConfigError

from bootstrap_core import _subprocess_env, _validate_argv

type JsonValue = dict[str, JsonValue] | list[JsonValue] | str | int | float | bool | None

TERRAFORM_NO_INPUT = "-input=false"
IDENTITY_PLAN = "identity.plan"

CHECKOV_VERSION = "3.2.534"
# Exact source commit for the product pin; this release is absent from PyPI.
CHECKOV_SOURCE = "git+https://github.com/bridgecrewio/checkov.git@73dac2f77484ea73f1740ea7bf91ffc67808b1b2"


def invalid(message: str) -> InstallationConfigError:
    """Build an operator-facing bootstrap error without private provider output."""
    return InstallationConfigError([ConfigIssue("bootstrap", message)])


def private_command(
    argv: list[str],
    *,
    stdin: str | None = None,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
) -> str:
    """Reuse the bootstrap process boundary with captured, sanitized failures.

    Unlike run_cmd this path never logs argv or child output; provider responses
    and secret-reference locators remain private. Input credentials use stdin
    or an intentionally constructed child environment, never argv.
    """
    _validate_argv(argv)
    stage = {
        "git": "inventory provenance",
        "gcloud": "cloud authority",
        "gh": "GitHub authority",
        "terraform": "Terraform",
        "uv": "policy scan",
    }.get(argv[0], "consumer")
    try:
        result = subprocess.run(  # nosec B603 - _validate_argv enforces the command allowlist
            argv,
            input=stdin,
            cwd=cwd,
            env=env if env is not None else _subprocess_env(),
            capture_output=True,
            text=True,
            check=False,
            timeout=1800,
        )
    except (OSError, subprocess.SubprocessError):
        raise invalid(f"{stage} command could not complete; check tool installation and credentials") from None
    if result.returncode:
        raise invalid(f"{stage} command failed (exit {result.returncode}); check permissions and prerequisites")
    return result.stdout


def private_json(
    argv: list[str],
    *,
    stdin: str | None = None,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
) -> JsonValue:
    """Decode provider JSON without exposing malformed responses or secret values."""
    try:
        return json.loads(private_command(argv, stdin=stdin, cwd=cwd, env=env))
    except (ValueError, TypeError):
        raise invalid("provider returned an invalid response; private output suppressed") from None


def authorize_record(record: DeploymentRecord, *, execution_repository: str, project_id: str) -> None:
    """Require explicit operator targets to match the validated deployment."""
    if (
        record.gcp is None
        or execution_repository != record.execution.repository
        or project_id != record.installation.settings["project_id"]
    ):
        raise invalid("explicit operator authorization does not match deployment bindings")


def write_private(path: Path, content: str | bytes) -> None:
    """Create a new operator-selected private file without following leaf symlinks."""
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "wb") as target:
        target.write(content.encode("utf-8") if isinstance(content, str) else content)


def write_identity_inputs(record: DeploymentRecord, directory: Path, *, project_number: str) -> None:
    """Write validated identity inputs using the verified project number."""
    if not project_number.isdecimal() or project_number.startswith("0"):
        raise invalid("invalid verified foundation project number")
    values = identity_tfvars(record)
    values["project_number"] = project_number
    write_private(directory / "inventory.auto.tfvars.json", json.dumps(values, sort_keys=True, indent=2) + "\n")


def validate_checkov_result(report: dict[str, Any]) -> None:
    """Require an unskipped WIF policy pass and no failed or malformed checks."""
    results = report.get("results", {})
    summary = report.get("summary", {})
    passed = results.get("passed_checks", [])
    if (
        summary.get("failed", 0)
        or summary.get("parsing_errors", 0)
        or results.get("failed_checks")
        or results.get("parsing_errors")
        or any(check.get("check_id") == "CKV_GCP_125" for check in results.get("skipped_checks", []))
        or len([check for check in passed if check.get("check_id") == "CKV_GCP_125"]) != 1
    ):
        raise invalid("Checkov must discover and pass the exact WIF policy without skips or parse errors")


def validate_environment(policy: dict[str, Any], branches: list[dict[str, Any]], expected: set[str]) -> None:
    """Compare exact Environment branch authorization with inventory."""
    if policy.get("deployment_branch_policy") != {"protected_branches": False, "custom_branch_policies": True}:
        raise invalid("execution Environment requires exact deployment branch policies")
    actual = {(branch.get("type"), branch.get("name")) for branch in branches}
    if actual != {("branch", branch) for branch in expected}:
        raise invalid("execution Environment branch authorization differs from inventory")


def file_digest(path: Path) -> str:
    """Hash saved plan bytes for later integrity checks."""
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def assert_plan_unchanged(path: Path, expected_digest: str) -> None:
    """Reject a saved plan whose bytes changed after inspection."""
    if file_digest(path) != expected_digest:
        raise invalid("saved Terraform plan changed after verification")


def expected_identity_policy(record: DeploymentRecord, project_number: str) -> dict[str, Any]:
    """Derive the exact single-project trust and service-account contract."""
    if record.gcp is None:
        raise invalid("GCP identity inputs are required")
    suffixes = {
        "build": "packer",
        "validate": "validate",
        "promote": "promote",
        "release_scan": "scan",
        "deploy": "deploy",
        "destroy": "destroy",
    }
    prefix = record.gcp.name_prefix.replace("-", "")
    return {
        "attribute_condition": trust_condition(record.execution),
        "project_id": record.installation.settings["project_id"],
        "project_number": project_number,
        "name_prefix": record.gcp.name_prefix,
        "purpose_subjects": {
            purpose: sorted({subject(record.execution, context.environment) for context in contexts})
            for purpose, contexts in record.execution.purposes.items()
        },
        "service_accounts": {
            purpose: f"projects/{record.installation.settings['project_id']}/serviceAccounts/"
            f"{prefix}-{suffixes[purpose]}@{record.installation.settings['project_id']}.iam.gserviceaccount.com"
            for purpose in record.execution.purposes
        },
    }


def verify_identity_plan(
    plan: dict[str, Any], record: DeploymentRecord, project_number: str, product_root: Path
) -> None:
    """Run the pinned product verifier against the resolved Terraform plan."""
    path = product_root / "scripts/check_tf_gcp_wif_trust/_resolved_plan.py"
    spec = importlib.util.spec_from_file_location("shifter_resolved_wif_policy", path)
    if spec is None or spec.loader is None:
        raise invalid("product WIF verifier is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if module.check_resolved_plan(plan, expected_identity_policy(record, project_number)):
        raise invalid("saved plan violates authorized identity, trust or migration boundaries")


def plan_identity(
    record: DeploymentRecord,
    *,
    directory: Path,
    product_root: Path,
    project_number: str,
    env: dict[str, str],
    plan_output: Path,
    apply: bool = False,
) -> dict[str, Any]:
    """Inspect and scan a saved plan; apply exactly those verified bytes."""
    state = record.state["identity"]
    write_identity_inputs(record, directory, project_number=project_number)
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
    private_command(["terraform", "validate", "-no-color"], cwd=directory, env=env)
    plan_path = directory / IDENTITY_PLAN
    private_command(
        ["terraform", "plan", TERRAFORM_NO_INPUT, "-lock-timeout=120s", "-out=identity.plan"], cwd=directory, env=env
    )
    digest = file_digest(plan_path)
    plan = private_json(["terraform", "show", "-json", IDENTITY_PLAN], cwd=directory, env=env)
    verify_identity_plan(plan, record, project_number, product_root)
    json_path = directory / "identity.plan.json"
    write_private(json_path, json.dumps(plan))
    checkov = [
        "uv",
        "tool",
        "run",
        "--from",
        CHECKOV_SOURCE,
        "python",
        str(product_root / "scripts/bootstrap/inventory_checkov.py"),
    ]
    report = private_json(
        [
            *checkov,
            "--file",
            str(json_path),
            "--framework",
            "terraform_plan",
            "--check",
            "CKV_GCP_118,CKV_GCP_125",
            "--output",
            "json",
            "--compact",
        ],
        cwd=directory,
        env=env,
    )
    validate_checkov_result(report)
    from inventory_plan import publish_plan

    assert_plan_unchanged(plan_path, digest)
    summary = publish_plan("identity", plan, plan_path, plan_output)
    assert_plan_unchanged(plan_path, digest)
    if apply:
        private_command(
            ["terraform", "apply", TERRAFORM_NO_INPUT, "-lock-timeout=120s", IDENTITY_PLAN], cwd=directory, env=env
        )
    return {
        "deployment": record.installation.deployment.name,
        "plan_sha256": digest,
        "plan": summary,
        "product_revision": record.product.revision,
        "applied": apply,
    }
