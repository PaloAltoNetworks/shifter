"""AWS Terraform component deployment operations for the bootstrap CLI."""

import json
import os
import subprocess  # nosec B404
import sys
from pathlib import Path

import terraform_backend as tb
from bootstrap_core import (
    Colors,
    confirm,
    error,
    get_repo_root,
    header,
    info,
    run_cmd,
    success,
)

_COMPONENT_REQUIREMENT_REASON = {
    "core": "Core creates ECR repositories needed for container images",
    "range": "Range VPC is required for isolated attack/defense environments",
    "portal": "Portal is the main application infrastructure",
}


def _infra_state_bucket(*, bucket_name: str | None = None) -> str:
    """Resolve the Terraform state bucket from args or TF_INFRA_STATE_BUCKET."""
    if bucket_name:
        return bucket_name
    from_env = os.environ.get("TF_INFRA_STATE_BUCKET", "").strip()
    if from_env:
        return from_env
    error("Set TF_INFRA_STATE_BUCKET or pass the bootstrap bucket name before running Terraform")
    raise SystemExit(1)


def _instance_root(*, env: str, bucket: str) -> Path:
    """Return the per-instance config root (explicit env dir or ~/.shifter/<env>-<bucket>)."""
    explicit = tb.instance_dir_from_env()
    if explicit is not None:
        return explicit
    return Path.home() / ".shifter" / f"{env}-{bucket}"


def _component_stack_dir(env: str, component: str) -> str:
    """Map a deploy component name to its path under platform/terraform/environments/."""
    if component == "core":
        return f"environments/{env}"
    return f"environments/{env}/{component}"


def _capture_terraform_outputs() -> dict[str, object]:
    """Return parsed `terraform output -json`, or empty dict on failure.

    Used by the post-apply portal step; isolated from the deploy loop so
    the loop body stays at a reasonable nesting depth.
    """
    cmd = ["terraform", "output", "-json"]
    result = subprocess.run(  # nosec B603 B607  # NOSONAR
        cmd,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return {}
    return json.loads(result.stdout)


def _terraform_init_or_exit(
    component: str,
    dry_run: bool,
    *,
    backend_config_path: Path,
) -> None:
    """Run `terraform init -reconfigure -backend-config=<path>`."""
    info(f"Running terraform init for {component}...")
    init_result = run_cmd(
        ["terraform", "init", "-reconfigure", f"-backend-config={backend_config_path}"],
        dry_run=dry_run,
    )
    if not dry_run and init_result and init_result.returncode != 0:
        error(f"Terraform init failed for {component}")
        error(f"Check that {backend_config_path} exists and has the real bucket name")
        raise SystemExit(1)


def _terraform_plan_or_exit(component: str, dry_run: bool, *, var_files: list[Path] | None = None) -> None:
    """Run `terraform plan -out=tfplan`."""
    info("Running terraform plan...")
    plan_cmd = ["terraform", "plan", "-out=tfplan"]
    for var_file in var_files or []:
        plan_cmd.extend(["-var-file", str(var_file)])
    plan_result = run_cmd(plan_cmd, dry_run=dry_run)
    if not dry_run and plan_result and plan_result.returncode != 0:
        error(f"Terraform plan failed for {component}")
        error("Review errors above and fix before continuing")
        sys.exit(1)


def _terraform_apply_or_exit(component: str) -> dict[str, object]:
    """Show plan, confirm, apply, and capture outputs (for portal). Exits on failure."""
    print(f"\n{Colors.BOLD}Plan Summary:{Colors.END}")
    subprocess.run(["terraform", "show", "-no-color", "tfplan"], check=False)  # nosec B603 B607

    if not confirm("\nApply this plan?"):
        error(f"Terraform apply for {component} is required")
        error("All infrastructure components are mandatory for Shifter to function")
        sys.exit(1)

    info("Running terraform apply...")
    apply_result = run_cmd(["terraform", "apply", "tfplan"])
    if apply_result and apply_result.returncode != 0:
        error(f"Terraform apply failed for {component}")
        error("Infrastructure deployment incomplete")
        sys.exit(1)

    success(f"{component} deployed successfully")
    if component == "portal":
        return _capture_terraform_outputs()
    return {}


def _require_component_deploy(component: str, dry_run: bool) -> None:
    """Confirm a Terraform component deploy or exit when the operator declines."""
    if dry_run or confirm(f"Deploy {component}?"):
        return
    error(f"{component.title()} deployment is required")
    reason = _COMPONENT_REQUIREMENT_REASON.get(component)
    if reason:
        error(reason)
    raise SystemExit(1)


def _portal_remote_state_var_file(env: str, bucket: str) -> Path:
    """Return the portal remote-state tfvars path for one instance."""
    return _instance_root(env=env, bucket=bucket) / "terraform-vars" / env / "portal" / "remote-state.auto.tfvars"


def _ensure_portal_remote_state_var_file(env: str, bucket: str, portal_var_file: Path) -> None:
    """Create portal remote-state tfvars when missing before portal init/plan."""
    if portal_var_file.exists():
        return
    tb.write_portal_remote_state_tfvars(
        instance_dir=_instance_root(env=env, bucket=bucket),
        env=env,
        bucket=bucket,
        region=os.environ.get("AWS_REGION", "us-east-2"),
    )


def _deploy_terraform_component(
    env: str,
    component: str,
    dry_run: bool,
    *,
    bucket_name: str | None = None,
) -> dict[str, object]:
    """Run init/plan/apply for one Terraform component; return any captured outputs."""
    _require_component_deploy(component, dry_run)

    bucket = _infra_state_bucket(bucket_name=bucket_name)
    instance_dir = _instance_root(env=env, bucket=bucket)
    backend_dir = tb.resolve_instance_backend_dir(env=env, bucket=bucket, instance_dir=instance_dir)
    backend_config_path = tb.backend_config_for_stack(
        backend_dir,
        _component_stack_dir(env, component),
        env,
    )
    portal_var_file = _portal_remote_state_var_file(env, bucket)
    if component == "portal":
        _ensure_portal_remote_state_var_file(env, bucket, portal_var_file)

    base_path = get_repo_root() / "platform" / "terraform" / "environments" / env
    tf_dir = base_path if component == "core" else base_path / component
    if not tf_dir.exists():
        error(f"Directory not found: {tf_dir}")
        return {}

    original_dir = os.getcwd()
    os.chdir(tf_dir)
    try:
        _terraform_init_or_exit(
            component,
            dry_run,
            backend_config_path=backend_config_path,
        )
        var_files = [portal_var_file] if component == "portal" and portal_var_file.exists() else None
        _terraform_plan_or_exit(component, dry_run, var_files=var_files)
        if dry_run:
            return {}
        return _terraform_apply_or_exit(component)
    finally:
        os.chdir(original_dir)


def terraform_deploy(
    env: str,
    profile: str,
    dry_run: bool = False,
    *,
    bucket_name: str | None = None,
) -> dict[str, object]:
    """Deploy all Terraform components in order."""
    header(f"Deploying {env.upper()} Infrastructure")

    # Set AWS_PROFILE for Terraform (only affects this process and its children)
    os.environ["AWS_PROFILE"] = profile

    components = [
        ("core", "ECR repositories"),
        ("range", "Range VPC + Pulumi state"),
        ("portal", "Portal infrastructure (VPC, RDS, EC2, ALB, Cognito)"),
    ]

    outputs: dict[str, object] = {}
    for i, (component, description) in enumerate(components, 1):
        header(f"Step {i}/{len(components)}: {description}")
        info(f"Component: {component}")
        captured = _deploy_terraform_component(env, component, dry_run, bucket_name=bucket_name)
        if captured:
            outputs = captured
    return outputs
