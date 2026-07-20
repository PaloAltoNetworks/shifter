"""Shared, fail-safe preflight for Shifter bootstrap/deploy prerequisites.

This module is the single source of truth for the question "is this environment
ready to bootstrap or deploy?". It is executed from two places so local and CI
can never diverge on what a fresh standup requires:

- the local operator CLI (``scripts/bootstrap/cli.py`` -- ``deploy.py preflight``
  and the gate that runs at the start of every deploy command), and
- the CI reusable deploy workflows (``.github/workflows/_*.yml``), which run
  ``python -m preflight`` before any Terraform apply.

The checks are declarative and the evaluators are pure and injectable
(``env`` / ``repo_root`` / ``tool_exists``) so tests assert observable behavior
without patching first-party seams (ADR-019). The operator-facing prerequisite
list is documented in ``docs/dev/deploy-secrets.md`` and the setup guide; the
``test_spec_matches_deploy_secrets_doc`` parity test keeps them in step.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from bootstrap_core import (
    confirm,
    error,
    get_repo_root,
    header,
    info,
    success,
    validate_gcp_control_plane_security_inputs,
    warn,
)

# Explicit, audited opt-out for the first Identity Platform operator bootstrap.
# When truthy, a missing operator credential is a loud WARN instead of a hard
# FAIL, so "no operator" is always a deliberate, logged choice -- never an
# empty-secret accident (contrast the old silent ``if: secrets != ''`` skip).
SKIP_OPERATOR_ENV = "SHIFTER_SKIP_OPERATOR_BOOTSTRAP"

_AWS_ENVIRONMENTS = ("dev", "proof", "prod")
_AWS_ENV_SUFFIX = {"dev": "DEV", "proof": "PROOF", "prod": "PROD"}
_TRUTHY = {"1", "true", "yes", "on"}


class Cloud(StrEnum):
    """Deployment cloud a preflight run targets."""

    AWS = "aws"
    GCP = "gcp"


class Mode(StrEnum):
    """Execution context: an operator laptop or a CI runner."""

    LOCAL = "local"
    CI = "ci"


class Status(StrEnum):
    """Outcome of a single check."""

    OK = "ok"
    WARN = "warn"
    FAIL = "fail"
    SKIP = "skip"


@dataclass(frozen=True)
class SecretCheck:
    """A deployment input sourced from an env var (a GitHub secret in CI)."""

    env_var: str
    label: str
    required: bool
    remediation: str
    opt_out_env: str = ""


@dataclass(frozen=True)
class ToolCheck:
    """A CLI tool that must be on ``PATH`` for a local deploy."""

    name: str
    install_url: str


@dataclass(frozen=True)
class CheckResult:
    """The evaluated outcome of one check."""

    name: str
    status: Status
    message: str


@dataclass
class PreflightReport:
    """The full set of evaluated checks for one preflight run."""

    cloud: str
    mode: str
    environment: str
    results: list[CheckResult]

    @property
    def failures(self) -> list[CheckResult]:
        """Return only the checks that failed."""
        return [result for result in self.results if result.status is Status.FAIL]

    @property
    def ok(self) -> bool:
        """Return True when no required check failed."""
        return not self.failures

    def render(self) -> str:
        """Render a plain-text report grouped by status for logs and tests."""
        symbol = {Status.OK: "[ ok ]", Status.WARN: "[warn]", Status.FAIL: "[FAIL]", Status.SKIP: "[skip]"}
        lines = [f"Deploy preflight: cloud={self.cloud} env={self.environment} mode={self.mode}"]
        for result in self.results:
            lines.append(f"  {symbol[result.status]} {result.name}: {result.message}")
        verdict = "PASS" if self.ok else f"FAIL ({len(self.failures)} blocking)"
        lines.append(f"Result: {verdict}")
        return "\n".join(lines)


# --- Secret name resolution (mirrors the reusable-workflow selection) ---------
# Role and state-bucket secrets are unsuffixed for prod (AWS_ROLE_ARN,
# TF_INFRA_STATE_BUCKET) and env-suffixed otherwise; the tfvars/config payload
# secrets are env-suffixed for every environment including prod (TF_VARS_PROD_*).


def _aws_role_secret(environment: str) -> str:
    """Return the IAM-role secret name for an AWS environment."""
    return "AWS_ROLE_ARN" if environment == "prod" else f"AWS_ROLE_ARN_{_AWS_ENV_SUFFIX[environment]}"


def _aws_state_bucket_secret(environment: str) -> str:
    """Return the Terraform state-bucket secret name for an AWS environment."""
    if environment == "prod":
        return "TF_INFRA_STATE_BUCKET"
    return f"TF_INFRA_STATE_BUCKET_{_AWS_ENV_SUFFIX[environment]}"


def _tf_vars_secret(environment: str, stack: str) -> str:
    """Return the ``TF_VARS_<ENV>_<STACK>`` payload secret name."""
    return f"TF_VARS_{_AWS_ENV_SUFFIX[environment]}_{stack.upper()}"


def _shifter_config_secret(environment: str) -> str:
    """Return the ``SHIFTER_CONFIG_<ENV>_RANGE`` payload secret name."""
    return f"SHIFTER_CONFIG_{_AWS_ENV_SUFFIX[environment]}_RANGE"


# --- Declarative check spec ---------------------------------------------------

_AWS_COMPONENT_STACKS = {"core": "CORE", "range": "RANGE", "portal": "PORTAL"}
_DOCS = "docs/dev/deploy-secrets.md"


def _aws_secret_checks(environment: str, component: str | None) -> list[SecretCheck]:
    """Build the AWS secret checks for an environment and optional component."""
    checks = [
        SecretCheck(
            _aws_role_secret(environment),
            "AWS deploy role",
            required=True,
            remediation=f"Set the {_aws_role_secret(environment)} secret (see {_DOCS}).",
        ),
        SecretCheck(
            _aws_state_bucket_secret(environment),
            "Terraform state bucket",
            required=True,
            remediation=f"Set the {_aws_state_bucket_secret(environment)} secret (see {_DOCS}).",
        ),
    ]
    components = [component] if component else list(_AWS_COMPONENT_STACKS)
    for name in components:
        stack = _AWS_COMPONENT_STACKS.get(name)
        if stack is None:
            continue
        checks.append(
            SecretCheck(
                _tf_vars_secret(environment, stack),
                f"{name} tfvars payload",
                required=True,
                remediation=f"Set the {_tf_vars_secret(environment, stack)} secret (see {_DOCS}).",
            )
        )
        if name == "range":
            checks.append(
                SecretCheck(
                    _shifter_config_secret(environment),
                    "range shifter.yaml payload",
                    required=True,
                    remediation=f"Set the {_shifter_config_secret(environment)} secret (see {_DOCS}).",
                )
            )
    return checks


def _gcp_secret_checks() -> list[SecretCheck]:
    """Build the GCP (gcp-dev) secret checks."""
    return [
        SecretCheck("GCP_PROJECT_ID", "GCP project", True, f"Set GCP_PROJECT_ID (see {_DOCS})."),
        SecretCheck("GCP_PUBLIC_HOSTNAME", "Public hostname", True, f"Set GCP_PUBLIC_HOSTNAME (see {_DOCS})."),
        SecretCheck(
            "GCP_IDENTITY_ALLOWED_EMAIL_DOMAIN",
            "Identity allowed email domain",
            True,
            f"Set GCP_IDENTITY_ALLOWED_EMAIL_DOMAIN (see {_DOCS}).",
        ),
        SecretCheck("GCP_SERVICE_ACCOUNT", "Deploy service account", True, f"Set GCP_SERVICE_ACCOUNT (see {_DOCS})."),
        SecretCheck(
            "GCP_WORKLOAD_IDENTITY_PROVIDER",
            "Workload identity provider",
            True,
            f"Set GCP_WORKLOAD_IDENTITY_PROVIDER (see {_DOCS}).",
        ),
        SecretCheck(
            "GCP_BOOTSTRAP_ADMIN_EMAIL",
            "Bootstrap operator email",
            True,
            f"Set GCP_BOOTSTRAP_ADMIN_EMAIL, or opt out with {SKIP_OPERATOR_ENV}=true (see {_DOCS}).",
            opt_out_env=SKIP_OPERATOR_ENV,
        ),
        SecretCheck(
            "GCP_BOOTSTRAP_ADMIN_PASSWORD",
            "Bootstrap operator password",
            True,
            f"Set GCP_BOOTSTRAP_ADMIN_PASSWORD, or opt out with {SKIP_OPERATOR_ENV}=true (see {_DOCS}).",
            opt_out_env=SKIP_OPERATOR_ENV,
        ),
        SecretCheck(
            "GCP_MASTER_AUTHORIZED_CIDRS",
            "GKE authorized CIDRs",
            False,
            "Optional; empty locks the GKE control-plane to private endpoints only.",
        ),
    ]


def secret_checks(cloud: Cloud, environment: str, component: str | None = None) -> list[SecretCheck]:
    """Return the env-var/secret checks for a cloud, environment, and component."""
    if cloud is Cloud.GCP:
        return _gcp_secret_checks()
    return _aws_secret_checks(environment, component)


def tool_checks(cloud: Cloud) -> list[ToolCheck]:
    """Return the CLI tools a local deploy requires for a cloud."""
    common = [
        ToolCheck("git", "https://git-scm.com/downloads"),
        ToolCheck("terraform", "https://developer.hashicorp.com/terraform/downloads"),
    ]
    if cloud is Cloud.GCP:
        return [
            *common,
            ToolCheck("gcloud", "https://cloud.google.com/sdk/docs/install"),
            ToolCheck("docker", "https://docs.docker.com/engine/install/"),
            ToolCheck("kubectl", "https://kubernetes.io/docs/tasks/tools/"),
        ]
    return [*common, ToolCheck("aws", "https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html")]


# Manual prerequisites the tooling cannot verify; surfaced for interactive
# affirmation only (never a CI gate).
MANUAL_PREREQS: dict[Cloud, list[str]] = {
    Cloud.AWS: [
        "AWS CLI is authenticated for the target account (SSO or IAM credentials).",
        "You can add DNS records for ACM certificate validation and the ALB CNAME.",
    ],
    Cloud.GCP: [
        "gcloud is authenticated for the target project.",
        "You can add the DNS A record for the public hostname (needed for managed TLS).",
    ],
}


# --- Evaluation (pure) --------------------------------------------------------


def _truthy(value: str | None) -> bool:
    """Return True when an env value is an explicit truthy string."""
    return (value or "").strip().lower() in _TRUTHY


def _eval_secret(check: SecretCheck, env: Mapping[str, str]) -> CheckResult:
    """Evaluate one secret/env check against the environment."""
    if (env.get(check.env_var) or "").strip():
        return CheckResult(check.label, Status.OK, f"{check.env_var} is set")
    if not check.required:
        return CheckResult(check.label, Status.WARN, f"{check.env_var} not set. {check.remediation}")
    if check.opt_out_env and _truthy(env.get(check.opt_out_env)):
        return CheckResult(
            check.label,
            Status.WARN,
            f"{check.env_var} not set; skipped via {check.opt_out_env} opt-out.",
        )
    return CheckResult(check.label, Status.FAIL, f"{check.env_var} is required. {check.remediation}")


def _eval_tool(check: ToolCheck, tool_exists: Callable[[str], str | None]) -> CheckResult:
    """Evaluate one tool-presence check."""
    if tool_exists(check.name):
        return CheckResult(f"tool: {check.name}", Status.OK, "found on PATH")
    return CheckResult(f"tool: {check.name}", Status.FAIL, f"not found. Install: {check.install_url}")


def _gcp_local_input_checks(environment: str, repo_root: Path) -> list[CheckResult]:
    """Evaluate GCP local tfvars-overlay security posture via the shared validator."""
    tf_dir = repo_root / "platform" / "terraform" / "gcp" / "environments" / environment
    if not tf_dir.exists():
        return [CheckResult("GCP tfvars", Status.FAIL, f"missing Terraform environment dir {tf_dir}")]
    try:
        validate_gcp_control_plane_security_inputs(tf_dir)
    except ValueError as exc:
        return [CheckResult("GCP control-plane inputs", Status.FAIL, str(exc))]
    return [CheckResult("GCP control-plane inputs", Status.OK, "public hostname, managed TLS, and CIDRs are valid")]


def _aws_local_input_checks(environment: str, component: str | None, repo_root: Path) -> list[CheckResult]:
    """Evaluate presence of AWS local.auto.tfvars overlays for the selected components."""
    base = repo_root / "platform" / "terraform" / "environments" / environment
    overlay_dirs = {"core": base, "range": base / "range", "portal": base / "portal"}
    components = [component] if component in overlay_dirs else list(overlay_dirs)
    results = []
    for name in components:
        overlay = overlay_dirs[name] / "local.auto.tfvars"
        if overlay.exists():
            results.append(CheckResult(f"{name} overlay", Status.OK, f"{overlay.name} present"))
        else:
            results.append(
                CheckResult(
                    f"{name} overlay",
                    Status.FAIL,
                    f"missing {overlay}; the committed baseline fails on apply (see {_DOCS}).",
                )
            )
    return results


def run_preflight(
    cloud: Cloud,
    mode: Mode,
    environment: str,
    *,
    component: str | None = None,
    env: Mapping[str, str] | None = None,
    repo_root: Path | None = None,
    tool_exists: Callable[[str], str | None] | None = None,
) -> PreflightReport:
    """Evaluate every applicable prerequisite and return a structured report.

    Pure aside from the injected boundaries: ``env`` (defaults to the process
    environment), ``repo_root`` (defaults to :func:`get_repo_root`), and
    ``tool_exists`` (defaults to :func:`shutil.which`).
    """
    env = os.environ if env is None else env
    repo_root = get_repo_root() if repo_root is None else repo_root
    tool_exists = shutil.which if tool_exists is None else tool_exists

    results: list[CheckResult] = []
    if mode is Mode.CI:
        results.extend(_eval_secret(check, env) for check in secret_checks(cloud, environment, component))
    else:
        results.extend(_eval_tool(check, tool_exists) for check in tool_checks(cloud))
        if cloud is Cloud.GCP:
            results.extend(_gcp_local_input_checks(environment, repo_root))
        elif component is not None:
            results.extend(_aws_local_input_checks(environment, component, repo_root))
    return PreflightReport(cloud=cloud.value, mode=mode.value, environment=environment, results=results)


# --- Interactive / headless gate ----------------------------------------------


def _resolve_headless(mode: Mode, headless: bool | None) -> bool:
    """Resolve headless mode from an explicit flag, else auto-detect a non-TTY."""
    if headless is not None:
        return headless
    return mode is Mode.CI or not sys.stdin.isatty()


def preflight_gate(
    cloud: Cloud,
    mode: Mode,
    environment: str,
    *,
    component: str | None = None,
    headless: bool | None = None,
) -> PreflightReport:
    """Run preflight, print the report, confirm manual prereqs, and fail-fast.

    Raises ``SystemExit(1)`` if any required check fails, before any deploy side
    effect. In interactive mode it also asks the operator to affirm the manual
    prerequisites the tooling cannot verify; in headless mode it never prompts.

    This is the production entrypoint; it reads the real process environment,
    repository, and ``PATH``. Unit tests drive the pure :func:`run_preflight`
    directly (which takes injectable ``env`` / ``repo_root`` / ``tool_exists``).
    """
    report = run_preflight(cloud, mode, environment, component=component)
    header(f"Deploy preflight ({cloud.value} / {environment})")
    for result in report.results:
        _emit_result(result)

    if not report.ok:
        error(f"Preflight failed: {len(report.failures)} required prerequisite(s) missing. See messages above.")
        raise SystemExit(1)

    if not _resolve_headless(mode, headless):
        _confirm_manual_prereqs(cloud)

    success("Preflight passed.")
    return report


def _emit_result(result: CheckResult) -> None:
    """Emit one result line through the matching operator-message helper."""
    if result.status is Status.FAIL:
        error(f"{result.name}: {result.message}")
    elif result.status is Status.WARN:
        warn(f"{result.name}: {result.message}")
    else:
        info(f"{result.name}: {result.message}")


def _confirm_manual_prereqs(cloud: Cloud) -> None:
    """Ask the operator to affirm the prerequisites the tooling cannot verify."""
    prereqs = MANUAL_PREREQS.get(cloud, [])
    if not prereqs:
        return
    info("Manual prerequisites (not machine-checkable):")
    for item in prereqs:
        info(f"  - {item}")
    if not confirm("Have you confirmed the manual prerequisites above?"):
        error("Aborting: confirm the manual prerequisites, then re-run.")
        raise SystemExit(1)


# --- CI entrypoint (python -m preflight) --------------------------------------


def main(argv: list[str] | None = None) -> int:
    """Run the preflight gate from the command line (CI uses ``python -m preflight``)."""
    parser = argparse.ArgumentParser(description="Validate Shifter deploy prerequisites.")
    parser.add_argument("--cloud", required=True, choices=[c.value for c in Cloud])
    parser.add_argument("--env", required=True, dest="environment")
    parser.add_argument("--component", choices=sorted(_AWS_COMPONENT_STACKS), default=None)
    parser.add_argument("--mode", choices=[m.value for m in Mode], default=Mode.CI.value)
    parser.add_argument("--headless", action="store_true", default=None)
    args = parser.parse_args(argv)

    preflight_gate(
        Cloud(args.cloud),
        Mode(args.mode),
        args.environment,
        component=args.component,
        headless=args.headless,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
