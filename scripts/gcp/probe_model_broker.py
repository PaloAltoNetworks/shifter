#!/usr/bin/env python3
"""Read-only model-project onboarding and effective-IAM probes (not M10 proof)."""

from __future__ import annotations

import argparse
import json
import subprocess  # nosec B404 - required CLI adapter; calls below use argv without a shell.
import sys
from pathlib import Path

from installation.errors import InstallationConfigError
from installation.gcp_model_broker import GcpModelBrokerSettings
from installation.loader import load_root_config


def assert_permission_state(result: dict[str, object], *, allowed: bool) -> None:
    """Unknown/conditional/incomplete IAM results never count as a negative proof."""
    expected = "CAN_ACCESS" if allowed else "CANNOT_ACCESS"
    if result.get("overallAccessState") != expected:
        raise ValueError("effective IAM probe did not establish the required access state")


def _gcloud(*args: str) -> object:
    # Fixed gcloud readback commands; validated identifiers remain separate argv entries, never shell text.
    result = subprocess.run(  # nosec B603 B607 - fixed CLI from the operator/CI toolchain.
        ["gcloud", *args, "--format=json", "--quiet"], capture_output=True, text=True, check=False, timeout=120
    )
    if result.returncode:
        raise ValueError("cloud readback failed; onboarding remains unqualified")
    return json.loads(result.stdout)


def _permission(principal: str, resource: str, permission: str, *, allowed: bool) -> None:
    result = _gcloud(
        "policy-intelligence",
        "troubleshoot-policy",
        "iam",
        resource,
        "--principal-email",
        principal,
        "--permission",
        permission,
    )
    if not isinstance(result, dict):
        raise ValueError("invalid IAM readback")
    assert_permission_state(result, allowed=allowed)


def probe_projects(settings: GcpModelBrokerSettings, *, broker_gsa: str, deployment: str) -> list[dict[str, str]]:
    """Check billing/API/project ownership, keylessness and inherited IAM authority."""
    evidence = []
    for project, account in settings.model_projects.items():
        project_info = _gcloud("projects", "describe", project)
        if not isinstance(project_info, dict) or project_info.get("labels", {}).get("shifter-deployment") != deployment:
            raise ValueError("model project lacks the exact deployment ownership label")
        billing = _gcloud("billing", "projects", "describe", project)
        if not isinstance(billing, dict) or billing.get("billingEnabled") is not True:
            raise ValueError("model project billing is not enabled")
        services = _gcloud("services", "list", "--enabled", "--project", project)
        enabled = {item.get("config", {}).get("name") for item in services} if isinstance(services, list) else set()
        if not {"aiplatform.googleapis.com", "iamcredentials.googleapis.com"} <= enabled:
            raise ValueError("model project APIs are not enabled")
        identity = f"{account}@{project}.iam.gserviceaccount.com"
        account_info = _gcloud("iam", "service-accounts", "describe", identity, "--project", project)
        if not isinstance(account_info, dict) or account_info.get("disabled") is True:
            raise ValueError("model invocation identity is unavailable")
        keys = _gcloud(
            "iam",
            "service-accounts",
            "keys",
            "list",
            "--iam-account",
            identity,
            "--managed-by",
            "user",
            "--project",
            project,
        )
        if keys != []:
            raise ValueError("model invocation identity has user-managed keys")
        resource = f"//iam.googleapis.com/projects/{project}/serviceAccounts/{identity}"
        _permission(broker_gsa, resource, "iam.serviceAccounts.getAccessToken", allowed=True)
        for permission in (
            "iam.serviceAccounts.setIamPolicy",
            "iam.serviceAccountKeys.create",
            "iam.serviceAccounts.actAs",
        ):
            _permission(broker_gsa, resource, permission, allowed=False)
        project_resource = f"//cloudresourcemanager.googleapis.com/projects/{project}"
        _permission(identity, project_resource, "aiplatform.endpoints.predict", allowed=True)
        for permission in (
            "compute.instances.create",
            "secretmanager.versions.access",
            "storage.objects.get",
            "aiplatform.endpoints.create",
            "iam.serviceAccounts.create",
        ):
            _permission(identity, project_resource, permission, allowed=False)
        evidence.append({"project": project, "identity": identity, "onboarding": "passed"})
    return evidence


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--broker-gsa", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    config = load_root_config(args.config)
    settings = GcpModelBrokerSettings.model_validate(config.settings.get("model_broker", {}))
    if not settings.enabled:
        raise ValueError("broker is disabled; no onboarding success can be asserted")
    result = probe_projects(settings, broker_gsa=args.broker_gsa, deployment=config.deployment.name)
    Path(args.output).write_text(
        json.dumps({"schema_version": 1, "scope": "project-and-iam-onboarding", "projects": result}, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (InstallationConfigError, ValueError, OSError, subprocess.SubprocessError):
        sys.stderr.write("model broker configuration or cloud readback failed; no qualification asserted\n")
        raise SystemExit(1) from None
