"""Explicit keyless operator authority and deployment-scoped bootstrap locking."""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from installation.deployment_inventory_types import DeploymentRecord

from inventory_bootstrap import invalid, private_command, private_json, write_private

GCP_INPUTS_REQUIRED = "GCP identity inputs are required"
JSON_FORMAT = "--format=json"
GCS_PREFIX = "gs://"


def operator_environment(operator: str) -> dict[str, str]:
    """Use one explicit gcloud token for gcloud, Terraform provider and backend.

    No ADC precedence, impersonation fallback, static key or persistent gcloud
    configuration change. Tokens remain solely in the private child environment.
    """
    env = {key: value for key, value in os.environ.items() if not key.startswith(("TF_", "GOOGLE_", "CLOUDSDK_AUTH_"))}
    for setting in ("auth/impersonate_service_account", "auth/credential_file_override", "auth/access_token_file"):
        value = private_command(["gcloud", "config", "get-value", setting], env=env).strip()
        if value not in {"", "(unset)"}:
            raise invalid("gcloud credential override conflicts with explicit operator authority")
    active = private_command(
        ["gcloud", "auth", "list", "--filter=status:ACTIVE", "--format=value(account)"], env=env
    ).strip()
    if not operator or active != operator:
        raise invalid("explicit operator does not match the active gcloud account")
    token = private_command(["gcloud", "auth", "print-access-token", "--account", operator], env=env).strip()
    if not token or any(character.isspace() for character in token):
        raise invalid("gcloud did not supply a usable operator credential")
    env.update(
        {
            "GOOGLE_OAUTH_ACCESS_TOKEN": token,
            "CLOUDSDK_AUTH_ACCESS_TOKEN": token,
            "TF_IN_AUTOMATION": "1",
            "TF_INPUT": "0",
        }
    )
    return env


def verify_projects(record: DeploymentRecord, env: dict[str, str]) -> str:
    """Verify the sole deployment project and return its numeric identity."""
    if record.gcp is None:
        raise invalid(GCP_INPUTS_REQUIRED)
    project = record.installation.settings["project_id"]
    detail = private_json(["gcloud", "projects", "describe", project, JSON_FORMAT], env=env)
    if detail.get("projectId") != project or detail.get("lifecycleState") != "ACTIVE":
        raise invalid("bootstrap requires the exact active deployment project")
    project_number = str(detail.get("projectNumber", ""))
    if not project_number.isdecimal() or project_number.startswith("0"):
        raise invalid("project response lacks a valid numeric identity")
    return project_number


def ensure_services(record: DeploymentRecord, env: dict[str, str], *, apply: bool) -> None:
    """Reconcile required foundation APIs under explicit bootstrap authority."""
    if record.gcp is None:
        raise invalid(GCP_INPUTS_REQUIRED)
    project = record.installation.settings["project_id"]
    services = {
        "iam.googleapis.com",
        "cloudresourcemanager.googleapis.com",
        "storage.googleapis.com",
        "iamcredentials.googleapis.com",
        "sts.googleapis.com",
        "compute.googleapis.com",
        "iap.googleapis.com",
        "oslogin.googleapis.com",
        "logging.googleapis.com",
        "monitoring.googleapis.com",
    }
    if apply:
        private_command(["gcloud", "services", "enable", *sorted(services), "--project", project], env=env)
    enabled = private_json(
        ["gcloud", "services", "list", "--enabled", "--project", project, "--format=json(config.name)"], env=env
    )
    if not services.issubset({item.get("config", {}).get("name") for item in enabled}):
        raise invalid("required cloud APIs are disabled; reconcile with bootstrap apply authority")


def ensure_state_buckets(record: DeploymentRecord, env: dict[str, str], *, apply: bool) -> None:
    """Reconcile state storage and verify project ownership and protections."""
    if record.gcp is None:
        raise invalid(GCP_INPUTS_REQUIRED)
    project = record.installation.settings["project_id"]
    for state in record.state.values():
        buckets = private_json(["gcloud", "storage", "buckets", "list", "--project", project, JSON_FORMAT], env=env)
        found = any(bucket.get("name") in {state.bucket, GCS_PREFIX + state.bucket} for bucket in buckets)
        if not found:
            if not apply:
                raise invalid("state bucket is absent; initial bootstrap requires apply authority")
            private_command(
                [
                    "gcloud",
                    "storage",
                    "buckets",
                    "create",
                    GCS_PREFIX + state.bucket,
                    "--project",
                    project,
                    "--location",
                    record.installation.settings["region"],
                    "--uniform-bucket-level-access",
                    "--public-access-prevention",
                ],
                env=env,
            )
        if apply:
            private_command(
                [
                    "gcloud",
                    "storage",
                    "buckets",
                    "update",
                    GCS_PREFIX + state.bucket,
                    "--versioning",
                    "--uniform-bucket-level-access",
                    "--public-access-prevention",
                ],
                env=env,
            )
        metadata = private_json(
            ["gcloud", "storage", "buckets", "describe", GCS_PREFIX + state.bucket, "--raw", JSON_FORMAT], env=env
        )
        project_metadata = private_json(["gcloud", "projects", "describe", project, JSON_FORMAT], env=env)
        _verify_bucket_metadata(metadata, state.bucket, str(project_metadata.get("projectNumber")))


def _verify_bucket_metadata(metadata: dict[str, Any], bucket: str, project_number: str) -> None:
    """Require exact project ownership and all state-bucket protection settings."""
    iam = metadata.get("iamConfiguration", {})
    if (
        str(metadata.get("projectNumber")) != project_number
        or metadata.get("name") != bucket
        or iam.get("uniformBucketLevelAccess", {}).get("enabled") is not True
        or iam.get("publicAccessPrevention") != "enforced"
        or metadata.get("versioning", {}).get("enabled") is not True
    ):
        raise invalid("state bucket ownership or security settings do not match; reconcile before planning")


@contextmanager
def bootstrap_lock(record: DeploymentRecord, directory: Path, env: dict[str, str]) -> Iterator[None]:
    """One remote writer across repositories, in addition to Terraform locking.

    No lease stealing: a process killed without cleanup leaves a lock for an
    operator to inspect. Failed acquisition never removes another writer's lock.
    """
    state = record.state["identity"]
    lock_url = f"gs://{state.bucket}/{state.prefix}/bootstrap.lock"
    path = directory / "bootstrap.lock"
    nonce = uuid.uuid4().hex
    write_private(path, json.dumps({"nonce": nonce, "deployment": record.installation.deployment.name}))
    private_command(["gcloud", "storage", "cp", "--if-generation-match=0", str(path), lock_url], env=env)
    generation = private_command(
        ["gcloud", "storage", "objects", "describe", lock_url, "--format=value(generation)"], env=env
    ).strip()
    if not generation.isdecimal():
        raise invalid("bootstrap lock generation could not be verified")
    try:
        yield
    finally:
        private_command(["gcloud", "storage", "rm", "--if-generation-match=" + generation, lock_url], env=env)
