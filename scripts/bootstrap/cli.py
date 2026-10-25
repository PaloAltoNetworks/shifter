"""Command-line wiring for the bootstrap deployment CLI."""

import argparse
import os
import shutil
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from urllib.parse import quote

from account_recovery import account_recovery
from aws_bootstrap import AWS_ENVIRONMENTS, BootstrapConfig, bootstrap_account
from aws_eks import deploy_eks, teardown_eks
from bootstrap_core import (
    HELP_AWS_PROFILE,
    HELP_DRY_RUN,
    GDCBootstrapConfig,
    code_block,
    confirm,
    error,
    get_default_gdc_project_id,
    header,
    info,
    run_cmd,
    set_assume_yes,
    success,
    warn,
)
from gcp_base_images import BaseImageError, discover_and_import, render_range_image_env
from gcp_control_plane import gdc_bootstrap_cluster
from gcp_foundation import bootstrap_gcp_foundation
from preflight import Cloud, Mode, preflight_gate
from terraform_deploy import terraform_deploy
from walkthrough import (
    walkthrough_acm_validation,
    walkthrough_backend_config,
    walkthrough_cognito_user,
    walkthrough_dns_setup,
    walkthrough_final_steps,
    walkthrough_github_secrets,
)

try:
    from runner import get_runner_config, provision_and_register_runners

    RUNNER_AVAILABLE = True
except ImportError:
    RUNNER_AVAILABLE = False

try:
    from gcp_runner import get_gcp_runner_config, provision_and_register_gcp_runners

    GCP_RUNNER_AVAILABLE = True
except ImportError:
    GCP_RUNNER_AVAILABLE = False

HELP_HEADLESS = "Non-interactive preflight: fail on missing prerequisites without prompting (auto-detected off a TTY)"
HELP_YES = (
    "Assume 'yes' for routine confirmation prompts so the bootstrap can run without a TTY "
    "(issue #1639). Does NOT authorize destructive cleanup; the leftover sweep has its own opt-in."
)
_RANGE_IMAGE_ENV_KEYS = frozenset({"GCP_RANGE_LINUX_IMAGE", "GCP_RANGE_KALI_IMAGE", "GCP_RANGE_DC_IMAGE"})
_AWS_COMPONENTS = ("core", "range", "portal")
_PREFLIGHT_COMPONENTS = (*_AWS_COMPONENTS, "deploy")


def full_deployment(env: str, profile: str, dry_run: bool = False) -> None:
    """Run complete deployment with interactive walkthrough."""
    header(f"Full {env.upper()} Deployment")

    print("""
This will guide you through a complete Shifter deployment:

  1. Bootstrap AWS account (S3 state bucket with native locking, GitHub OIDC, IAM)
  2. Configure GitHub secrets (automated with gh CLI or manual)
  3. Write instance Terraform backend configuration (outside the repo)
  4. Set up GitHub Actions runners (optional - for self-hosted CI/CD)
  5. Deploy infrastructure (Core → Range → Portal)
  6. Configure DNS and SSL certificate (manual - external DNS)
  7. Create first user

Automated steps will ask for confirmation:
  [y] yes - run automatically
  [n] no - abort (all steps are required)
  [m] manual - show instructions and wait

Estimated time: 30-45 minutes (mostly waiting for RDS and ACM)
""")

    if not dry_run and not confirm("Ready to begin?"):
        warn("Deployment cancelled")
        return

    if dry_run:
        info("[DRY-RUN] Showing what would happen...")

    # Phase 1: Bootstrap
    config = BootstrapConfig(env=env)
    bootstrap_result = bootstrap_account(config, profile, dry_run=dry_run)

    # Phase 2: GitHub Secrets
    walkthrough_github_secrets(bootstrap_result, dry_run=dry_run)

    # Phase 3: Backend Configuration
    walkthrough_backend_config(bootstrap_result, dry_run=dry_run)

    # Phase 4: GitHub Actions Runner Setup (automated - issue #1433)
    if RUNNER_AVAILABLE:
        runner_config = get_runner_config(
            env=env,
            region=config.region,
            github_org=config.github_org,
            github_repo=config.github_repo,
            aws_profile=profile,
        )
        provision_and_register_runners(
            runner_config,
            dry_run=dry_run,
            bucket_name=bootstrap_result.get("bucket_name"),
        )
    else:
        warn("Runner module not available - skipping GitHub runner setup")

    # Phase 5: Terraform Deployment
    if not dry_run and not confirm("Continue with Terraform deployment?"):
        print("\nYou can resume later with:")
        code_block(f"./scripts/bootstrap/deploy.py terraform --env {env} --profile {profile}")
        return

    outputs = terraform_deploy(
        env,
        profile,
        dry_run=dry_run,
        bucket_name=bootstrap_result.get("bucket_name"),
    )

    if not dry_run and outputs:
        # Phase 6: ACM Validation
        walkthrough_acm_validation(outputs, dry_run=dry_run)

        # Phase 7: DNS Setup
        walkthrough_dns_setup(outputs, dry_run=dry_run)

        # Phase 8: First User
        walkthrough_cognito_user(outputs, env, profile, dry_run=dry_run)

    # Final Summary
    walkthrough_final_steps(env)


def runners_deployment(
    env: str,
    profile: str,
    dry_run: bool = False,
    use_existing_network: bool = False,
    runner_count: int | None = None,
) -> None:
    """Provision + register self-hosted GitHub runners (issue #1433).

    First-class automatable path: Terraform provisions the runner fleet and (by
    default) a dedicated ADR-004-R20-compliant runner VPC, then each runner is
    registered over SSM and verified via the GitHub runners API. Registration
    tokens are minted per runner and never persisted (see runner.py).
    """
    if not RUNNER_AVAILABLE:
        error("Runner module not available - cannot provision runners")
        sys.exit(1)

    config = BootstrapConfig(env=env)
    runner_config = get_runner_config(
        env=env,
        region=config.region,
        github_org=config.github_org,
        github_repo=config.github_repo,
        aws_profile=profile,
    )
    provision_and_register_runners(
        runner_config,
        dry_run=dry_run,
        use_existing_network=use_existing_network,
        runner_count=runner_count,
    )


def gcp_runners_deployment(
    env: str,
    project_id: str,
    region: str,
    zone: str,
    *,
    dry_run: bool = False,
    runner_count: int | None = None,
    labels: str | None = None,
) -> None:
    """Provision + register GCP-native self-hosted runners (issue #1546).

    The GCP counterpart to :func:`runners_deployment`: Terraform provisions the
    GCE fleet plus a mandatory dedicated custom VPC (ADR-008-R8, no opt-out),
    then each runner is registered over ``gcloud compute ssh --tunnel-through-iap``
    with a per-runner token delivered over stdin and verified online + labeled via
    the GitHub runners API. Tokens are minted per runner and never persisted (see
    gcp_runner.py). Uses the operator's default gcloud/ADC identity (no profile).
    """
    if not GCP_RUNNER_AVAILABLE:
        error("GCP runner module not available - cannot provision GCP runners")
        sys.exit(1)
    if not project_id:
        error("GCP runner provisioning requires --project-id (or PANW_GCP_DEV / repo-root .env)")
        sys.exit(1)

    defaults = BootstrapConfig(env=env)
    runner_config = get_gcp_runner_config(
        env=env,
        project_id=project_id,
        region=region,
        zone=zone,
        github_org=defaults.github_org,
        github_repo=defaults.github_repo,
        labels=labels,
    )
    provision_and_register_gcp_runners(
        runner_config,
        dry_run=dry_run,
        runner_count=runner_count,
    )


def gcp_base_images_import(
    project_id: str,
    environment: str,
    region: str,
    *,
    dry_run: bool = False,
) -> dict[str, str]:
    """Import the reusable GHCR base images as native GCE images and wire the refs.

    Discovers Kali/Ubuntu/DC in GHCR, imports them into ``project_id`` as native
    GCE images (reusing unchanged digests), and sets the GCP_RANGE_*_IMAGE
    variables in the ``environment`` deployment Environment so deploy resolves
    them without a per-tenant Packer bake (#2309). The returned mapping is also
    the supported in-process handoff to the first local platform bootstrap.
    """
    if not project_id:
        error("gcp-images requires --project-id (the range project the images import into)")
        sys.exit(1)
    _validate_base_image_auth()

    imported = discover_and_import(project=project_id, region=region, dry_run=dry_run)
    range_image_env = render_range_image_env(imported)
    _publish_range_image_env(range_image_env, environment, dry_run=dry_run)
    success(f"Wired {', '.join(sorted(range_image_env))} into the {environment} deployment environment")
    return range_image_env


def _validate_base_image_auth(*, command_runner: Callable[..., object] = run_cmd) -> None:
    """Validate the existing GCP and GitHub CLI sessions without mutation."""
    for command, failure in (
        (["gcloud", "auth", "list", "--filter=status:ACTIVE", "--format=value(account)"], "gcloud authentication"),
        (["gh", "auth", "status"], "GitHub authentication"),
    ):
        result = command_runner(command, check=False, capture=True)
        missing_gcloud_identity = command[0] == "gcloud" and not (getattr(result, "stdout", "") or "").strip()
        if result is None or getattr(result, "returncode", 1) != 0 or missing_gcloud_identity:
            raise BaseImageError(f"{failure} is required before importing public base images")


def _publish_range_image_env(
    range_image_env: dict[str, str],
    environment: str,
    *,
    dry_run: bool,
    command_runner: Callable[..., object] = run_cmd,
) -> None:
    """Publish one complete exact image mapping to a GitHub Environment."""
    if set(range_image_env) != _RANGE_IMAGE_ENV_KEYS:
        raise BaseImageError("public base-image import did not return the complete range-image environment")

    if dry_run:
        for name, ref in sorted(range_image_env.items()):
            command_runner(["gh", "variable", "set", name, "--env", environment, "--body", ref], dry_run=True)
        return

    repo_result = command_runner(
        ["gh", "repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner"],
        capture=True,
    )
    repo = (getattr(repo_result, "stdout", "") or "").strip()
    if not repo:
        raise BaseImageError("could not resolve the current GitHub repository for Environment variable publication")

    environment_path = quote(environment, safe="")
    collection = f"repos/{repo}/environments/{environment_path}/variables"
    existing_result = command_runner(
        ["gh", "api", collection, "--paginate", "--jq", ".variables[].name"],
        capture=True,
    )
    if existing_result is None:
        raise BaseImageError(f"could not list GitHub Environment variables for {environment}")
    existing = set((getattr(existing_result, "stdout", "") or "").splitlines())

    for name, ref in sorted(range_image_env.items()):
        if name in existing:
            command = [
                "gh",
                "api",
                "--method",
                "PATCH",
                f"{collection}/{quote(name, safe='')}",
                "-f",
                f"name={name}",
                "-f",
                f"value={ref}",
            ]
        else:
            command = [
                "gh",
                "api",
                "--method",
                "POST",
                collection,
                "-f",
                f"name={name}",
                "-f",
                f"value={ref}",
            ]
        command_runner(command)


def _missing_dependency_lines(commands: dict[str, str]) -> list[str]:
    """Return formatted '  - cmd: desc' lines for each command not found on PATH."""
    return [f"  - {cmd}: {desc}" for cmd, desc in commands.items() if not shutil.which(cmd)]


# Tool -> install-hint. `_required_tools` selects the subset a command needs.
_TOOL_HINTS = {
    "git": "Git - https://git-scm.com/downloads",
    "aws": "AWS CLI - https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html",
    "terraform": "Terraform - https://developer.hashicorp.com/terraform/downloads",
    "gcloud": "Google Cloud CLI - https://cloud.google.com/sdk/docs/install",
    "gh": "GitHub CLI - https://cli.github.com/",
    "ssh-keygen": "OpenSSH client tools - https://www.openssh.com/",
    "docker": "Docker - https://docs.docker.com/engine/install/",
    "kubectl": "kubectl - https://kubernetes.io/docs/tasks/tools/",
    "helm": "Helm - https://helm.sh/docs/intro/install/",
    "oras": "ORAS CLI - https://oras.land/docs/installation",
}


def _required_tools(command: str | None, cloud: str | None, *, import_public_base_images: bool = False) -> set[str]:
    """Return the set of required CLI tools for a bootstrap command."""
    if command == "gcp-foundation":
        return {"git", "gcloud", "gh", "terraform"}
    if command == "gcp-images":
        return {"git", "gcloud", "gh", "oras"}
    if command == "gdc-bootstrap":
        tools = {"git", "gcloud", "ssh-keygen", "terraform", "docker", "kubectl", "helm"}
        return tools | ({"gh", "oras"} if import_public_base_images else set())
    if command == "runners":
        # GCP runners use gcloud + ADC (no AWS CLI); both clouds need gh + terraform.
        cloud_tools = {"gcloud"} if cloud == Cloud.GCP.value else {"aws"}
        return {"git", "gh", "terraform"} | cloud_tools
    if command in {"eks-deploy", "eks-teardown"}:
        return {"git", "aws", "terraform", "kubectl", "helm"}
    if command in {None, "bootstrap", "terraform", "full"}:
        return {"git", "aws", "terraform"}
    return {"git"}


def check_dependencies(
    command: str | None = None,
    cloud: str | None = None,
    *,
    import_public_base_images: bool = False,
) -> None:
    """Check command-specific dependencies before starting."""
    required = {
        tool: _TOOL_HINTS[tool]
        for tool in _required_tools(command, cloud, import_public_base_images=import_public_base_images)
    }
    optional = {"gh": "GitHub CLI - https://cli.github.com/ (recommended for automating GitHub secrets)"}

    missing_required = _missing_dependency_lines(required)
    missing_optional = _missing_dependency_lines(optional)

    if missing_required:
        error("Missing required dependencies:")
        for item in missing_required:
            print(item)
        sys.exit(1)

    if missing_optional:
        warn("Missing optional dependencies (some automation features will be unavailable):")
        for item in missing_optional:
            print(item)
        print()


def _add_runners_subparser(subparsers: argparse._SubParsersAction) -> None:
    """Wire the `runners` subcommand (issue #1433 AWS; issue #1546 GCP).

    --cloud selects the provider; AWS is the default for back-compat. GCP
    provisions into the target GCP project (dev-tenant containment) with a
    dedicated runner VPC and IAP-only registration.
    """
    runners_parser = subparsers.add_parser(
        "runners",
        help="Provision and auto-register self-hosted GitHub Actions runners (dedicated runner VPC by default)",
    )
    runners_parser.add_argument(
        "--cloud", choices=[c.value for c in Cloud], default=Cloud.AWS.value, help="Target cloud (default: aws)"
    )
    runners_parser.add_argument(
        "--env",
        required=True,
        help="Environment (AWS: dev/proof/prod; GCP: e.g. gcp-dev). Validated per --cloud.",
    )
    runners_parser.add_argument("--profile", help=HELP_AWS_PROFILE + " (AWS only)")
    runners_parser.add_argument("--dry-run", action="store_true", help=HELP_DRY_RUN)
    runners_parser.add_argument(
        "--use-existing-network",
        action="store_true",
        help=(
            "Do not provision the standard dedicated runner network; use an existing compliant "
            "network's vpc_id/subnet_id from a gitignored local.auto.tfvars in the runner root."
        ),
    )
    runners_parser.add_argument(
        "--runner-count",
        type=int,
        default=None,
        help="Override runner_count for this apply (defaults to the runner tfvars value).",
    )
    # GCP-only flags (ignored for --cloud aws). GCP uses the operator's default
    # gcloud/ADC identity, so there is no --profile equivalent.
    runners_parser.add_argument(
        "--project-id",
        default=get_default_gdc_project_id(),
        help="GCP project ID to provision runners into (GCP only; defaults to PANW_GCP_DEV or repo-root .env)",
    )
    runners_parser.add_argument("--region", default="us-central1", help="GCP region (GCP only)")
    runners_parser.add_argument("--zone", default="us-central1-a", help="GCP compute zone (GCP only)")
    runners_parser.add_argument(
        "--labels",
        default=None,
        help="Custom runner label set (GCP only; defaults to the environment name, e.g. gcp-dev)",
    )


def _add_gdc_bootstrap_subparser(subparsers: argparse._SubParsersAction) -> None:
    """Wire the `gdc-bootstrap` subcommand (ADR-008 GCP standup entrypoint).

    --range-backend selects the range plane (#1716) and --terraform-identity
    selects the identity the control-plane Terraform runs as (#1718); both
    default to the back-compat path but can be overridden for hardened orgs.
    """
    gdc_parser = subparsers.add_parser(
        "gdc-bootstrap",
        help="Bootstrap a repeatable Google Distributed Cloud VM Runtime evaluation cluster",
    )
    gdc_parser.add_argument(
        "--project-id",
        default=get_default_gdc_project_id(),
        help="GCP project ID (defaults to PANW_GCP_DEV or repo-root .env)",
    )
    gdc_parser.add_argument(
        "--environment",
        default="gcp-dev",
        help=(
            "Deployment environment name (default gcp-dev). Selects the Terraform root "
            "(platform/terraform/gcp/environments/<env>), the state prefix "
            "(shifter/<env>/platform-core), the Helm values override (values-<env>.yaml), and the "
            "operator-creds overlay. Use a per-tenant name (e.g. nazgul) to stand up an additional tenant."
        ),
    )
    gdc_parser.add_argument("--cluster-id", default="cluster1", help="Cluster name / prefix")
    gdc_parser.add_argument("--region", default="us-central1", help="Cluster region")
    gdc_parser.add_argument("--zone", default="us-central1-a", help="Compute Engine zone")
    gdc_parser.add_argument("--google-account-email", help="Optional Google identity to grant cluster-admin")
    gdc_parser.add_argument(
        "--shifter-config",
        help=(
            "Path to the deployment's shifter.yaml; its settings.range_egress is rendered into "
            "range_egress.auto.tfvars before the control-plane apply (#1015). Defaults to "
            "$SHIFTER_CONFIG or ./shifter.yaml; a missing config fails the deploy."
        ),
    )
    gdc_parser.add_argument(
        "--range-backend",
        choices=["gce", "gdc"],
        default=(os.environ.get("GCP_RANGE_BACKEND", "gce").strip() or "gce"),
        help=(
            "GCP range plane backend (#1716; default from GCP_RANGE_BACKEND, else gce). "
            "'gce' provisions plain GCE range instances and skips the ABM/GDC VM Runtime "
            "substrate (no service-account JSON key required). 'gdc' builds the substrate "
            "for the KubeVirt VM Runtime range plane."
        ),
    )
    gdc_parser.add_argument(
        "--terraform-identity",
        choices=["bootstrap-sa", "operator-adc"],
        default=(os.environ.get("SHIFTER_GCP_TERRAFORM_IDENTITY", "operator-adc").strip() or "operator-adc"),
        help=(
            "Identity the control-plane Terraform runs as (#1718; default from "
            "SHIFTER_GCP_TERRAFORM_IDENTITY, else operator-adc). 'operator-adc' (default) runs "
            "terraform under the caller's Application Default Credentials, minting no service "
            "account or key (secure-by-default; the only path on orgs that forbid owner-on-SA or "
            "SA-key creation). 'bootstrap-sa' impersonates a dedicated tf-bootstrap service account "
            "granted roles/owner (ADR-008), for operators who cannot run terraform under their own ADC."
        ),
    )
    gdc_parser.add_argument("--dry-run", action="store_true", help=HELP_DRY_RUN)
    gdc_parser.add_argument("--yes", action="store_true", help=HELP_YES)
    gdc_parser.add_argument(
        "--import-public-base-images",
        action="store_true",
        help=(
            "Discover and import the public Kali/Ubuntu/DC base set, publish the exact references to the "
            "selected GitHub Environment, and use them for this local GCE platform bootstrap"
        ),
    )
    gdc_parser.add_argument(
        "--allow-missing-range-images",
        action="store_true",
        help=(
            "Proceed even if the GCE range guest images are not yet baked or the required range-cell "
            "variables are unset (a deliberate platform-first bring-up). By default gdc-bootstrap fails "
            "closed on these preconditions so a fresh project does not deploy a range-incapable control "
            "plane; see scripts/bootstrap/README.md 'Fresh GCP Account Order'."
        ),
    )


def _add_gcp_images_subparser(subparsers: argparse._SubParsersAction) -> None:
    """Wire the `gcp-images` subcommand: import the reusable GHCR base images (#2309)."""
    images_parser = subparsers.add_parser(
        "gcp-images",
        help="Import the reusable GHCR base images (Kali/Ubuntu/DC) as native GCE images and wire GCP_RANGE_*_IMAGE",
    )
    images_parser.add_argument(
        "--project-id",
        default=get_default_gdc_project_id(),
        help="GCP project the range guest images import into (defaults to PANW_GCP_DEV or the repo-root env file)",
    )
    images_parser.add_argument(
        "--environment",
        default="gcp-dev",
        help="GitHub deployment Environment to set GCP_RANGE_*_IMAGE in (default gcp-dev)",
    )
    images_parser.add_argument("--region", default="us-central1", help="Region for the temporary transfer bucket")
    images_parser.add_argument("--dry-run", action="store_true", help=HELP_DRY_RUN)


def _add_eks_subparsers(subparsers: argparse._SubParsersAction) -> None:
    """Add the explicit AWS EKS deploy and teardown commands."""
    deploy_parser = subparsers.add_parser(
        "eks-deploy",
        help="Explicitly deploy backend: aws to EKS through the shared Helm chart",
    )
    deploy_parser.add_argument("--config", default="shifter.yaml", help="Validated root installation config")
    deploy_parser.add_argument(
        "--images",
        default=".shifter/images.json",
        help="JSON mapping of workloads to attested repository@sha256 identities",
    )
    deploy_parser.add_argument(
        "--backend-config",
        default=os.environ.get("SHIFTER_BACKEND_CONFIG_PATH", ""),
        help="Protected S3 backend config rendered outside the repository",
    )
    deploy_parser.add_argument(
        "--terraform-inputs",
        default=os.environ.get("SHIFTER_EKS_TFVARS_PATH", ""),
        help="Protected JSON var-file containing the EKS infrastructure/runtime projection",
    )
    deploy_parser.add_argument("--profile", help=HELP_AWS_PROFILE)
    deploy_parser.add_argument("--dry-run", action="store_true", help=HELP_DRY_RUN)

    teardown_parser = subparsers.add_parser(
        "eks-teardown",
        help="Explicitly tear down only the root-configured AWS EKS bundle",
    )
    teardown_parser.add_argument("--config", default="shifter.yaml", help="Validated root installation config")
    teardown_parser.add_argument(
        "--backend-config",
        default=os.environ.get("SHIFTER_BACKEND_CONFIG_PATH", ""),
        help="Protected S3 backend config rendered outside the repository",
    )
    teardown_parser.add_argument(
        "--terraform-inputs",
        default=os.environ.get("SHIFTER_EKS_TFVARS_PATH", ""),
        help="Protected JSON var-file containing the isolated EKS root inputs",
    )
    teardown_parser.add_argument("--profile", help=HELP_AWS_PROFILE)
    teardown_parser.add_argument("--dry-run", action="store_true", help=HELP_DRY_RUN)


def _add_aws_deploy_subparsers(subparsers: argparse._SubParsersAction) -> None:
    """Add the AWS bootstrap, Terraform, and full-deploy commands."""
    bootstrap_parser = subparsers.add_parser(
        "bootstrap", help="Bootstrap AWS account (S3 state bucket with native locking, GitHub OIDC, IAM)"
    )
    bootstrap_parser.add_argument("--env", required=True, choices=AWS_ENVIRONMENTS, help="Environment")
    bootstrap_parser.add_argument("--profile", required=True, help=HELP_AWS_PROFILE)
    bootstrap_parser.add_argument("--dry-run", action="store_true", help=HELP_DRY_RUN)
    bootstrap_parser.add_argument("--headless", action="store_const", const=True, default=None, help=HELP_HEADLESS)
    bootstrap_parser.add_argument("--yes", action="store_true", help=HELP_YES)

    terraform_parser = subparsers.add_parser("terraform", help="Deploy Terraform infrastructure")
    terraform_parser.add_argument("--env", required=True, choices=AWS_ENVIRONMENTS, help="Environment")
    terraform_parser.add_argument("--profile", required=True, help=HELP_AWS_PROFILE)
    terraform_parser.add_argument("--dry-run", action="store_true", help=HELP_DRY_RUN)
    terraform_parser.add_argument("--headless", action="store_const", const=True, default=None, help=HELP_HEADLESS)
    terraform_parser.add_argument("--yes", action="store_true", help=HELP_YES)

    full_parser = subparsers.add_parser("full", help="Full interactive deployment (bootstrap + config + terraform)")
    full_parser.add_argument("--env", required=True, choices=AWS_ENVIRONMENTS, help="Environment")
    full_parser.add_argument("--profile", required=True, help=HELP_AWS_PROFILE)
    full_parser.add_argument("--dry-run", action="store_true", help=HELP_DRY_RUN)
    full_parser.add_argument("--headless", action="store_const", const=True, default=None, help=HELP_HEADLESS)
    full_parser.add_argument("--yes", action="store_true", help=HELP_YES)


def _add_preflight_and_recovery_subparsers(subparsers: argparse._SubParsersAction) -> None:
    """Add prerequisite validation and account-leftover recovery commands."""
    preflight_parser = subparsers.add_parser(
        "preflight", help="Validate deploy prerequisites (tools, secrets, config) without making changes"
    )
    preflight_parser.add_argument("--cloud", required=True, choices=[c.value for c in Cloud], help="Target cloud")
    preflight_parser.add_argument("--env", required=True, help="Environment (e.g. dev, proof, prod, gcp-dev)")
    preflight_parser.add_argument(
        "--component",
        choices=sorted(_PREFLIGHT_COMPONENTS),
        default=None,
        help="Deployment component or protected-environment boundary to validate",
    )
    preflight_parser.add_argument("--headless", action="store_const", const=True, default=None, help=HELP_HEADLESS)

    recovery_parser = subparsers.add_parser(
        "account-recovery",
        help="Detect (and optionally --sweep) leftover AWS resources from an incomplete prior teardown",
    )
    recovery_parser.add_argument("--env", required=True, choices=AWS_ENVIRONMENTS, help="Environment")
    recovery_parser.add_argument("--profile", required=True, help=HELP_AWS_PROFILE)
    recovery_parser.add_argument(
        "--sweep",
        action="store_true",
        help="Delete the owned leftovers (explicit destructive opt-in; detection is read-only without it)",
    )
    recovery_parser.add_argument("--dry-run", action="store_true", help=HELP_DRY_RUN)
    recovery_parser.add_argument("--yes", action="store_true", help=HELP_YES)


def _build_parser() -> argparse.ArgumentParser:
    """Build the bootstrap CLI argument parser and its subcommands."""
    parser = argparse.ArgumentParser(
        description="Shifter deployment CLI - interactive deployment guide",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Preview full deployment (no changes)
  ./scripts/bootstrap/deploy.py full --env prod --profile my-prod-profile --dry-run

  # Run full interactive deployment
  ./scripts/bootstrap/deploy.py full --env prod --profile my-prod-profile

  # Just bootstrap AWS account
  ./scripts/bootstrap/deploy.py bootstrap --env prod --profile my-prod-profile

  # Just run terraform (after bootstrap)
  ./scripts/bootstrap/deploy.py terraform --env prod --profile my-prod-profile

  # Bootstrap a repeatable Google Distributed Cloud VM Runtime cluster
  ./scripts/bootstrap/deploy.py gdc-bootstrap --project-id example-gcp-project --cluster-id cluster1
        """,
    )

    subparsers = parser.add_subparsers(dest="command", required=True)
    _add_eks_subparsers(subparsers)
    _add_aws_deploy_subparsers(subparsers)
    _add_preflight_and_recovery_subparsers(subparsers)
    _add_runners_subparser(subparsers)
    _add_gdc_bootstrap_subparser(subparsers)
    _add_gcp_images_subparser(subparsers)
    foundation = subparsers.add_parser("gcp-foundation", help="Bootstrap GCP state, CI identities, and image network")
    foundation.add_argument("--inputs", required=True, help="Explicit foundation JSON Terraform var-file")
    foundation.add_argument("--dry-run", action="store_true", help=HELP_DRY_RUN)
    foundation.add_argument("--yes", action="store_true", help=HELP_YES)

    return parser


def _build_gdc_bootstrap_config(args: argparse.Namespace) -> GDCBootstrapConfig:
    """Build the GDCBootstrapConfig for the `gdc-bootstrap` subcommand from parsed args."""
    return GDCBootstrapConfig(
        project_id=args.project_id,
        environment=args.environment,
        cluster_id=args.cluster_id,
        region=args.region,
        zone=args.zone,
        google_account_email=args.google_account_email,
        shifter_config_path=args.shifter_config,
        range_backend=args.range_backend,
        terraform_identity=args.terraform_identity,
    )


def _dispatch_runners(args: argparse.Namespace) -> None:
    """Dispatch the `runners` subcommand to the AWS or GCP provisioning path."""
    if args.cloud == Cloud.GCP.value:
        # The dedicated runner network is mandatory for GCP (ADR-008-R8), so the
        # AWS-only existing-network opt-out is rejected rather than silently ignored.
        if args.use_existing_network:
            error("--use-existing-network is not supported for --cloud gcp; the dedicated runner network is mandatory")
            sys.exit(1)
        # gcp_runner._verify_prerequisites fails closed on gh auth + gcloud ADC
        # before any mutation. The full platform preflight_gate is intentionally
        # not used here: a runner standup must not require the platform
        # environment's secret/config surface.
        gcp_runners_deployment(
            args.env,
            args.project_id,
            args.region,
            args.zone,
            dry_run=args.dry_run,
            runner_count=args.runner_count,
            labels=args.labels,
        )
        return

    if args.env not in AWS_ENVIRONMENTS:
        error(f"--env must be one of {', '.join(AWS_ENVIRONMENTS)} for --cloud aws (got '{args.env}')")
        sys.exit(1)
    if not args.profile:
        error("--profile is required for --cloud aws")
        sys.exit(1)
    runners_deployment(
        args.env,
        args.profile,
        dry_run=args.dry_run,
        use_existing_network=args.use_existing_network,
        runner_count=args.runner_count,
    )


def _handle_preflight(args: argparse.Namespace) -> None:
    """Run the read-only prerequisite gate."""
    preflight_gate(Cloud(args.cloud), Mode.LOCAL, args.env, component=args.component, headless=args.headless)


def _handle_account_recovery(args: argparse.Namespace) -> None:
    """Run account-leftover detection or its explicitly authorized sweep."""
    account_recovery(args.env, args.profile, sweep=args.sweep, dry_run=args.dry_run)


def _handle_eks_deploy(args: argparse.Namespace) -> None:
    """Deploy the root-configured AWS EKS bundle."""
    deploy_eks(
        args.config,
        args.images,
        backend_config_path=args.backend_config,
        terraform_inputs_path=args.terraform_inputs,
        aws_profile=args.profile,
        dry_run=args.dry_run,
    )


def _handle_eks_teardown(args: argparse.Namespace) -> None:
    """Tear down only the root-configured AWS EKS bundle."""
    teardown_eks(
        args.config,
        backend_config_path=args.backend_config,
        terraform_inputs_path=args.terraform_inputs,
        aws_profile=args.profile,
        dry_run=args.dry_run,
    )


def _handle_bootstrap(args: argparse.Namespace) -> None:
    """Bootstrap the selected AWS account and render operator handoffs."""
    config = BootstrapConfig(env=args.env)
    result = bootstrap_account(config, args.profile, dry_run=args.dry_run)
    if not args.dry_run:
        walkthrough_github_secrets(result, dry_run=False)
        walkthrough_backend_config(result, dry_run=False)


def _handle_terraform(args: argparse.Namespace) -> None:
    """Deploy AWS Terraform and complete its operator walkthroughs."""
    outputs = terraform_deploy(args.env, args.profile, dry_run=args.dry_run)
    if not args.dry_run and outputs:
        walkthrough_acm_validation(outputs, dry_run=False)
        walkthrough_dns_setup(outputs, dry_run=False)
        walkthrough_cognito_user(outputs, args.env, args.profile, dry_run=False)
        walkthrough_final_steps(args.env)


def _handle_full(args: argparse.Namespace) -> None:
    """Run the complete AWS deployment workflow."""
    full_deployment(args.env, args.profile, dry_run=args.dry_run)


def _handle_gdc_bootstrap(args: argparse.Namespace) -> None:
    """Bootstrap the configured GDC VM Runtime control plane."""
    config = _build_gdc_bootstrap_config(args)
    if not args.import_public_base_images:
        gdc_bootstrap_cluster(
            config,
            dry_run=args.dry_run,
            allow_missing_range_images=args.allow_missing_range_images,
        )
        return

    if config.builds_gdc_substrate:
        raise BaseImageError("--import-public-base-images applies only to the native GCE range backend")
    gcp_bootstrap_with_public_images(
        config,
        dry_run=args.dry_run,
        allow_missing_range_images=args.allow_missing_range_images,
    )


def gcp_bootstrap_with_public_images(
    config: GDCBootstrapConfig,
    *,
    dry_run: bool,
    allow_missing_range_images: bool = False,
) -> None:
    """Import, publish, bind, and consume one exact public image mapping."""
    if not dry_run:
        header("Foundation-ready Shifter GCP bootstrap")
        info(f"GCP Project: {config.project_id}")
        info(f"Deployment Environment: {config.environment}")
        info(f"Region / Zone: {config.region} / {config.zone}")
        info("Public base images: import or reuse Kali, Ubuntu, and DC before platform bootstrap")
        if not confirm("Import the public base set, publish its exact references, and bootstrap this deployment?"):
            warn("Aborted by user")
            sys.exit(0)

    range_image_env = gcp_base_images_import(
        config.project_id,
        config.environment,
        config.region,
        dry_run=dry_run,
    )
    with _temporary_environment_overlay(range_image_env):
        gdc_bootstrap_cluster(
            config,
            dry_run=dry_run,
            allow_missing_range_images=allow_missing_range_images,
            confirmation_obtained=not dry_run,
        )


@contextmanager
def _temporary_environment_overlay(values: dict[str, str]) -> Iterator[None]:
    """Overlay imported image references for one local bootstrap and restore them."""
    if set(values) != _RANGE_IMAGE_ENV_KEYS:
        raise BaseImageError("public base-image import did not return the complete range-image environment")
    previous = {key: os.environ.get(key) for key in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


_COMMAND_HANDLERS = {
    "gcp-foundation": lambda args: bootstrap_gcp_foundation(args.inputs, dry_run=args.dry_run),
    "preflight": _handle_preflight,
    "account-recovery": _handle_account_recovery,
    "eks-deploy": _handle_eks_deploy,
    "eks-teardown": _handle_eks_teardown,
    "bootstrap": _handle_bootstrap,
    "terraform": _handle_terraform,
    "full": _handle_full,
    "runners": _dispatch_runners,
    "gdc-bootstrap": _handle_gdc_bootstrap,
    "gcp-images": lambda args: gcp_base_images_import(
        args.project_id, args.environment, args.region, dry_run=args.dry_run
    ),
}


def main() -> None:
    """Parse CLI arguments, enforce shared gates, and invoke one handler."""
    args = _build_parser().parse_args()
    if getattr(args, "yes", False):
        set_assume_yes(True)
    check_dependencies(
        args.command,
        cloud=getattr(args, "cloud", None),
        import_public_base_images=getattr(args, "import_public_base_images", False),
    )
    if args.command in {"bootstrap", "terraform", "full"}:
        preflight_gate(Cloud.AWS, Mode.LOCAL, args.env, headless=args.headless)
    try:
        _COMMAND_HANDLERS[args.command](args)
    except BaseImageError as exc:
        error(str(exc))
        raise SystemExit(1) from None
