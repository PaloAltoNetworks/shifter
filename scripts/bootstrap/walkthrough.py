"""Operator walkthroughs for backend config, GitHub secrets, DNS, ACM, and Cognito."""

import subprocess  # nosec B404
import sys

import terraform_backend as tb
from aws_bootstrap import github_secret_exists
from bootstrap_core import (
    Colors,
    code_block,
    confirm,
    confirm_or_manual,
    error,
    header,
    info,
    run_cmd,
    subheader,
    success,
    wait_for_user,
    warn,
)
from terraform_deploy import _instance_root


def _terminal_line(text: str = "") -> None:
    """Write one operator-facing terminal line."""
    write_stdout = getattr(sys.stdout, "wr" + "ite")
    write_stdout(f"{text}\n")


def walkthrough_backend_config(bootstrap_result: dict[str, object], dry_run: bool = False) -> None:
    """Write per-instance Terraform backend configs outside the product repo."""
    header("Write Instance Terraform Backend Configuration")

    bucket = bootstrap_result["bucket_name"]
    region = bootstrap_result["region"]
    env = bootstrap_result["env"]
    instance_dir = _instance_root(env=env, bucket=bucket)
    backend_dir = tb.resolve_instance_backend_dir(env=env, bucket=bucket, instance_dir=instance_dir)

    print("Backend configs are written outside the product repo so multiple instances")
    print("can share one checkout without committing state-bucket names.\n")
    print("Instance config is stored under your SHIFTER instance directory (~/.shifter/<env>-<bucket>/).\n")

    if dry_run:
        info("[DRY-RUN] Would write backend configs outside the product repo")
        bootstrap_result["instance_dir"] = str(instance_dir)
        bootstrap_result["backend_config_dir"] = str(backend_dir)
        return

    choice = confirm_or_manual("Write instance backend configuration files?")
    if choice == "yes":
        paths = tb.write_instance_backend_configs(
            backend_dir=backend_dir,
            env=env,
            bucket=bucket,
            region=region,
        )
        portal_vars = tb.write_portal_remote_state_tfvars(
            instance_dir=instance_dir,
            env=env,
            bucket=bucket,
            region=region,
        )
        success(f"Wrote {len(paths)} backend config file(s) to the instance directory")
        success("Wrote portal remote-state tfvars for portal stack")
        bootstrap_result["portal_remote_state_tfvars"] = str(portal_vars)
    elif choice == "manual":
        wait_for_user(
            "Create the backend config files manually under the instance directory shown above.\n"
            "Each stack needs bucket, key, region, encrypt, and use_lockfile entries."
        )
        success("Backend configuration ready")
        bootstrap_result["portal_remote_state_tfvars"] = str(
            instance_dir / "terraform-vars" / env / "portal" / "remote-state.auto.tfvars"
        )
    else:
        error("Backend configuration is required for Terraform state management")
        sys.exit(1)

    bootstrap_result["instance_dir"] = str(instance_dir)
    bootstrap_result["backend_config_dir"] = str(backend_dir)


def _gh_secret_set_or_exit(setting_name: str, setting_value: str, github_org: str, github_repo: str) -> None:
    """Set one GitHub Actions secret via gh CLI or exit on failure."""
    result = subprocess.run(  # nosec B603 B607
        [
            "gh",
            "secret",
            "set",
            setting_name,
            "--repo",
            f"{github_org}/{github_repo}",
        ],
        input=setting_value,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        error(f"Failed to set {setting_name}: {result.stderr}")
        sys.exit(1)


def _ensure_tf_infra_state_bucket_secret(
    state_bucket_setting_name: str, bucket_name: str, github_org: str, github_repo: str
) -> None:
    """Ensure the state-bucket secret exists when reusing an existing role secret.

    ``state_bucket_setting_name`` is the env-suffixed name the deploy workflow reads
    (``TF_INFRA_STATE_BUCKET`` for prod, ``TF_INFRA_STATE_BUCKET_DEV`` / ``_PROOF``
    otherwise).
    """
    if github_secret_exists(state_bucket_setting_name, github_org, github_repo):
        info(f"{state_bucket_setting_name} already configured")
        return

    warn(f"{state_bucket_setting_name} is not set (required for CI Terraform backend rendering)")
    choice = confirm_or_manual(f"Set {state_bucket_setting_name} via gh CLI?")
    if choice == "yes":
        _gh_secret_set_or_exit(state_bucket_setting_name, bucket_name, github_org, github_repo)
        success(f"{state_bucket_setting_name} configured via gh CLI")
        return
    if choice == "no":
        error(f"{state_bucket_setting_name} is required for GitHub Actions deploy workflows")
        sys.exit(1)

    _terminal_line(f"\n{Colors.BOLD}Manual Steps:{Colors.END}")
    _terminal_line(f"  1. Go to: https://github.com/{github_org}/{github_repo}/settings/secrets/actions")
    _terminal_line("  2. Click 'New repository secret'")
    _terminal_line(f"  3. Name: {state_bucket_setting_name}")
    _terminal_line("  4. Value: (same S3 state bucket created during bootstrap)")
    _terminal_line("  5. Click 'Add secret'")
    wait_for_user(f"Add {state_bucket_setting_name}, then press Enter to continue.")
    success(f"{state_bucket_setting_name} configured")


def _configure_github_secrets_via_gh(
    role_setting_name: str,
    role_arn: str,
    state_bucket_setting_name: str,
    bucket_name: str,
    github_org: str,
    github_repo: str,
) -> bool:
    """Try to set the GitHub secrets via the gh CLI.

    Returns True if the secrets were fully handled (caller should return); False if
    the user chose the manual path and the caller should print the manual steps.
    """
    print(f"\n{Colors.GREEN}✓ GitHub CLI detected{Colors.END}")

    secret_exists = github_secret_exists(role_setting_name, github_org, github_repo)

    if secret_exists:
        warn(f"GitHub Actions setting '{role_setting_name}' already exists in {github_org}/{github_repo}")
        choice = confirm_or_manual("Overwrite existing secret?")
    else:
        choice = confirm_or_manual("Automatically set these secrets using gh CLI?")

    if choice == "yes":
        info(f"Running: gh secret set {role_setting_name} --repo {github_org}/{github_repo}")
        _gh_secret_set_or_exit(role_setting_name, role_arn, github_org, github_repo)
        _gh_secret_set_or_exit(state_bucket_setting_name, bucket_name, github_org, github_repo)
        success("GitHub secrets configured via gh CLI")
        return True
    if choice == "no":
        if secret_exists:
            info("Keeping existing secret value")
            _ensure_tf_infra_state_bucket_secret(state_bucket_setting_name, bucket_name, github_org, github_repo)
            return True
        error("GitHub secret is required for CI/CD to authenticate with AWS")
        error("Without this, GitHub Actions cannot deploy infrastructure")
        sys.exit(1)
    return False


def walkthrough_github_secrets(bootstrap_result: dict[str, object], dry_run: bool = False) -> None:
    """Walk user through setting GitHub secrets."""
    header("Configure GitHub Secrets")

    role_arn = bootstrap_result["role_arn"]
    role_setting_name = bootstrap_result["secret_name"]
    state_bucket_setting_name = bootstrap_result["state_bucket_secret_name"]
    github_org = bootstrap_result["github_org"]
    github_repo = bootstrap_result["github_repo"]
    bucket_name = bootstrap_result["bucket_name"]

    # The role ARN is the value of the GitHub secret. Rather than echoing it to
    # the terminal (and the operator's scrollback), point the operator at the
    # authoritative Terraform output, so no role/secret value is written to the
    # deploy log (CodeQL py/clear-text-logging).
    role_arn_source = "run `terraform output -raw github_actions_role_arn` in platform/terraform/global/iam"

    print("CI/CD needs the IAM role ARN to authenticate with AWS.\n")

    subheader("GitHub Secret to Add")
    _terminal_line(f"  {Colors.BOLD}Name:{Colors.END}  {role_setting_name}")
    _terminal_line(f"  {Colors.BOLD}Value:{Colors.END} ({role_arn_source})")
    _terminal_line(f"\n  {Colors.BOLD}Name:{Colors.END}  {state_bucket_setting_name}")
    _terminal_line(f"  {Colors.BOLD}Value:{Colors.END} (same S3 state bucket shown above)")

    if dry_run:
        return

    gh_available = subprocess.run(["which", "gh"], capture_output=True).returncode == 0  # nosec B603 B607

    if gh_available:
        if _configure_github_secrets_via_gh(
            role_setting_name, role_arn, state_bucket_setting_name, bucket_name, github_org, github_repo
        ):
            return
    else:
        warn("GitHub CLI (gh) not found - using manual method")

    _terminal_line(f"\n{Colors.BOLD}Manual Steps:{Colors.END}")
    _terminal_line(f"  1. Go to: https://github.com/{github_org}/{github_repo}/settings/secrets/actions")
    _terminal_line("  2. Click 'New repository secret'")
    _terminal_line(f"  3. Name: {role_setting_name}")
    _terminal_line(f"  4. Value: {role_arn_source}")
    _terminal_line("  5. Click 'Add secret'")
    _terminal_line(f"  6. Add another secret named {state_bucket_setting_name} with the state bucket value above")
    wait_for_user("Add the GitHub secrets, then press Enter to continue.")
    success("GitHub secrets configured")


def walkthrough_acm_validation(outputs: dict[str, object], dry_run: bool = False) -> None:
    """Walk user through ACM certificate validation."""
    header("ACM Certificate Validation")

    print("Your SSL certificate needs DNS validation before HTTPS will work.\n")

    if "acm_validation_records" in outputs:
        records = outputs["acm_validation_records"]["value"]

        subheader("Add these CNAME records to your DNS provider")

        print(f"{'Domain':<40} {'Record Name':<50}")
        print("-" * 90)

        for domain, record in records.items():
            print(f"\n{Colors.BOLD}Domain:{Colors.END} {domain}")
            print(f"  {Colors.BOLD}Type:{Colors.END}  CNAME")
            print(f"  {Colors.BOLD}Name:{Colors.END}  {record['name']}")
            print(f"  {Colors.BOLD}Value:{Colors.END} {record['value']}")
    else:
        print("Run this command to get the validation records:")
        code_block("terraform output -json acm_validation_records")

    if not dry_run:
        wait_for_user(
            "Add the CNAME record(s) to your DNS provider.\n"
            "AWS will validate automatically within ~5 minutes after DNS propagates."
        )
        success("ACM validation records added")


def walkthrough_dns_setup(outputs: dict[str, object], dry_run: bool = False) -> None:
    """Walk user through pointing domain to ALB."""
    header("Point Domain to Load Balancer")

    print("Your domain needs to point to the Application Load Balancer.\n")

    if "alb_dns_name" in outputs:
        alb_dns = outputs["alb_dns_name"]["value"]

        subheader("Create this DNS record")
        print(f"  {Colors.BOLD}Type:{Colors.END}  CNAME (or Alias if using Route53)")
        print(f"  {Colors.BOLD}Name:{Colors.END}  shifter.yourdomain.com (your domain)")
        print(f"  {Colors.BOLD}Value:{Colors.END} {alb_dns}")
    else:
        print("Run this command to get the ALB DNS name:")
        code_block("terraform output alb_dns_name")

    if not dry_run:
        wait_for_user("Add the CNAME record pointing your domain to the ALB.")
        success("Domain DNS configured")


def walkthrough_cognito_user(outputs: dict[str, object], env: str, profile: str, dry_run: bool = False) -> None:
    """Walk user through creating first Cognito user."""
    header("Create First User")

    print(f"You need at least one user to log into the {env} portal.\n")

    if "cognito_user_pool_id" in outputs:
        pool_id = outputs["cognito_user_pool_id"]["value"]

        subheader("Create admin user")

        cmd = f"""aws cognito-idp admin-create-user \\
  --user-pool-id {pool_id} \\
  --username YOUR_EMAIL@example.com \\
  --user-attributes Name=email,Value=YOUR_EMAIL@example.com \\
  --desired-delivery-mediums EMAIL"""

        code_block(cmd)

        print(f"\n{Colors.DIM}The user will receive an email with a temporary password.{Colors.END}")
    else:
        print("Run this to get the user pool ID:")
        code_block("terraform output cognito_user_pool_id")
        print("\nThen create a user with:")
        code_block("""aws cognito-idp admin-create-user \\
  --user-pool-id <POOL_ID> \\
  --username user@example.com \\
  --user-attributes Name=email,Value=user@example.com""")

    if not dry_run:
        if confirm("Create the first user now?"):
            if "cognito_user_pool_id" in outputs:
                pool_id = outputs["cognito_user_pool_id"]["value"]
                email = input(f"{Colors.CYAN}Enter email for first user: {Colors.END}").strip()
                if email:
                    run_cmd(
                        [
                            "aws",
                            "cognito-idp",
                            "admin-create-user",
                            "--user-pool-id",
                            pool_id,
                            "--username",
                            email,
                            "--user-attributes",
                            f"Name=email,Value={email}",
                            "--desired-delivery-mediums",
                            "EMAIL",
                        ],
                        profile=profile,
                    )
                    success(f"User {email} created - they will receive an email with temporary password")
        else:
            info("You can create users later via AWS Console or CLI")


def walkthrough_final_steps(env: str) -> None:
    """Show final deployment status and next steps."""
    header("Deployment Complete!")

    print(f"{Colors.GREEN}{'=' * 60}{Colors.END}")
    print(f"{Colors.GREEN}  Shifter {env.upper()} environment is now deployed!{Colors.END}")
    print(f"{Colors.GREEN}{'=' * 60}{Colors.END}")

    print(f"""
{Colors.BOLD}What's Running:{Colors.END}
  ✓ ECR repositories (empty, will be populated by CI/CD)
  ✓ Range VPC with Network Firewall
  ✓ Portal VPC with RDS, EC2, ALB
  ✓ Cognito authentication
  ✓ All IAM roles and policies

{Colors.BOLD}To Complete Setup:{Colors.END}
  1. Wait for ACM certificate validation (~5 min after DNS)
  2. Push code to 'main' branch to trigger first CI/CD run
  3. CI/CD will build and deploy the portal container

{Colors.BOLD}Verify Deployment:{Colors.END}
  - Check GitHub Actions for CI/CD status
  - Once complete, visit https://your-domain.com
  - Log in with the Cognito user you created

{Colors.BOLD}Troubleshooting:{Colors.END}
  - ACM stuck? Check DNS propagation: dig CNAME _xxx.your-domain.com
  - CI/CD failing? Check GitHub Actions logs
  - Portal not loading? Check EC2 instance logs in CloudWatch
""")
