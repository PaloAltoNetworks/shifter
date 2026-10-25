"""Bootstrap the backend and independently owned GCP CI identity root."""

import json
import re
import tempfile
from pathlib import Path

from bootstrap_core import confirm, gcloud_resource_exists, get_repo_root, run_cmd

# gcp-dev-destroy.yml rejects every other dispatch ref before auth; the
# cicd-oidc purpose_contexts validation enforces the same set.
DESTROY_PROTECTED_REFS = ("refs/heads/dev", "refs/heads/main")

# GCP naming rules. The bucket rule matches the cicd-oidc
# terraform_state_bucket_name validation. A value that starts with "-" can
# not match, so gcloud can not parse an input as a flag.
_PROJECT_ID_RE = re.compile(r"[a-z][a-z0-9-]{4,28}[a-z0-9]")
_BUCKET_NAME_RE = re.compile(r"[a-z0-9][a-z0-9-]{1,61}[a-z0-9]")
_REGION_RE = re.compile(r"[a-z]+-[a-z]+\d+", re.ASCII)


def _require_protected_destroy_refs(purpose_contexts: dict[str, list[dict[str, str]]]) -> None:
    """Reject destroy tuples the destroy workflow's protected-ref guard can never satisfy."""
    for context in purpose_contexts.get("destroy", []):
        ref = context.get("ref")
        if ref not in DESTROY_PROTECTED_REFS or not str(context.get("workflow_ref", "")).endswith(f"@{ref}"):
            raise ValueError(
                f"Destroy purpose tuple must bind {' or '.join(DESTROY_PROTECTED_REFS)} "
                f"(gcp-dev-destroy.yml rejects other dispatch refs); got ref={ref!r}"
            )


def _require_gcp_name(field: str, value: object, pattern: re.Pattern[str]) -> str:
    """Return a foundation input value only when it is a valid GCP resource name."""
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise ValueError(f"Foundation input {field} is not a valid GCP name: {value!r}")
    return value


def bootstrap_gcp_foundation(inputs_path: str, *, dry_run: bool = False) -> None:
    """Apply explicit foundation inputs before runners, image bakes, or platform."""
    path = Path(inputs_path).resolve(strict=True)
    inputs = json.loads(path.read_text())
    required = {
        "project_id",
        "project_number",
        "environment",
        "name_prefix",
        "github_org",
        "github_repo",
        "github_repository_id",
        "github_owner_id",
        "purpose_contexts",
        "terraform_state_bucket_name",
        "release_evidence_bucket_name",
    }
    missing = sorted(required - inputs.keys())
    if missing:
        raise ValueError("Missing foundation inputs: " + ", ".join(missing))
    _require_protected_destroy_refs(inputs["purpose_contexts"])
    project = _require_gcp_name("project_id", inputs["project_id"], _PROJECT_ID_RE)
    bucket = _require_gcp_name("terraform_state_bucket_name", inputs["terraform_state_bucket_name"], _BUCKET_NAME_RE)
    region = _require_gcp_name("region", inputs.get("region", "us-central1"), _REGION_RE)
    root = get_repo_root() / "platform/terraform/gcp/global/cicd-oidc"
    tf = ["terraform", f"-chdir={root}"]
    if not dry_run:
        result = run_cmd(["gcloud", "projects", "describe", project, "--format=value(projectNumber)"], capture=True)
        if result.stdout.strip() != str(inputs["project_number"]):
            raise ValueError("Foundation project number does not match the selected project")
        result = run_cmd(["gh", "api", f"repos/{inputs['github_org']}/{inputs['github_repo']}"], capture=True)
        repository = json.loads(result.stdout)
        if (str(repository["id"]), str(repository["owner"]["id"])) != (
            str(inputs["github_repository_id"]),
            str(inputs["github_owner_id"]),
        ):
            raise ValueError("Foundation repository IDs do not match GitHub")
        if not confirm(f"Bootstrap foundation in {project}? Evidence retention locks for 90 days."):
            raise SystemExit("Foundation bootstrap cancelled")
    run_cmd(
        [
            "gcloud",
            "services",
            "enable",
            "iam.googleapis.com",
            "iamcredentials.googleapis.com",
            "sts.googleapis.com",
            "compute.googleapis.com",
            "iap.googleapis.com",
            "cloudbuild.googleapis.com",
            "artifactregistry.googleapis.com",
            "storage.googleapis.com",
            "--project",
            project,
        ],
        dry_run=dry_run,
    )
    if dry_run or not gcloud_resource_exists(["gcloud", "storage", "buckets", "describe", f"gs://{bucket}"]):
        run_cmd(
            [
                "gcloud",
                "storage",
                "buckets",
                "create",
                f"gs://{bucket}",
                "--project",
                project,
                "--location",
                region,
                "--uniform-bucket-level-access",
                "--public-access-prevention",
            ],
            dry_run=dry_run,
        )
    run_cmd(["gcloud", "storage", "buckets", "update", f"gs://{bucket}", "--versioning"], dry_run=dry_run)
    run_cmd(
        [*tf, "init", "-reconfigure", f"-backend-config=bucket={bucket}", "-backend-config=prefix=cicd-oidc"],
        dry_run=dry_run,
    )
    with tempfile.TemporaryDirectory(prefix="shifter-gcp-foundation-") as staging:
        plan = str(Path(staging) / "foundation.tfplan")
        run_cmd([*tf, "plan", "-input=false", f"-var-file={path}", f"-out={plan}"], dry_run=dry_run)
        run_cmd([*tf, "apply", "-input=false", plan], dry_run=dry_run)
