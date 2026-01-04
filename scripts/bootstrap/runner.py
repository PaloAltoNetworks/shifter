"""GitHub Actions Runner setup module.

Provides functions for setting up self-hosted GitHub Actions runners:
- Walks user through creating a GitHub App (manual steps with clear instructions)
- Creates SSM parameters for secrets (private key, webhook secret)
- Validates configuration

This module is called from deploy.py as part of the full deployment flow.
"""

import base64
import subprocess
import sys
from dataclasses import dataclass

# Import shared utilities from deploy
from deploy import (
    Colors,
    code_block,
    confirm,
    confirm_or_manual,
    error,
    header,
    info,
    subheader,
    success,
    wait_for_user,
    warn,
)


@dataclass
class RunnerConfig:
    """Configuration for GitHub Runner setup."""

    env: str
    region: str
    github_org: str
    github_repo: str
    ssm_prefix: str = "/shifter/github-runner"

    @property
    def key_param_name(self) -> str:
        return f"{self.ssm_prefix}/key-base64"

    @property
    def webhook_secret_param_name(self) -> str:
        return f"{self.ssm_prefix}/webhook-secret"


def check_ssm_parameter_exists(name: str, profile: str, region: str) -> bool:
    """Check if an SSM parameter already exists."""
    cmd = [
        "aws",
        "--profile",
        profile,
        "ssm",
        "get-parameter",
        "--name",
        name,
        "--region",
        region,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.returncode == 0


def create_ssm_parameter(
    name: str,
    value: str,
    profile: str,
    region: str,
    param_type: str = "SecureString",
    dry_run: bool = False,
) -> bool:
    """Create or update an SSM parameter."""
    if dry_run:
        info(f"[DRY-RUN] Would create SSM parameter: {name}")
        return True

    cmd = [
        "aws",
        "--profile",
        profile,
        "ssm",
        "put-parameter",
        "--name",
        name,
        "--value",
        value,
        "--type",
        param_type,
        "--region",
        region,
        "--overwrite",
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        error(f"Failed to create SSM parameter {name}: {result.stderr}")
        return False

    success(f"Created SSM parameter: {name}")
    return True


def validate_base64_pem(value: str) -> tuple[bool, str]:
    """Validate that a value is valid base64-encoded PEM key."""
    try:
        decoded = base64.b64decode(value).decode("utf-8")
        if "-----BEGIN" not in decoded or "-----END" not in decoded:
            return False, "Decoded content doesn't look like a PEM file"
        if "PRIVATE KEY" not in decoded:
            return False, "PEM doesn't contain a private key"
        return True, ""
    except Exception as e:
        return False, f"Invalid base64 encoding: {e}"


def prompt_for_private_key(dry_run: bool = False) -> str | None:
    """Prompt user for the base64-encoded private key."""
    if dry_run:
        return "DRYRUN_BASE64_KEY"

    print(f"\n{Colors.BOLD}Private Key Setup{Colors.END}")
    print("You should have downloaded a .pem file when creating the GitHub App.")
    print("\nTo base64-encode it, run:")
    code_block("base64 -w 0 path/to/your-app.private-key.pem")

    print("\nPaste the base64-encoded private key (single line):")

    if not sys.stdin.isatty():
        warn("Non-interactive mode - skipping private key input")
        return None

    value = input(f"{Colors.CYAN}> {Colors.END}").strip()

    if not value:
        error("No private key provided")
        return None

    valid, msg = validate_base64_pem(value)
    if not valid:
        error(f"Invalid private key: {msg}")
        return None

    success("Private key validated")
    return value


def prompt_for_webhook_secret(dry_run: bool = False) -> str | None:
    """Prompt user for the webhook secret."""
    if dry_run:
        return "DRYRUN_WEBHOOK_SECRET"

    print(f"\n{Colors.BOLD}Webhook Secret Setup{Colors.END}")
    print("Enter a webhook secret (or press Enter to generate one):")

    if not sys.stdin.isatty():
        # Generate a random secret in non-interactive mode
        import uuid

        return str(uuid.uuid4())

    value = input(f"{Colors.CYAN}> {Colors.END}").strip()

    if not value:
        import uuid

        value = str(uuid.uuid4())
        info(f"Generated webhook secret: {value}")

    return value


def prompt_for_app_id(dry_run: bool = False) -> str | None:
    """Prompt user for the GitHub App ID."""
    if dry_run:
        return "123456"

    print(f"\n{Colors.BOLD}GitHub App ID{Colors.END}")
    print("Enter the App ID from your GitHub App settings page:")

    if not sys.stdin.isatty():
        warn("Non-interactive mode - skipping App ID input")
        return None

    value = input(f"{Colors.CYAN}> {Colors.END}").strip()

    if not value:
        error("No App ID provided")
        return None

    if not value.isdigit():
        error("App ID should be a number")
        return None

    return value


def show_github_app_instructions(config: RunnerConfig) -> None:
    """Display instructions for creating a GitHub App."""
    header("Create GitHub App for Runner Authentication")

    print(f"""
GitHub Apps provide secure authentication for self-hosted runners.
You need to create one manually in the GitHub UI.

{Colors.BOLD}Step 1: Go to GitHub App creation page{Colors.END}
""")

    url = f"https://github.com/organizations/{config.github_org}/settings/apps/new"
    print(f"  {Colors.CYAN}{url}{Colors.END}")
    print("\n  Or: GitHub Org Settings → Developer settings → GitHub Apps → New GitHub App")

    print(f"""
{Colors.BOLD}Step 2: Fill in the basic settings{Colors.END}

  GitHub App name:     {Colors.GREEN}shifter-runner-{config.env}{Colors.END}
  Homepage URL:        {Colors.GREEN}https://github.com/{config.github_org}/{config.github_repo}{Colors.END}
  Webhook:             {Colors.GREEN}Disable for now{Colors.END} (configure after Terraform deploy)
""")

    print(f"""{Colors.BOLD}Step 3: Set app installation scope{Colors.END}

  {Colors.YELLOW}Where can this GitHub App be installed?{Colors.END}
    Select: {Colors.GREEN}Only on this account{Colors.END}
""")

    print(f"""{Colors.BOLD}Step 4: Set required permissions{Colors.END}

  {Colors.YELLOW}Repository Permissions:{Colors.END}
    Actions:           Read-only
    Checks:            Read-only
    Metadata:          Read-only

  {Colors.YELLOW}Organization Permissions:{Colors.END}
    Self-hosted runners:  Read and write
""")

    print(f"""{Colors.BOLD}Step 5: Generate credentials{Colors.END}

  1. After creating, note the {Colors.GREEN}App ID{Colors.END} (shown on the app page)
  2. Scroll down and click {Colors.GREEN}"Generate a private key"{Colors.END}
  3. Save the downloaded .pem file securely
  4. Generate a {Colors.GREEN}webhook secret{Colors.END} (random string for later)
""")


def walkthrough_runner_setup(
    config: RunnerConfig,
    profile: str,
    dry_run: bool = False,
) -> dict | None:
    """Walk user through GitHub Runner setup.

    Returns a dict with app_id if successful, None if skipped or failed.
    """
    header("GitHub Actions Runner Setup")

    print(f"""
Self-hosted GitHub Actions runners allow CI/CD to run in your AWS account.
This setup uses the terraform-aws-github-runner module for auto-scaling runners.

{Colors.BOLD}What you'll need to do:{Colors.END}
  1. Create a GitHub App (manual - in GitHub UI)
  2. Provide the App ID and private key (we'll store in AWS SSM)
  3. Provide a webhook secret (we'll store in AWS SSM)

The Terraform deployment will use these credentials to set up auto-scaling runners.
""")

    if not dry_run:
        choice = confirm_or_manual("Set up GitHub runners now?")

        if choice == "no":
            info("Skipping runner setup - you can set this up later")
            return None
        elif choice == "manual":
            show_github_app_instructions(config)
            wait_for_user("Create the GitHub App, then press Enter to continue.")

    # Show instructions
    show_github_app_instructions(config)

    if not dry_run:
        wait_for_user("Create the GitHub App following the instructions above.")

    # Check if secrets already exist
    subheader("Checking existing SSM parameters")

    if dry_run:
        key_exists = False
        webhook_exists = False
    else:
        key_exists = check_ssm_parameter_exists(config.key_param_name, profile, config.region)
        webhook_exists = check_ssm_parameter_exists(config.webhook_secret_param_name, profile, config.region)

    if key_exists:
        info(f"Private key already exists at {config.key_param_name}")
        if not confirm("Overwrite existing private key?"):
            private_key = None
        else:
            private_key = prompt_for_private_key(dry_run)
    else:
        private_key = prompt_for_private_key(dry_run)

    if webhook_exists:
        info(f"Webhook secret already exists at {config.webhook_secret_param_name}")
        if not confirm("Overwrite existing webhook secret?"):
            webhook_secret = None
        else:
            webhook_secret = prompt_for_webhook_secret(dry_run)
    else:
        webhook_secret = prompt_for_webhook_secret(dry_run)

    # Get App ID
    app_id = prompt_for_app_id(dry_run)

    # Create SSM parameters
    subheader("Creating SSM Parameters")

    if private_key and not create_ssm_parameter(
        config.key_param_name,
        private_key,
        profile,
        config.region,
        dry_run=dry_run,
    ):
        error("Failed to create private key parameter")
        return None

    if webhook_secret and not create_ssm_parameter(
        config.webhook_secret_param_name,
        webhook_secret,
        profile,
        config.region,
        dry_run=dry_run,
    ):
        error("Failed to create webhook secret parameter")
        return None

    # Summary
    subheader("Runner Setup Complete")

    print(f"""
{Colors.GREEN}SSM Parameters created:{Colors.END}
  - {config.key_param_name}
  - {config.webhook_secret_param_name}

{Colors.BOLD}Next steps (handled by Terraform):{Colors.END}
  1. Deploy the github-runner Terraform module
  2. Configure the GitHub App webhook URL (from Terraform output)
  3. Install the GitHub App on your repository

{Colors.YELLOW}Note:{Colors.END} After Terraform deploys, you'll need to:
  1. Go back to your GitHub App settings
  2. Enable webhook and set the URL from Terraform output
  3. Enter the webhook secret (same value stored in SSM)
  4. Subscribe to events: check {Colors.GREEN}Workflow Job{Colors.END} only
  5. Install the app on {config.github_org}/{config.github_repo}
""")

    return {
        "app_id": app_id,
        "key_param_name": config.key_param_name,
        "webhook_secret_param_name": config.webhook_secret_param_name,
    }


def get_runner_config(env: str, region: str, github_org: str, github_repo: str) -> RunnerConfig:
    """Create a RunnerConfig from deployment parameters."""
    return RunnerConfig(
        env=env,
        region=region,
        github_org=github_org,
        github_repo=github_repo,
    )
