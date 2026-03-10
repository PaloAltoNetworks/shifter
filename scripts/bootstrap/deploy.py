#!/usr/bin/env python3
"""Shifter deployment CLI.

Guides you through deploying Shifter infrastructure from a bare AWS account.

Features:
- Interactive prompts with automated options (via gh CLI, git)
- Confirmation before any changes (yes/no/manual)
- Dry-run mode to preview without making changes
- Manual fallback for all steps

Usage:
    ./scripts/bootstrap/deploy.py bootstrap --env prod --profile my-prod-profile
    ./scripts/bootstrap/deploy.py bootstrap --env prod --profile my-prod-profile --dry-run
    ./scripts/bootstrap/deploy.py terraform --env prod --profile my-prod-profile
    ./scripts/bootstrap/deploy.py terraform --env prod --profile my-prod-profile --dry-run
    ./scripts/bootstrap/deploy.py full --env prod --profile my-prod-profile
"""

import argparse
import json
import os
import re
import shutil
import subprocess  # nosec B404
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path

# Import runner setup module
try:
    from runner import get_runner_config, walkthrough_runner_setup

    RUNNER_AVAILABLE = True
except ImportError:
    RUNNER_AVAILABLE = False


# Colors for terminal output
class Colors:
    HEADER = "\033[95m"
    BLUE = "\033[94m"
    CYAN = "\033[96m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    END = "\033[0m"


def info(msg: str) -> None:
    print(f"{Colors.CYAN}ℹ {msg}{Colors.END}")


def success(msg: str) -> None:
    print(f"{Colors.GREEN}✓ {msg}{Colors.END}")


def warn(msg: str) -> None:
    print(f"{Colors.YELLOW}⚠ {msg}{Colors.END}")


def error(msg: str) -> None:
    print(f"{Colors.RED}✗ {msg}{Colors.END}")


def header(msg: str) -> None:
    print(f"\n{Colors.BOLD}{Colors.HEADER}{'=' * 60}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.HEADER}{msg}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.HEADER}{'=' * 60}{Colors.END}\n")


def subheader(msg: str) -> None:
    print(f"\n{Colors.BOLD}{Colors.CYAN}--- {msg} ---{Colors.END}\n")


def code_block(text: str) -> None:
    """Print a code block with dimmed formatting."""
    print(f"{Colors.DIM}┌{'─' * 58}┐{Colors.END}")
    for line in text.strip().split("\n"):
        print(f"{Colors.DIM}│{Colors.END} {line}")
    print(f"{Colors.DIM}└{'─' * 58}┘{Colors.END}")


def confirm(msg: str, default_yes: bool = False) -> bool:
    """Prompt for yes/no confirmation. Returns default_yes if not interactive."""
    # Check if we're in a non-interactive environment
    if not sys.stdin.isatty():
        return default_yes

    while True:
        response = input(f"{Colors.YELLOW}{msg} [y/N]: {Colors.END}").strip().lower()
        if response in ("y", "yes"):
            return True
        if response in ("n", "no", ""):
            return False
        print("Please enter 'y' or 'n'")


def confirm_or_manual(msg: str) -> str:
    """Prompt for yes/no/manual. Returns 'yes', 'no', or 'manual'.

    Note: 'no' will cause the script to abort with an error explanation,
    as all steps are required for a functioning deployment.
    """
    # Check if we're in a non-interactive environment
    if not sys.stdin.isatty():
        return "manual"

    while True:
        response = input(f"{Colors.YELLOW}{msg} [y/n/m]: {Colors.END}").strip().lower()
        if response in ("y", "yes"):
            return "yes"
        if response in ("n", "no"):
            return "no"
        if response in ("m", "manual"):
            return "manual"
        print("Please enter 'y' (yes), 'n' (no - will abort), or 'm' (manual)")


def wait_for_user(msg: str) -> None:
    """Wait for user to confirm they've completed a manual step."""
    # Skip in non-interactive mode
    if not sys.stdin.isatty():
        print(f"\n{Colors.BOLD}{Colors.YELLOW}ACTION REQUIRED:{Colors.END}")
        print(f"{msg}\n")
        print(f"{Colors.DIM}[Non-interactive mode - skipping prompt]{Colors.END}")
        return

    print(f"\n{Colors.BOLD}{Colors.YELLOW}ACTION REQUIRED:{Colors.END}")
    print(f"{msg}\n")
    while True:
        response = input(f"{Colors.GREEN}Press Enter when done (or 'skip' to skip): {Colors.END}").strip().lower()
        if response == "":
            return
        if response == "skip":
            warn("Step skipped - you'll need to complete this manually later")
            return
        print("Press Enter to continue, or type 'skip' to skip this step")


def run_cmd(
    cmd: list[str],
    dry_run: bool = False,
    check: bool = True,
    capture: bool = False,
    profile: str = None,
) -> subprocess.CompletedProcess | None:
    """Run a command, optionally in dry-run mode."""
    # Insert --profile flag for AWS CLI commands
    if profile and cmd[0] == "aws":
        cmd = cmd[:1] + ["--profile", profile] + cmd[1:]

    cmd_str = " ".join(cmd)
    if dry_run:
        print(f"{Colors.BLUE}[DRY-RUN] Would run: {cmd_str}{Colors.END}")
        return None

    info(f"Running: {cmd_str}")
    try:
        if capture:
            result = subprocess.run(cmd, check=check, capture_output=True, text=True)  # nosec B603 B607
        else:
            result = subprocess.run(cmd, check=check, text=True)  # nosec B603 B607
        return result
    except subprocess.CalledProcessError as e:
        error(f"Command failed: {e}")
        if hasattr(e, "stderr") and e.stderr:
            print(e.stderr)
        if check:
            sys.exit(1)
        return None


def get_aws_account_id(profile: str = None) -> str:
    """Get current AWS account ID."""
    cmd = ["aws", "sts", "get-caller-identity", "--query", "Account", "--output", "text"]
    if profile:
        cmd = ["aws", "--profile", profile, "sts", "get-caller-identity", "--query", "Account", "--output", "text"]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)  # nosec B603 B607
    return result.stdout.strip()


def get_repo_root() -> Path:
    """Get the repository root directory."""
    return Path(__file__).parent.parent.parent


def s3_bucket_exists(bucket_name: str, profile: str) -> bool:
    """Check if an S3 bucket exists."""
    result = subprocess.run(  # nosec B603 B607
        ["aws", "--profile", profile, "s3api", "head-bucket", "--bucket", bucket_name],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def dynamodb_table_exists(table_name: str, region: str, profile: str) -> bool:
    """Check if a DynamoDB table exists."""
    result = subprocess.run(  # nosec B603 B607
        [
            "aws",
            "--profile",
            profile,
            "dynamodb",
            "describe-table",
            "--table-name",
            table_name,
            "--region",
            region,
        ],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def github_secret_exists(secret_name: str, github_org: str, github_repo: str) -> bool:
    """Check if a GitHub secret exists."""
    result = subprocess.run(  # nosec B603 B607
        ["gh", "secret", "list", "--repo", f"{github_org}/{github_repo}"],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0 and result.stdout is not None and secret_name in result.stdout


def create_s3_bucket(bucket_name: str, region: str, profile: str, dry_run: bool) -> None:
    """Create and configure an S3 bucket for Terraform state."""
    run_cmd(
        [
            "aws",
            "s3api",
            "create-bucket",
            "--bucket",
            bucket_name,
            "--region",
            region,
            "--create-bucket-configuration",
            f"LocationConstraint={region}",
        ],
        dry_run=dry_run,
        profile=profile,
    )

    run_cmd(
        [
            "aws",
            "s3api",
            "put-bucket-versioning",
            "--bucket",
            bucket_name,
            "--versioning-configuration",
            "Status=Enabled",
        ],
        dry_run=dry_run,
        profile=profile,
    )

    run_cmd(
        [
            "aws",
            "s3api",
            "put-bucket-encryption",
            "--bucket",
            bucket_name,
            "--server-side-encryption-configuration",
            '{"Rules": [{"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}]}',
        ],
        dry_run=dry_run,
        profile=profile,
    )

    run_cmd(
        [
            "aws",
            "s3api",
            "put-public-access-block",
            "--bucket",
            bucket_name,
            "--public-access-block-configuration",
            (
                '{"BlockPublicAcls": true, "IgnorePublicAcls": true, '
                '"BlockPublicPolicy": true, "RestrictPublicBuckets": true}'
            ),
        ],
        dry_run=dry_run,
        profile=profile,
    )


def create_dynamodb_table(table_name: str, region: str, profile: str, dry_run: bool) -> None:
    """Create a DynamoDB table for Terraform state locking."""
    run_cmd(
        [
            "aws",
            "dynamodb",
            "create-table",
            "--table-name",
            table_name,
            "--attribute-definitions",
            "AttributeName=LockID,AttributeType=S",
            "--key-schema",
            "AttributeName=LockID,KeyType=HASH",
            "--billing-mode",
            "PAY_PER_REQUEST",
            "--region",
            region,
        ],
        dry_run=dry_run,
        profile=profile,
    )

    if not dry_run:
        info("Waiting for table to be active...")
        run_cmd(
            ["aws", "dynamodb", "wait", "table-exists", "--table-name", table_name, "--region", region],
            profile=profile,
        )


@dataclass
class BootstrapConfig:
    env: str
    region: str = "us-east-2"  # TODO: Make configurable via CLI argument if multi-region support needed
    github_org: str = "Brad-Edwards"  # USER-SPECIFIC: Change to your GitHub organization
    github_repo: str = "shifter"  # USER-SPECIFIC: Change to your repository name

    @property
    def bucket_prefix(self) -> str:
        return "shifter-infra" if self.env == "prod" else f"shifter-{self.env}-infra"

    @property
    def table_prefix(self) -> str:
        return "shifter-terraform" if self.env == "prod" else f"shifter-{self.env}-terraform"

    @property
    def bootstrap_role_name(self) -> str:
        """Temporary bootstrap role - deleted after terraform creates the real one."""
        return f"github-actions-shifter-{self.env}-bootstrap"

    @property
    def role_name(self) -> str:
        """Production role managed by Terraform - never touched by this script."""
        return f"github-actions-shifter-{self.env}"

    @property
    def secret_name(self) -> str:
        return "AWS_ROLE_ARN" if self.env == "prod" else "AWS_ROLE_ARN_DEV"


def bootstrap_account(config: BootstrapConfig, profile: str, dry_run: bool = False) -> dict:
    """Bootstrap AWS account with state backend and IAM role."""
    header(f"Bootstrapping {config.env.upper()} AWS Account")

    info(f"Using AWS Profile: {profile}")

    # Get account ID
    if not dry_run:
        account_id = get_aws_account_id(profile)
        info(f"AWS Account ID: {account_id}")
    else:
        account_id = "123456789012"
        info("[DRY-RUN] Would get AWS account ID")

    # Generate UUID for uniqueness
    uid = str(uuid.uuid4())
    bucket_name = f"{config.bucket_prefix}-{uid}"
    table_name = f"{config.table_prefix}-{uid}"

    info(f"S3 Bucket: {bucket_name}")
    info(f"DynamoDB Table: {table_name}")
    info(f"IAM Role: {config.role_name}")

    if not dry_run and not confirm("Create these resources?"):
        warn("Aborted by user")
        sys.exit(0)

    # Step 1: S3 Bucket
    header("Step 1/4: Creating S3 Bucket")

    if not dry_run and s3_bucket_exists(bucket_name, profile):
        warn(f"S3 bucket '{bucket_name}' already exists")
        if not confirm("Continue using existing bucket?"):
            error("Cannot continue without S3 bucket for Terraform state")
            sys.exit(1)
        info("Using existing bucket")
    else:
        create_s3_bucket(bucket_name, config.region, profile, dry_run)

    success("S3 bucket ready")

    # Step 2: DynamoDB Table
    header("Step 2/4: Creating DynamoDB Table")

    if not dry_run and dynamodb_table_exists(table_name, config.region, profile):
        warn(f"DynamoDB table '{table_name}' already exists")
        if not confirm("Continue using existing table?"):
            error("Cannot continue without DynamoDB table for Terraform state locking")
            sys.exit(1)
        info("Using existing table")
    else:
        create_dynamodb_table(table_name, config.region, profile, dry_run)

    success("DynamoDB table ready")

    # Step 3: Bootstrap IAM Role (temporary - will be replaced by Terraform)
    header("Step 3/4: Creating Bootstrap IAM Role")

    # Construct OIDC ARN - the provider will be created by Terraform, but the ARN format is deterministic
    # Format: arn:aws:iam::<account_id>:oidc-provider/token.actions.githubusercontent.com
    oidc_arn = f"arn:aws:iam::{account_id}:oidc-provider/token.actions.githubusercontent.com"

    # OIDC Trust Policy for GitHub Actions
    # VERIFIED OFFICIAL VALUES (Brad Edwards, 2026-01-02):
    # - token.actions.githubusercontent.com:aud must be "sts.amazonaws.com"
    # - token.actions.githubusercontent.com:sub format: "repo:ORG/REPO:*"
    # Source: https://docs.github.com/en/actions/deployment/security-hardening-your-deployments/configuring-openid-connect-in-amazon-web-services
    trust_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"Federated": oidc_arn},
                "Action": "sts:AssumeRoleWithWebIdentity",
                "Condition": {
                    "StringEquals": {"token.actions.githubusercontent.com:aud": "sts.amazonaws.com"},
                    "StringLike": {
                        "token.actions.githubusercontent.com:sub": (f"repo:{config.github_org}/{config.github_repo}:*")
                    },
                },
            }
        ],
    }

    info(f"Creating temporary bootstrap role: {config.bootstrap_role_name}")
    info("This role will be deleted after Terraform creates the production role")

    run_cmd(
        [
            "aws",
            "iam",
            "create-role",
            "--role-name",
            config.bootstrap_role_name,
            "--assume-role-policy-document",
            json.dumps(trust_policy),
            "--tags",
            f"Key=Name,Value={config.bootstrap_role_name}",
            "Key=Project,Value=shifter",
            "Key=Purpose,Value=bootstrap-temporary",
        ],
        dry_run=dry_run,
        check=False,  # May already exist
        profile=profile,
    )

    # Attach AdministratorAccess to bootstrap role (temporary, will be deleted)
    run_cmd(
        [
            "aws",
            "iam",
            "attach-role-policy",
            "--role-name",
            config.bootstrap_role_name,
            "--policy-arn",
            "arn:aws:iam::aws:policy/AdministratorAccess",
        ],
        dry_run=dry_run,
        profile=profile,
    )

    success("Bootstrap IAM role created with AdministratorAccess")

    # Step 4: Run Terraform to create OIDC provider and production IAM role
    header("Step 4/4: Creating OIDC Provider and IAM Role via Terraform")

    info("Running Terraform to create properly scoped IAM policies...")
    info("The production role will be: " + config.role_name)

    repo_root = get_repo_root()
    iam_tf_dir = repo_root / "platform" / "terraform" / "global" / "iam"

    if not iam_tf_dir.exists():
        error(f"IAM Terraform directory not found: {iam_tf_dir}")
        sys.exit(1)

    # Update the backend config file for this environment with the new bucket/table
    backend_config_file = iam_tf_dir / f"{config.env}.s3.tfbackend"
    backend_config_content = f"""bucket         = "{bucket_name}"
key            = "global/iam/terraform.tfstate"
region         = "{config.region}"
dynamodb_table = "{table_name}"
encrypt        = true
"""
    if not dry_run:
        info(f"Updating backend config: {backend_config_file}")
        backend_config_file.write_text(backend_config_content)
        success(f"Backend config updated for {config.env}")
    else:
        info(f"[DRY-RUN] Would update {backend_config_file}")

    original_dir = os.getcwd()
    os.chdir(iam_tf_dir)

    # Set AWS_PROFILE for Terraform (only affects this process and its children)
    os.environ["AWS_PROFILE"] = profile

    try:
        # Terraform init with backend config for environment
        backend_config = f"{config.env}.s3.tfbackend"
        info(f"Running terraform init with backend config: {backend_config}")
        run_cmd(
            ["terraform", "init", "-reconfigure", f"-backend-config={backend_config}"],
            dry_run=dry_run,
        )

        # Terraform apply with auto-approve (we already confirmed at start)
        info(f"Running terraform apply for {config.env}...")
        tfvars_file = f"{config.env}.tfvars"

        if not dry_run:
            apply_result = run_cmd(
                ["terraform", "apply", "-auto-approve", f"-var-file={tfvars_file}"],
                dry_run=dry_run,
                check=False,
            )
            if apply_result and apply_result.returncode != 0:
                error("Terraform apply failed for IAM module")
                error("The bootstrap role is still active - you can retry manually")
                sys.exit(1)
        else:
            run_cmd(["terraform", "plan", f"-var-file={tfvars_file}"], dry_run=dry_run)

        # Get role ARN from terraform output
        if not dry_run:
            result = subprocess.run(  # nosec B603 B607
                ["terraform", "output", "-raw", "github_actions_role_arn"],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                error("Failed to get role ARN from Terraform output")
                sys.exit(1)
            role_arn = result.stdout.strip()
            success(f"Production IAM role created: {role_arn}")
        else:
            role_arn = f"arn:aws:iam::{account_id}:role/{config.role_name}"

    finally:
        os.chdir(original_dir)

    # Cleanup: Delete the bootstrap role
    header("Cleanup: Removing Bootstrap Role")

    info(f"Deleting temporary bootstrap role: {config.bootstrap_role_name}")

    # Detach AdministratorAccess first
    run_cmd(
        [
            "aws",
            "iam",
            "detach-role-policy",
            "--role-name",
            config.bootstrap_role_name,
            "--policy-arn",
            "arn:aws:iam::aws:policy/AdministratorAccess",
        ],
        dry_run=dry_run,
        check=False,
        profile=profile,
    )

    # Delete the role
    run_cmd(
        [
            "aws",
            "iam",
            "delete-role",
            "--role-name",
            config.bootstrap_role_name,
        ],
        dry_run=dry_run,
        check=False,
        profile=profile,
    )

    success("Bootstrap role deleted - using Terraform-managed role going forward")

    return {
        "bucket_name": bucket_name,
        "table_name": table_name,
        "role_arn": role_arn,
        "region": config.region,
        "env": config.env,
        "secret_name": config.secret_name,
        "github_org": config.github_org,
        "github_repo": config.github_repo,
    }


def walkthrough_github_secrets(bootstrap_result: dict, dry_run: bool = False) -> None:
    """Walk user through setting GitHub secrets."""
    header("Configure GitHub Secrets")

    role_arn = bootstrap_result["role_arn"]
    secret_name = bootstrap_result["secret_name"]
    github_org = bootstrap_result["github_org"]
    github_repo = bootstrap_result["github_repo"]

    print("CI/CD needs the IAM role ARN to authenticate with AWS.\n")

    subheader("GitHub Secret to Add")
    print(f"  {Colors.BOLD}Name:{Colors.END}  {secret_name}")
    print(f"  {Colors.BOLD}Value:{Colors.END} {role_arn}")

    if not dry_run:
        # Check if gh CLI is available
        gh_available = subprocess.run(["which", "gh"], capture_output=True).returncode == 0  # nosec B603 B607

        if gh_available:
            print(f"\n{Colors.GREEN}✓ GitHub CLI detected{Colors.END}")

            secret_exists = github_secret_exists(secret_name, github_org, github_repo)

            if secret_exists:
                warn(f"Secret '{secret_name}' already exists in {github_org}/{github_repo}")
                choice = confirm_or_manual("Overwrite existing secret?")
            else:
                choice = confirm_or_manual("Automatically set this secret using gh CLI?")

            if choice == "yes":
                info(f"Running: gh secret set {secret_name} --repo {github_org}/{github_repo}")
                result = subprocess.run(  # nosec B603 B607
                    ["gh", "secret", "set", secret_name, "--body", role_arn, "--repo", f"{github_org}/{github_repo}"],
                    capture_output=True,
                    text=True,
                )
                if result.returncode == 0:
                    success("GitHub secret configured via gh CLI")
                    return
                else:
                    error(f"Failed to set secret: {result.stderr}")
                    error("GitHub CLI command failed")
                    error("Try manual method or fix gh authentication")
                    sys.exit(1)
            elif choice == "no":
                if secret_exists:
                    info("Keeping existing secret value")
                    return
                error("GitHub secret is required for CI/CD to authenticate with AWS")
                error("Without this, GitHub Actions cannot deploy infrastructure")
                sys.exit(1)
            # If manual, fall through to manual instructions
        else:
            warn("GitHub CLI (gh) not found - using manual method")

        # Manual method
        print(f"\n{Colors.BOLD}Manual Steps:{Colors.END}")
        print(f"  1. Go to: https://github.com/{github_org}/{github_repo}/settings/secrets/actions")
        print("  2. Click 'New repository secret'")
        print(f"  3. Name: {secret_name}")
        print(f"  4. Value: {role_arn}")
        print("  5. Click 'Add secret'")
        wait_for_user("Add the GitHub secret, then press Enter to continue.")
        success("GitHub secret configured")


def walkthrough_backend_config(bootstrap_result: dict, dry_run: bool = False) -> None:
    """Update backend.tf files with S3 backend configuration."""
    header("Update Terraform Backend Configuration")

    bucket = bootstrap_result["bucket_name"]
    table = bootstrap_result["table_name"]
    region = bootstrap_result["region"]
    env = bootstrap_result["env"]

    repo_root = get_repo_root()

    print("Updating backend.tf files with S3 state configuration.\n")
    print("These files configure where Terraform stores infrastructure state.\n")

    # Backend configurations for each component
    # Note: Core uses shifter/{env}/, but portal/range use {env}/ (historical convention)
    # Core needs full provider config in backend.tf; portal/range have it in main.tf
    files_to_write = []

    # Core backend.tf - needs full terraform block with provider config
    core_path = f"platform/terraform/environments/{env}/backend.tf"
    core_config = f'''terraform {{
  backend "s3" {{
    bucket         = "{bucket}"
    key            = "shifter/{env}/terraform.tfstate"
    region         = "{region}"
    dynamodb_table = "{table}"
    encrypt        = true
  }}

  required_version = ">= 1.0"

  required_providers {{
    aws = {{
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }}
  }}
}}

provider "aws" {{
  region = var.aws_region

  default_tags {{
    tags = {{
      Environment = "{env}"
      Project     = "shifter"
      ManagedBy   = "terraform"
    }}
  }}
}}
'''
    files_to_write.append((core_path, repo_root / core_path, core_config))

    # Portal and Range backend.tf - just the backend block (provider in main.tf)
    for component, state_key in [
        ("portal", f"{env}/portal/terraform.tfstate"),
        ("range", f"{env}/range/terraform.tfstate"),
    ]:
        filepath = f"platform/terraform/environments/{env}/{component}/backend.tf"
        backend_config = f'''terraform {{
  backend "s3" {{
    bucket         = "{bucket}"
    key            = "{state_key}"
    region         = "{region}"
    dynamodb_table = "{table}"
    encrypt        = true
  }}
}}
'''
        files_to_write.append((filepath, repo_root / filepath, backend_config))

    # Show what will be written
    for filepath, full_path, backend_config in files_to_write:
        subheader(filepath)
        code_block(backend_config.strip())
        if full_path.exists():
            warn(f"File exists (will be overwritten): {full_path}")

    if not dry_run:
        choice = confirm_or_manual("Write these backend.tf files?")

        if choice == "yes":
            for filepath, full_path, backend_config in files_to_write:
                try:
                    full_path.parent.mkdir(parents=True, exist_ok=True)
                    full_path.write_text(backend_config)
                    success(f"Wrote {filepath}")
                except Exception as e:
                    error(f"Failed to write {filepath}: {e}")
                    error("Cannot continue without backend configuration files")
                    sys.exit(1)

            success("Backend configuration files updated")

        elif choice == "manual":
            wait_for_user(
                "Update the backend.tf files shown above manually.\nYou can copy the content directly into each file."
            )
            success("Backend configuration ready")
        else:
            error("Backend configuration is required for Terraform state management")
            error("Without this, Terraform cannot store or track infrastructure state")
            sys.exit(1)

    # Update terraform_remote_state bucket references in portal/main.tf
    _update_remote_state_references(env, bucket, region, dry_run)

    # Update global module backend configs and hardcoded bucket references
    _update_global_backend_configs(env, bucket, table, region, dry_run)


def _update_global_backend_configs(env: str, bucket: str, table: str, region: str, dry_run: bool = False) -> None:
    """Update .tfbackend files and hardcoded bucket refs under global/."""
    repo_root = get_repo_root()
    global_dir = repo_root / "platform" / "terraform" / "global"

    if not global_dir.exists():
        return

    subheader("Update Global Module Backend Configs")
    print("Scanning global/ for .tfbackend files and hardcoded bucket references")
    print("that need to match the new state backend.\n")

    updated_files = []

    # Pattern to match old shifter bucket names with UUIDs
    bucket_pattern = re.compile(r"shifter-(?:\w+-)?infra-[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}")
    table_pattern = re.compile(r"shifter-(?:\w+-)?terraform-[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}")

    for tf_file in sorted(global_dir.rglob(f"{env}.s3.tfbackend")):
        content = tf_file.read_text()
        new_content = bucket_pattern.sub(bucket, content)
        new_content = table_pattern.sub(table, new_content)
        if new_content != content:
            rel_path = tf_file.relative_to(repo_root)
            updated_files.append((tf_file, rel_path, new_content))

    for tf_file in sorted(global_dir.rglob("*.tf")):
        content = tf_file.read_text()
        new_content = bucket_pattern.sub(bucket, content)
        if new_content != content:
            rel_path = tf_file.relative_to(repo_root)
            updated_files.append((tf_file, rel_path, new_content))

    if not updated_files:
        info("No global backend configs need updating")
        return

    for _, rel_path, _ in updated_files:
        info(f"  Will update: {rel_path}")

    if not dry_run:
        if confirm(f"Update {len(updated_files)} global backend config(s)?"):
            for tf_file, rel_path, new_content in updated_files:
                try:
                    tf_file.write_text(new_content)
                    success(f"Updated {rel_path}")
                except Exception as e:
                    error(f"Failed to update {rel_path}: {e}")
        else:
            warn("Skipping global backend updates - you'll need to update them manually")
    else:
        info(f"[DRY-RUN] Would update {len(updated_files)} file(s)")


def _update_remote_state_references(env: str, bucket: str, region: str, dry_run: bool = False) -> None:
    """Update terraform_remote_state bucket references in portal/main.tf."""
    repo_root = get_repo_root()
    portal_main_tf = repo_root / f"platform/terraform/environments/{env}/portal/main.tf"

    if not portal_main_tf.exists():
        warn(f"Portal main.tf not found at {portal_main_tf}, skipping remote_state updates")
        return

    subheader("Update terraform_remote_state References")
    print("Portal's main.tf contains terraform_remote_state data sources that reference")
    print("the S3 bucket. These need to be updated with the new bucket name.\n")

    content = portal_main_tf.read_text()
    original_content = content

    # Find and replace bucket references in terraform_remote_state blocks
    # Match: bucket = "shifter-*" within config blocks
    pattern = r'(data\s+"terraform_remote_state".*?config\s*=\s*\{[^}]*bucket\s*=\s*)"[^"]*"'

    def replace_bucket(match):
        return f'{match.group(1)}"{bucket}"'

    new_content = re.sub(pattern, replace_bucket, content, flags=re.DOTALL)

    if new_content == original_content:
        info("No terraform_remote_state bucket references found or already up to date")
        return

    # Show what will change
    print(f"Will update bucket references in: {portal_main_tf.relative_to(repo_root)}")
    print("  Old: shifter-*-...-...")
    print(f"  New: {bucket}\n")

    if not dry_run:
        if confirm("Update terraform_remote_state bucket references?"):
            try:
                portal_main_tf.write_text(new_content)
                success("Updated terraform_remote_state bucket references")
            except Exception as e:
                error(f"Failed to update portal/main.tf: {e}")
                error("You may need to manually update the bucket references")
        else:
            warn("Skipping remote_state updates - you'll need to update them manually")


def terraform_deploy(env: str, profile: str, dry_run: bool = False) -> dict:
    """Deploy all Terraform components in order."""
    header(f"Deploying {env.upper()} Infrastructure")

    # Set AWS_PROFILE for Terraform (only affects this process and its children)
    os.environ["AWS_PROFILE"] = profile

    components = [
        ("core", "ECR repositories"),
        ("range", "Range VPC + Pulumi state"),
        ("portal", "Portal infrastructure (VPC, RDS, EC2, ALB, Cognito)"),
    ]

    outputs = {}

    for i, (component, description) in enumerate(components, 1):
        header(f"Step {i}/{len(components)}: {description}")
        info(f"Component: {component}")

        if not dry_run and not confirm(f"Deploy {component}?"):
            error(f"{component.title()} deployment is required")
            if component == "core":
                error("Core creates ECR repositories needed for container images")
            elif component == "range":
                error("Range VPC is required for isolated attack/defense environments")
            elif component == "portal":
                error("Portal is the main application infrastructure")
            sys.exit(1)

        base_path = get_repo_root() / "platform" / "terraform" / "environments" / env
        tf_dir = base_path if component == "core" else base_path / component

        if not tf_dir.exists():
            error(f"Directory not found: {tf_dir}")
            continue

        # Change to terraform directory
        original_dir = os.getcwd()
        os.chdir(tf_dir)

        try:
            # Init with -reconfigure (backend config is in backend.tf)
            info("Running terraform init...")
            init_result = run_cmd(
                ["terraform", "init", "-reconfigure"],
                dry_run=dry_run,
            )
            if not dry_run and init_result and init_result.returncode != 0:
                error(f"Terraform init failed for {component}")
                error("Check that backend.tf exists and is correctly configured")
                sys.exit(1)

            # Plan
            info("Running terraform plan...")
            plan_result = run_cmd(["terraform", "plan", "-out=tfplan"], dry_run=dry_run)
            if not dry_run and plan_result and plan_result.returncode != 0:
                error(f"Terraform plan failed for {component}")
                error("Review errors above and fix before continuing")
                sys.exit(1)

            if not dry_run:
                # Show plan summary
                print(f"\n{Colors.BOLD}Plan Summary:{Colors.END}")
                subprocess.run(["terraform", "show", "-no-color", "tfplan"], check=False)  # nosec B603 B607

                if not confirm("\nApply this plan?"):
                    error(f"Terraform apply for {component} is required")
                    error("All infrastructure components are mandatory for Shifter to function")
                    sys.exit(1)

                # Apply
                info("Running terraform apply...")
                apply_result = run_cmd(["terraform", "apply", "tfplan"])

                if apply_result and apply_result.returncode != 0:
                    error(f"Terraform apply failed for {component}")
                    error("Infrastructure deployment incomplete")
                    sys.exit(1)

                success(f"{component} deployed successfully")

                # Capture outputs for portal
                if component == "portal":
                    result = subprocess.run(  # nosec B603 B607
                        ["terraform", "output", "-json"], capture_output=True, text=True, check=False
                    )
                    if result.returncode == 0:
                        outputs = json.loads(result.stdout)
        finally:
            os.chdir(original_dir)

    return outputs


def walkthrough_acm_validation(outputs: dict, dry_run: bool = False) -> None:
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


def walkthrough_dns_setup(outputs: dict, dry_run: bool = False) -> None:
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


def walkthrough_cognito_user(outputs: dict, env: str, profile: str, dry_run: bool = False) -> None:
    """Walk user through creating first Cognito user."""
    header("Create First User")

    print("You need at least one user to log into the portal.\n")

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


def full_deployment(env: str, profile: str, dry_run: bool = False) -> None:
    """Run complete deployment with interactive walkthrough."""
    header(f"Full {env.upper()} Deployment")

    print("""
This will guide you through a complete Shifter deployment:

  1. Bootstrap AWS account (S3, DynamoDB, IAM)
  2. Configure GitHub secrets (automated with gh CLI or manual)
  3. Update Terraform backend configuration (automated or manual)
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

    outputs = terraform_deploy(env, profile, dry_run=dry_run)

    if not dry_run and outputs:
        # Phase 6: ACM Validation
        walkthrough_acm_validation(outputs, dry_run=dry_run)

        # Phase 7: DNS Setup
        walkthrough_dns_setup(outputs, dry_run=dry_run)

        # Phase 8: First User
        walkthrough_cognito_user(outputs, env, profile, dry_run=dry_run)

    # Final Summary
    walkthrough_final_steps(env)


def check_dependencies():
    """Check all required dependencies before starting."""
    required = {
        "aws": "AWS CLI - https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html",
        "terraform": "Terraform - https://developer.hashicorp.com/terraform/downloads",
        "git": "Git - https://git-scm.com/downloads",
    }

    optional = {"gh": "GitHub CLI - https://cli.github.com/ (recommended for automating GitHub secrets)"}

    missing_required = []
    missing_optional = []

    for cmd, desc in required.items():
        if not shutil.which(cmd):
            missing_required.append(f"  - {cmd}: {desc}")

    for cmd, desc in optional.items():
        if not shutil.which(cmd):
            missing_optional.append(f"  - {cmd}: {desc}")

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


def main():
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
        """,
    )

    # Check dependencies first
    check_dependencies()

    subparsers = parser.add_subparsers(dest="command", required=True)

    # Bootstrap command
    bootstrap_parser = subparsers.add_parser("bootstrap", help="Bootstrap AWS account (S3, DynamoDB, IAM)")
    bootstrap_parser.add_argument("--env", required=True, choices=["dev", "prod"], help="Environment")
    bootstrap_parser.add_argument("--profile", required=True, help="AWS CLI profile name")
    bootstrap_parser.add_argument("--dry-run", action="store_true", help="Show what would be done")

    # Terraform command
    tf_parser = subparsers.add_parser("terraform", help="Deploy Terraform infrastructure")
    tf_parser.add_argument("--env", required=True, choices=["dev", "prod"], help="Environment")
    tf_parser.add_argument("--profile", required=True, help="AWS CLI profile name")
    tf_parser.add_argument("--dry-run", action="store_true", help="Show what would be done")

    # Full command
    full_parser = subparsers.add_parser("full", help="Full interactive deployment (bootstrap + config + terraform)")
    full_parser.add_argument("--env", required=True, choices=["dev", "prod"], help="Environment")
    full_parser.add_argument("--profile", required=True, help="AWS CLI profile name")
    full_parser.add_argument("--dry-run", action="store_true", help="Show what would be done")

    args = parser.parse_args()

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


if __name__ == "__main__":
    main()
