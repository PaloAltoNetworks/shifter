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
import subprocess
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path

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
    for line in text.strip().split('\n'):
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
    """Prompt for yes/no/manual. Returns 'yes', 'no', or 'manual'."""
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
        print("Please enter 'y' (yes), 'n' (no), or 'm' (manual)")


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


def run_cmd(cmd: list[str], dry_run: bool = False, check: bool = True, capture: bool = False, profile: str = None) -> subprocess.CompletedProcess | None:
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
            result = subprocess.run(cmd, check=check, capture_output=True, text=True)
        else:
            result = subprocess.run(cmd, check=check, text=True)
        return result
    except subprocess.CalledProcessError as e:
        error(f"Command failed: {e}")
        if hasattr(e, 'stderr') and e.stderr:
            print(e.stderr)
        if check:
            sys.exit(1)
        return None


def get_aws_account_id(profile: str = None) -> str:
    """Get current AWS account ID."""
    cmd = ["aws", "sts", "get-caller-identity", "--query", "Account", "--output", "text"]
    if profile:
        cmd = ["aws", "--profile", profile, "sts", "get-caller-identity", "--query", "Account", "--output", "text"]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return result.stdout.strip()


def get_repo_root() -> Path:
    """Get the repository root directory."""
    return Path(__file__).parent.parent.parent


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
    def role_name(self) -> str:
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
        info(f"[DRY-RUN] Would get AWS account ID")

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

    run_cmd([
        "aws", "s3api", "create-bucket",
        "--bucket", bucket_name,
        "--region", config.region,
        "--create-bucket-configuration", f"LocationConstraint={config.region}"
    ], dry_run=dry_run, profile=profile)

    run_cmd([
        "aws", "s3api", "put-bucket-versioning",
        "--bucket", bucket_name,
        "--versioning-configuration", "Status=Enabled"
    ], dry_run=dry_run, profile=profile)

    run_cmd([
        "aws", "s3api", "put-bucket-encryption",
        "--bucket", bucket_name,
        "--server-side-encryption-configuration",
        '{"Rules": [{"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}]}'
    ], dry_run=dry_run, profile=profile)

    run_cmd([
        "aws", "s3api", "put-public-access-block",
        "--bucket", bucket_name,
        "--public-access-block-configuration",
        '{"BlockPublicAcls": true, "IgnorePublicAcls": true, "BlockPublicPolicy": true, "RestrictPublicBuckets": true}'
    ], dry_run=dry_run, profile=profile)

    success("S3 bucket created")

    # Step 2: DynamoDB Table
    header("Step 2/4: Creating DynamoDB Table")

    run_cmd([
        "aws", "dynamodb", "create-table",
        "--table-name", table_name,
        "--attribute-definitions", "AttributeName=LockID,AttributeType=S",
        "--key-schema", "AttributeName=LockID,KeyType=HASH",
        "--billing-mode", "PAY_PER_REQUEST",
        "--region", config.region
    ], dry_run=dry_run, profile=profile)

    if not dry_run:
        info("Waiting for table to be active...")
        run_cmd([
            "aws", "dynamodb", "wait", "table-exists",
            "--table-name", table_name,
            "--region", config.region
        ], profile=profile)

    success("DynamoDB table created")

    # Step 3: OIDC Provider
    header("Step 3/4: Creating GitHub OIDC Provider")

    # VERIFIED OFFICIAL VALUES (Brad Edwards, 2026-01-02):
    # Provider URL: https://token.actions.githubusercontent.com
    # Source: https://docs.github.com/en/actions/deployment/security-hardening-your-deployments/configuring-openid-connect-in-amazon-web-services
    # Source: https://aws.amazon.com/blogs/security/use-iam-roles-to-connect-github-actions-to-actions-in-aws/
    # Audience: sts.amazonaws.com (official AWS STS audience for OIDC)
    # Note: As of July 2024, AWS IAM automatically trusts GitHub's root CAs
    # so thumbprints are no longer required for token.actions.githubusercontent.com
    run_cmd([
        "aws", "iam", "create-open-id-connect-provider",
        "--url", "https://token.actions.githubusercontent.com",
        "--client-id-list", "sts.amazonaws.com",
        "--tags", f"Key=Name,Value=github-actions-oidc-{config.env}", "Key=Project,Value=shifter"
    ], dry_run=dry_run, check=False, profile=profile)  # May already exist

    success("OIDC provider ready")

    # Step 4: IAM Role
    header("Step 4/4: Creating IAM Role and Policies")

    # Get OIDC ARN
    if not dry_run:
        cmd = ["aws", "iam", "list-open-id-connect-providers",
               "--query", "OpenIDConnectProviderList[?contains(Arn, 'token.actions.githubusercontent.com')].Arn",
               "--output", "text"]
        if profile:
            cmd = ["aws", "--profile", profile] + cmd[1:]
        result = subprocess.run(cmd, capture_output=True, text=True)
        oidc_arn = result.stdout.strip()
    else:
        oidc_arn = f"arn:aws:iam::{account_id}:oidc-provider/token.actions.githubusercontent.com"

        # OIDC Trust Policy for GitHub Actions
        # VERIFIED OFFICIAL VALUES (Brad Edwards, 2026-01-02):
        # - token.actions.githubusercontent.com:aud must be "sts.amazonaws.com"
        # - token.actions.githubusercontent.com:sub format: "repo:ORG/REPO:*"
        # Source: https://docs.github.com/en/actions/deployment/security-hardening-your-deployments/configuring-openid-connect-in-amazon-web-services
        trust_policy = {
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"Federated": oidc_arn},
            "Action": "sts:AssumeRoleWithWebIdentity",
            "Condition": {
                "StringEquals": {"token.actions.githubusercontent.com:aud": "sts.amazonaws.com"},
                "StringLike": {"token.actions.githubusercontent.com:sub": f"repo:{config.github_org}/{config.github_repo}:*"}
            }
        }]
    }

    run_cmd([
        "aws", "iam", "create-role",
        "--role-name", config.role_name,
        "--assume-role-policy-document", json.dumps(trust_policy),
        "--tags", f"Key=Name,Value={config.role_name}", "Key=Project,Value=shifter"
    ], dry_run=dry_run, profile=profile)

    # Attach policies
    policies = [
        ("core", ["ecr:*", "s3:*", "dynamodb:*"]),
        ("vpc", ["ec2:*"]),
        ("compute", ["ecs:*", "elasticloadbalancing:*", "autoscaling:*"]),
        ("data", ["rds:*", "elasticache:*"]),
        ("security", ["iam:*", "kms:*", "secretsmanager:*", "acm:*", "wafv2:*"]),
        ("serverless", ["lambda:*", "states:*", "events:*", "logs:*", "cloudwatch:*", "sns:*", "sqs:*"]),
        ("cognito", ["cognito-idp:*", "ssm:*"]),
        ("network", ["network-firewall:*"]),
        ("other", ["firehose:*", "budgets:*"]),
    ]

    for name, actions in policies:
        policy_doc = {
            "Version": "2012-10-17",
            "Statement": [{"Effect": "Allow", "Action": actions, "Resource": "*"}]
        }
        run_cmd([
            "aws", "iam", "put-role-policy",
            "--role-name", config.role_name,
            "--policy-name", f"shifter-{config.env}-{name}",
            "--policy-document", json.dumps(policy_doc)
        ], dry_run=dry_run, profile=profile)

    success("IAM role and policies created")

    # Get role ARN
    if not dry_run:
        cmd = ["aws", "iam", "get-role",
               "--role-name", config.role_name,
               "--query", "Role.Arn",
               "--output", "text"]
        if profile:
            cmd = ["aws", "--profile", profile] + cmd[1:]
        result = subprocess.run(cmd, capture_output=True, text=True)
        role_arn = result.stdout.strip()
    else:
        role_arn = f"arn:aws:iam::{account_id}:role/{config.role_name}"

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
        gh_available = subprocess.run(["which", "gh"], capture_output=True).returncode == 0

        if gh_available:
            print(f"\n{Colors.GREEN}✓ GitHub CLI detected{Colors.END}")
            choice = confirm_or_manual("Automatically set this secret using gh CLI?")

            if choice == "yes":
                info(f"Running: gh secret set {secret_name} --repo {github_org}/{github_repo}")
                result = subprocess.run(
                    ["gh", "secret", "set", secret_name, "--body", role_arn, "--repo", f"{github_org}/{github_repo}"],
                    capture_output=True, text=True
                )
                if result.returncode == 0:
                    success("GitHub secret configured via gh CLI")
                    return
                else:
                    error(f"Failed to set secret: {result.stderr}")
                    warn("Falling back to manual method")
            elif choice == "no":
                info("Skipping GitHub secret configuration")
                return
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
    """Walk user through updating backend.tf files."""
    header("Update Terraform Backend Configuration")

    bucket = bootstrap_result["bucket_name"]
    table = bootstrap_result["table_name"]
    region = bootstrap_result["region"]
    env = bootstrap_result["env"]

    repo_root = get_repo_root()

    print("Terraform needs to know where to store state.\n")

    # Generate backend configs
    # Note: Core uses shifter/{env}/, but portal/range use {env}/ (historical convention)
    backends = [
        (f"platform/terraform/environments/{env}/backend.tf", f"shifter/{env}/terraform.tfstate"),
        (f"platform/terraform/environments/{env}/portal/backend.tf", f"{env}/portal/terraform.tfstate"),
        (f"platform/terraform/environments/{env}/range/backend.tf", f"{env}/range/terraform.tfstate"),
    ]

    # Show what will be written
    for filepath, state_key in backends:
        subheader(filepath)

        backend_config = f'''terraform {{
  backend "s3" {{
    bucket         = "{bucket}"
    key            = "{state_key}"
    region         = "{region}"
    dynamodb_table = "{table}"
    encrypt        = true
  }}
}}'''
        code_block(backend_config)

        full_path = repo_root / filepath
        if full_path.exists():
            info(f"File exists at: {full_path}")
        else:
            warn(f"File not found: {full_path}")

    if not dry_run:
        choice = confirm_or_manual("Automatically write these backend.tf files?")

        if choice == "yes":
            # Write the files
            for filepath, state_key in backends:
                full_path = repo_root / filepath
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
                try:
                    full_path.parent.mkdir(parents=True, exist_ok=True)
                    full_path.write_text(backend_config)
                    success(f"Wrote {filepath}")
                except Exception as e:
                    error(f"Failed to write {filepath}: {e}")
                    return

            # Offer to commit and push
            commit_choice = confirm_or_manual("Commit and push these changes to git?")

            if commit_choice == "yes":
                try:
                    info(f"Adding files: platform/terraform/environments/{env}/")
                    subprocess.run(["git", "add", f"platform/terraform/environments/{env}/"], check=True, cwd=repo_root)

                    info(f"Committing: Update backend config for {env}")
                    subprocess.run(["git", "commit", "-m", f"Update backend config for {env}"], check=True, cwd=repo_root)

                    info("Pushing to remote...")
                    subprocess.run(["git", "push"], check=True, cwd=repo_root)

                    success("Changes committed and pushed")
                except subprocess.CalledProcessError as e:
                    error(f"Git operation failed: {e}")
                    warn("You'll need to commit and push manually")
            elif commit_choice == "manual":
                info("You should run:")
                code_block(f"git add platform/terraform/environments/{env}/\ngit commit -m 'Update backend config for {env}'\ngit push")
                wait_for_user("Commit and push the changes, then press Enter.")

            success("Backend configuration updated")

        elif choice == "manual":
            # Manual method
            wait_for_user(
                "Update the backend.tf files shown above with the new bucket and table names.\n"
                "You can copy the code blocks directly into each file."
            )

            if confirm("Commit and push the backend.tf changes now?"):
                info("You should run:")
                code_block(f"git add platform/terraform/environments/{env}/\ngit commit -m 'Update backend config for {env}'\ngit push")
                wait_for_user("Commit and push the changes, then press Enter.")

            success("Backend configuration updated")
        else:
            info("Skipping backend configuration")


def terraform_deploy(env: str, profile: str, dry_run: bool = False) -> dict:
    """Deploy all Terraform components in order."""
    header(f"Deploying {env.upper()} Infrastructure")

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
            warn(f"Skipping {component}")
            continue

        base_path = get_repo_root() / "platform" / "terraform" / "environments" / env
        tf_dir = base_path if component == "core" else base_path / component

        if not tf_dir.exists():
            error(f"Directory not found: {tf_dir}")
            continue

        # Change to terraform directory
        original_dir = os.getcwd()
        os.chdir(tf_dir)

        try:
            # Init
            info("Running terraform init...")
            run_cmd(["terraform", "init"], dry_run=dry_run)

            # Plan
            info("Running terraform plan...")
            run_cmd(["terraform", "plan", "-out=tfplan"], dry_run=dry_run)

            if not dry_run:
                # Show plan summary
                print(f"\n{Colors.BOLD}Plan Summary:{Colors.END}")
                subprocess.run(["terraform", "show", "-no-color", "tfplan"], check=False)

                if not confirm(f"\nApply this plan?"):
                    warn("Apply skipped by user")
                    continue

                # Apply
                info("Running terraform apply...")
                run_cmd(["terraform", "apply", "tfplan"])

                success(f"{component} deployed successfully")

                # Capture outputs for portal
                if component == "portal":
                    result = subprocess.run(
                        ["terraform", "output", "-json"],
                        capture_output=True, text=True, check=False
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

        cmd = f'''aws cognito-idp admin-create-user \\
  --user-pool-id {pool_id} \\
  --username YOUR_EMAIL@example.com \\
  --user-attributes Name=email,Value=YOUR_EMAIL@example.com \\
  --desired-delivery-mediums EMAIL'''

        code_block(cmd)

        print(f"\n{Colors.DIM}The user will receive an email with a temporary password.{Colors.END}")
    else:
        print("Run this to get the user pool ID:")
        code_block("terraform output cognito_user_pool_id")
        print("\nThen create a user with:")
        code_block(f'''aws cognito-idp admin-create-user \\
  --user-pool-id <POOL_ID> \\
  --username user@example.com \\
  --user-attributes Name=email,Value=user@example.com''')

    if not dry_run:
        if confirm("Create the first user now?"):
            if "cognito_user_pool_id" in outputs:
                pool_id = outputs["cognito_user_pool_id"]["value"]
                email = input(f"{Colors.CYAN}Enter email for first user: {Colors.END}").strip()
                if email:
                    run_cmd([
                        "aws", "cognito-idp", "admin-create-user",
                        "--user-pool-id", pool_id,
                        "--username", email,
                        "--user-attributes", f"Name=email,Value={email}",
                        "--desired-delivery-mediums", "EMAIL"
                    ], profile=profile)
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

    print(f"""
This will guide you through a complete Shifter deployment:

  1. Bootstrap AWS account (S3, DynamoDB, IAM)
  2. Configure GitHub secrets (automated with gh CLI or manual)
  3. Update Terraform backend configuration (automated or manual)
  4. Deploy infrastructure (Core → Range → Portal)
  5. Configure DNS and SSL certificate (manual - external DNS)
  6. Create first user

Automated steps will ask for confirmation:
  [y] yes - run automatically
  [n] no - skip this step
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

    # Phase 4: Terraform Deployment
    if not dry_run:
        if not confirm("Continue with Terraform deployment?"):
            print("\nYou can resume later with:")
            code_block(f"./scripts/bootstrap/deploy.py terraform --env {env} --profile {profile}")
            return

    outputs = terraform_deploy(env, profile, dry_run=dry_run)

    if not dry_run and outputs:
        # Phase 5: ACM Validation
        walkthrough_acm_validation(outputs, dry_run=dry_run)

        # Phase 6: DNS Setup
        walkthrough_dns_setup(outputs, dry_run=dry_run)

        # Phase 7: First User
        walkthrough_cognito_user(outputs, env, profile, dry_run=dry_run)

    # Final Summary
    walkthrough_final_steps(env)


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
        """
    )

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
