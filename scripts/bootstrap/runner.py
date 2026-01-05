"""GitHub Actions Runner setup module.

Provides instructions for setting up self-hosted GitHub Actions runners
on EC2 instances. The instances are provisioned by Terraform; this module
guides users through the manual registration process.

This module is called from deploy.py as part of the full deployment flow.
"""

import subprocess  # nosec B404
from dataclasses import dataclass

# Import shared utilities from deploy
from deploy import (
    Colors,
    code_block,
    confirm_or_manual,
    header,
    info,
    subheader,
    success,
    wait_for_user,
)


@dataclass
class RunnerConfig:
    """Configuration for GitHub Runner setup."""

    env: str
    region: str
    github_org: str
    github_repo: str
    aws_profile: str


def get_runner_instance_ids(config: RunnerConfig) -> list[str]:
    """Get EC2 instance IDs for GitHub runners from AWS."""
    cmd = [
        "aws",
        "--profile",
        config.aws_profile,
        "--region",
        config.region,
        "ec2",
        "describe-instances",
        "--filters",
        "Name=tag:Name,Values=shifter-github-runner-*",
        "Name=instance-state-name,Values=running",
        "--query",
        "Reservations[*].Instances[*].InstanceId",
        "--output",
        "text",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)  # nosec B603 B607
    if result.returncode != 0:
        return []
    return result.stdout.strip().split()


def show_runner_registration_instructions(config: RunnerConfig, instance_ids: list[str]) -> None:
    """Display instructions for registering GitHub runners."""
    header("GitHub Actions Runner Registration")

    print(f"""
The Terraform module has provisioned {len(instance_ids)} EC2 instance(s) for self-hosted runners.
You need to manually register each runner with GitHub.

{Colors.BOLD}Runner Instance IDs:{Colors.END}
""")

    for i, instance_id in enumerate(instance_ids, 1):
        print(f"  {i}. {Colors.CYAN}{instance_id}{Colors.END}")

    subheader("Step 1: Connect to Runner Instance via SSM")

    print("""
Connect to each runner instance using AWS SSM Session Manager:
""")

    for _i, instance_id in enumerate(instance_ids, 1):
        code_block(
            f"AWS_PROFILE={config.aws_profile} aws ssm start-session --target {instance_id} --region {config.region}"
        )

    subheader("Step 2: Install Dependencies")

    print("""
Once connected, switch to ec2-user and install required dependencies:
""")

    code_block("""sudo su ec2-user
cd ~/actions-runner
sudo dnf install -y libicu dotnet-runtime-6.0""")

    subheader("Step 3: Get Runner Registration Token")

    print(f"""
1. Go to your GitHub repository:
   {Colors.CYAN}https://github.com/{config.github_org}/{config.github_repo}/settings/actions/runners/new{Colors.END}

2. Click {Colors.GREEN}"New self-hosted runner"{Colors.END}

3. Copy the {Colors.GREEN}./config.sh{Colors.END} command which includes your unique token
""")

    subheader("Step 4: Configure the Runner")

    print("""
Run the config command from GitHub (replace <TOKEN> with your actual token):
""")

    code_block(f"./config.sh --url https://github.com/{config.github_org}/{config.github_repo} --token <TOKEN>")

    print(f"""
When prompted, use these values:

  {Colors.YELLOW}Runner group:{Colors.END}      (press Enter for default)
  {Colors.YELLOW}Runner name:{Colors.END}       shifter-runner-1  (use 1, 2, 3 for each instance)
  {Colors.YELLOW}Additional labels:{Colors.END} {config.env},shifter
  {Colors.YELLOW}Work folder:{Colors.END}       shifter
""")

    subheader("Step 5: Install and Start as Service")

    print("""
Install the runner as a systemd service so it starts automatically:
""")

    code_block("""sudo ./svc.sh install
sudo ./svc.sh start
sudo ./svc.sh status""")

    subheader("Step 6: Verify Runner Status")

    print(f"""
Check that your runners appear as {Colors.GREEN}Idle{Colors.END} on the GitHub Runners page:

  {Colors.CYAN}https://github.com/{config.github_org}/{config.github_repo}/settings/actions/runners{Colors.END}

{Colors.YELLOW}Note:{Colors.END} Repeat steps 1-5 for each runner instance.
""")


def walkthrough_runner_setup(
    config: RunnerConfig,
    dry_run: bool = False,
) -> dict | None:
    """Walk user through GitHub Runner setup.

    Returns a dict with instance_ids if successful, None if skipped.
    """
    header("GitHub Actions Runner Setup")

    print(f"""
Self-hosted GitHub Actions runners are EC2 instances that run your CI/CD workflows.
The instances have been provisioned by Terraform; you need to register them with GitHub.

{Colors.BOLD}What you'll do:{Colors.END}
  1. Connect to each runner instance via SSM
  2. Install dependencies (libicu, dotnet-runtime)
  3. Get a registration token from GitHub
  4. Configure and register the runner
  5. Install as a systemd service

This is a one-time setup per runner instance.
""")

    if dry_run:
        instance_ids = ["i-dry-run-instance-1", "i-dry-run-instance-2"]
    else:
        choice = confirm_or_manual("Set up GitHub runners now?")

        if choice == "no":
            info("Skipping runner setup - you can set this up later")
            return None

        # Get running runner instances
        subheader("Finding Runner Instances")
        instance_ids = get_runner_instance_ids(config)

        if not instance_ids:
            info("No runner instances found. Deploy the github-runner Terraform module first.")
            print("""
To deploy runner infrastructure:
""")
            code_block(f"""cd platform/terraform/global/github-runner
AWS_PROFILE={config.aws_profile} terraform init -backend-config={config.env}.s3.tfbackend
AWS_PROFILE={config.aws_profile} terraform apply -var-file={config.env}.tfvars""")
            return None

        success(f"Found {len(instance_ids)} runner instance(s)")

    # Show registration instructions
    show_runner_registration_instructions(config, instance_ids)

    if not dry_run:
        wait_for_user("Press Enter when you've completed runner registration.")

    subheader("Runner Setup Complete")

    print(f"""
{Colors.GREEN}Runners configured!{Colors.END}

Your self-hosted runners should now be available for GitHub Actions workflows.
Workflows with {Colors.CYAN}runs-on: self-hosted{Colors.END} will use these runners.

{Colors.YELLOW}Troubleshooting:{Colors.END}
  - Check runner status: sudo ./svc.sh status
  - View runner logs: sudo journalctl -u actions.runner.*
  - Restart runner: sudo ./svc.sh stop && sudo ./svc.sh start
""")

    return {
        "instance_ids": instance_ids,
    }


def get_runner_config(
    env: str,
    region: str,
    github_org: str,
    github_repo: str,
    aws_profile: str,
) -> RunnerConfig:
    """Create a RunnerConfig from deployment parameters."""
    return RunnerConfig(
        env=env,
        region=region,
        github_org=github_org,
        github_repo=github_repo,
        aws_profile=aws_profile,
    )
