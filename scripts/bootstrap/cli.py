"""Command-line wiring for the bootstrap deployment CLI."""

import argparse
import shutil
import sys

from aws_bootstrap import AWS_ENVIRONMENTS, BootstrapConfig, bootstrap_account
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
    warn,
)
from gcp_control_plane import gdc_bootstrap_cluster
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
    from runner import get_runner_config, walkthrough_runner_setup

    RUNNER_AVAILABLE = True
except ImportError:
    RUNNER_AVAILABLE = False


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

    # Phase 4: GitHub Actions Runner Setup (optional)
    runner_result = None
    if RUNNER_AVAILABLE:
        runner_config = get_runner_config(
            env=env,
            region=config.region,
            github_org=config.github_org,
            github_repo=config.github_repo,
            aws_profile=profile,
        )
        runner_result = walkthrough_runner_setup(runner_config, dry_run=dry_run)
        if runner_result:
            # Store app_id for terraform vars if needed
            info(f"Runner App ID: {runner_result.get('app_id', 'N/A')}")
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


def _missing_dependency_lines(commands: dict[str, str]) -> list[str]:
    """Return formatted '  - cmd: desc' lines for each command not found on PATH."""
    return [f"  - {cmd}: {desc}" for cmd, desc in commands.items() if not shutil.which(cmd)]


def check_dependencies(command: str | None = None) -> None:
    """Check command-specific dependencies before starting."""
    required = {"git": "Git - https://git-scm.com/downloads"}

    if command in {None, "bootstrap", "terraform", "full"}:
        required.update(
            {
                "aws": "AWS CLI - https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html",
                "terraform": "Terraform - https://developer.hashicorp.com/terraform/downloads",
            }
        )

    if command == "gdc-bootstrap":
        required.update(
            {
                "gcloud": "Google Cloud CLI - https://cloud.google.com/sdk/docs/install",
                "ssh-keygen": "OpenSSH client tools - https://www.openssh.com/",
                "terraform": "Terraform - https://developer.hashicorp.com/terraform/downloads",
                "docker": "Docker - https://docs.docker.com/engine/install/",
                "kubectl": "kubectl - https://kubernetes.io/docs/tasks/tools/",
                "helm": "Helm - https://helm.sh/docs/intro/install/",
            }
        )

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


def main() -> None:
    """Parse CLI arguments and dispatch the requested bootstrap operation."""
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
  ./scripts/bootstrap/deploy.py gdc-bootstrap --project-id prod-rwctxzl6shxk --cluster-id cluster1
        """,
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # Bootstrap command
    bootstrap_parser = subparsers.add_parser(
        "bootstrap", help="Bootstrap AWS account (S3 state bucket with native locking, GitHub OIDC, IAM)"
    )
    bootstrap_parser.add_argument("--env", required=True, choices=AWS_ENVIRONMENTS, help="Environment")
    bootstrap_parser.add_argument("--profile", required=True, help=HELP_AWS_PROFILE)
    bootstrap_parser.add_argument("--dry-run", action="store_true", help=HELP_DRY_RUN)

    # Terraform command
    tf_parser = subparsers.add_parser("terraform", help="Deploy Terraform infrastructure")
    tf_parser.add_argument("--env", required=True, choices=AWS_ENVIRONMENTS, help="Environment")
    tf_parser.add_argument("--profile", required=True, help=HELP_AWS_PROFILE)
    tf_parser.add_argument("--dry-run", action="store_true", help=HELP_DRY_RUN)

    # Full command
    full_parser = subparsers.add_parser("full", help="Full interactive deployment (bootstrap + config + terraform)")
    full_parser.add_argument("--env", required=True, choices=AWS_ENVIRONMENTS, help="Environment")
    full_parser.add_argument("--profile", required=True, help=HELP_AWS_PROFILE)
    full_parser.add_argument("--dry-run", action="store_true", help=HELP_DRY_RUN)

    gdc_parser = subparsers.add_parser(
        "gdc-bootstrap",
        help="Bootstrap a repeatable Google Distributed Cloud VM Runtime evaluation cluster",
    )
    gdc_parser.add_argument(
        "--project-id",
        default=get_default_gdc_project_id(),
        help="GCP project ID (defaults to PANW_GCP_DEV or repo-root .env)",
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
    gdc_parser.add_argument("--dry-run", action="store_true", help=HELP_DRY_RUN)

    args = parser.parse_args()
    check_dependencies(args.command)

    if args.command == "bootstrap":
        config = BootstrapConfig(env=args.env)
        result = bootstrap_account(config, args.profile, dry_run=args.dry_run)
        if not args.dry_run:
            walkthrough_github_secrets(result, dry_run=args.dry_run)
            walkthrough_backend_config(result, dry_run=args.dry_run)

    elif args.command == "terraform":
        outputs = terraform_deploy(args.env, args.profile, dry_run=args.dry_run)
        if not args.dry_run and outputs:
            walkthrough_acm_validation(outputs, dry_run=args.dry_run)
            walkthrough_dns_setup(outputs, dry_run=args.dry_run)
            walkthrough_cognito_user(outputs, args.env, args.profile, dry_run=args.dry_run)
            walkthrough_final_steps(args.env)

    elif args.command == "full":
        full_deployment(args.env, args.profile, dry_run=args.dry_run)

    elif args.command == "gdc-bootstrap":
        gdc_bootstrap_cluster(
            GDCBootstrapConfig(
                project_id=args.project_id,
                cluster_id=args.cluster_id,
                region=args.region,
                zone=args.zone,
                google_account_email=args.google_account_email,
                shifter_config_path=args.shifter_config,
            ),
            dry_run=args.dry_run,
        )
