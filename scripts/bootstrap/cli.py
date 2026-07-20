"""Command-line wiring for the bootstrap deployment CLI."""

import argparse
import os
import shutil
import sys

from account_recovery import account_recovery
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
    set_assume_yes,
    warn,
)
from gcp_control_plane import gdc_bootstrap_cluster
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
_AWS_COMPONENTS = ("core", "range", "portal")


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
}


def _required_tools(command: str | None, cloud: str | None) -> set[str]:
    """Return the set of required CLI tools for a bootstrap command."""
    if command == "gdc-bootstrap":
        return {"git", "gcloud", "ssh-keygen", "terraform", "docker", "kubectl", "helm"}
    if command == "runners":
        # GCP runners use gcloud + ADC (no AWS CLI); both clouds need gh + terraform.
        cloud_tools = {"gcloud"} if cloud == Cloud.GCP.value else {"aws"}
        return {"git", "gh", "terraform"} | cloud_tools
    if command in {None, "bootstrap", "terraform", "full"}:
        return {"git", "aws", "terraform"}
    return {"git"}


def check_dependencies(command: str | None = None, cloud: str | None = None) -> None:
    """Check command-specific dependencies before starting."""
    required = {tool: _TOOL_HINTS[tool] for tool in _required_tools(command, cloud)}
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
            "Do not provision a dedicated runner network; use the vpc_id/subnet_id or "
            "allow_default_vpc opt-in already configured in the runner tfvars."
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
    bootstrap_parser.add_argument("--headless", action="store_const", const=True, default=None, help=HELP_HEADLESS)
    bootstrap_parser.add_argument("--yes", action="store_true", help=HELP_YES)

    # Terraform command
    tf_parser = subparsers.add_parser("terraform", help="Deploy Terraform infrastructure")
    tf_parser.add_argument("--env", required=True, choices=AWS_ENVIRONMENTS, help="Environment")
    tf_parser.add_argument("--profile", required=True, help=HELP_AWS_PROFILE)
    tf_parser.add_argument("--dry-run", action="store_true", help=HELP_DRY_RUN)
    tf_parser.add_argument("--headless", action="store_const", const=True, default=None, help=HELP_HEADLESS)
    tf_parser.add_argument("--yes", action="store_true", help=HELP_YES)

    # Full command
    full_parser = subparsers.add_parser("full", help="Full interactive deployment (bootstrap + config + terraform)")
    full_parser.add_argument("--env", required=True, choices=AWS_ENVIRONMENTS, help="Environment")
    full_parser.add_argument("--profile", required=True, help=HELP_AWS_PROFILE)
    full_parser.add_argument("--dry-run", action="store_true", help=HELP_DRY_RUN)
    full_parser.add_argument("--headless", action="store_const", const=True, default=None, help=HELP_HEADLESS)
    full_parser.add_argument("--yes", action="store_true", help=HELP_YES)

    # Preflight command: validate deploy prerequisites without making any change.
    preflight_parser = subparsers.add_parser(
        "preflight", help="Validate deploy prerequisites (tools, secrets, config) without making changes"
    )
    preflight_parser.add_argument("--cloud", required=True, choices=[c.value for c in Cloud], help="Target cloud")
    preflight_parser.add_argument("--env", required=True, help="Environment (e.g. dev, proof, prod, gcp-dev)")
    preflight_parser.add_argument(
        "--component", choices=sorted(_AWS_COMPONENTS), default=None, help="AWS component to scope overlay checks"
    )
    preflight_parser.add_argument("--headless", action="store_const", const=True, default=None, help=HELP_HEADLESS)

    # Account leftover recovery: detect (and optionally sweep) state-absent
    # control-plane residue from an incomplete prior teardown so a re-standup
    # does not fail collision-by-collision (issue #1639 / #1618).
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

    _add_runners_subparser(subparsers)
    _add_gdc_bootstrap_subparser(subparsers)

    return parser


def _build_gdc_bootstrap_config(args: argparse.Namespace) -> GDCBootstrapConfig:
    """Build the GDCBootstrapConfig for the `gdc-bootstrap` subcommand from parsed args."""
    return GDCBootstrapConfig(
        project_id=args.project_id,
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


def main() -> None:
    """Parse CLI arguments and dispatch the requested bootstrap operation."""
    parser = _build_parser()
    args = parser.parse_args()
    # --yes lets the bootstrap flow's confirm() prompts proceed without a TTY
    # (issue #1639). Routine prompts only; the leftover sweep stays separately gated.
    if getattr(args, "yes", False):
        set_assume_yes(True)
    check_dependencies(args.command, cloud=getattr(args, "cloud", None))

    if args.command == "preflight":
        preflight_gate(Cloud(args.cloud), Mode.LOCAL, args.env, component=args.component, headless=args.headless)
        return

    if args.command == "account-recovery":
        # Recovery is not a deploy; it resolves the account itself and gates its
        # own destructive sweep. It does not run the deploy preflight_gate.
        account_recovery(args.env, args.profile, sweep=args.sweep, dry_run=args.dry_run)
        return

    # Fail-safe gate: verify prerequisites and confirm the manual ones before any
    # deploy command touches the account. Raises SystemExit(1) if a required
    # prerequisite is missing. Run `preflight --component <c>` for overlay/secret depth.
    if args.command in {"bootstrap", "terraform", "full"}:
        preflight_gate(Cloud.AWS, Mode.LOCAL, args.env, headless=args.headless)

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

    elif args.command == "runners":
        _dispatch_runners(args)

    elif args.command == "gdc-bootstrap":
        gdc_bootstrap_cluster(
            _build_gdc_bootstrap_config(args),
            dry_run=args.dry_run,
        )
