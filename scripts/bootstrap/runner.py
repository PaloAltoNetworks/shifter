"""GitHub Actions Runner setup module.

Provides self-hosted GitHub Actions runner provisioning and registration for
the bootstrap flow. Terraform (``platform/terraform/global/github-runner``)
owns the EC2 fleet, IAM, alarms, and network; this module orchestrates applying
that root and registering each runner over SSM (issue #1433).

Registration security (per the #1433 preflight and #1222 guardrail): a
single-use GitHub registration token is minted per runner via ``gh api``, kept
in memory only, and delivered inside one JSON ``--parameters`` SSM
``AWS-RunShellScript`` body so ``run_cmd``'s log redactor masks the whole blob.
The token is never written to Terraform state, user data, SSM Parameter Store,
Secrets Manager, GitHub secrets, or disk. The manual walkthrough is kept as an
explicit fallback.

This module is called from cli.py / deploy.py as part of the deployment flow.
"""

import json
import os
import subprocess  # nosec B404
from dataclasses import dataclass, field
from pathlib import Path

import terraform_backend as tb

# Import shared utilities from the bootstrap support layer. `deploy.py` remains
# the executable facade, but runner.py should not depend on that facade.
from bootstrap_core import (
    Colors,
    code_block,
    confirm_or_manual,
    error,
    get_repo_root,
    header,
    info,
    run_cmd,
    subheader,
    success,
    wait_for_user,
    warn,
)

# The runner binary and service live under ec2-user's home (see the runner root
# user_data). Registration commands cd here before invoking config.sh / svc.sh.
RUNNER_HOME = "/home/ec2-user/actions-runner"
DEFAULT_RUNNER_LABELS = "self-hosted,linux,X64"
DEFAULT_RUNNER_WORK_FOLDER = "shifter"


@dataclass
class RunnerConfig:
    """Configuration for GitHub Runner setup."""

    env: str
    region: str
    github_org: str
    github_repo: str
    aws_profile: str


@dataclass
class RunnerTarget:
    """One runner to register.

    The registration operation is parameterized by this target (the #1433
    extensibility seam): future multi-AZ/subnet placement, differing label sets,
    or a separate proof/prod fleet change the target mapping, not the
    token-handling path or the Terraform root.
    """

    instance_id: str
    runner_name: str
    repo_url: str
    region: str
    labels: str = DEFAULT_RUNNER_LABELS
    work_folder: str = DEFAULT_RUNNER_WORK_FOLDER
    extra_labels: list[str] = field(default_factory=list)

    @property
    def all_labels(self) -> str:
        """Comma-joined labels including any per-target extras (env, etc.)."""
        if not self.extra_labels:
            return self.labels
        return ",".join([self.labels, *self.extra_labels])


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


# ------------------------------------------------------------------------------
# Automated provisioning + registration (issue #1433)
# ------------------------------------------------------------------------------


def mint_registration_token(config: RunnerConfig, *, dry_run: bool = False) -> str | None:
    """Mint a single-use GitHub Actions registration token via the repo API.

    Returns the token (held in memory only), or None in dry-run. `gh api` reads
    the operator's existing GitHub auth. The token is never logged (captured, not
    streamed), written to disk, or passed to Terraform. Mint one per runner.
    """
    if dry_run:
        info("[DRY-RUN] Would mint a single-use GitHub registration token (one per runner)")
        return None

    result = run_cmd(
        [
            "gh",
            "api",
            "-X",
            "POST",
            f"/repos/{config.github_org}/{config.github_repo}/actions/runners/registration-token",
            "--jq",
            ".token",
        ],
        capture=True,
    )
    token = (result.stdout or "").strip() if result else ""
    if not token:
        error("Failed to mint a GitHub Actions runner registration token (check `gh auth status`)")
        raise SystemExit(1)
    return token


def _registration_script(target: RunnerTarget, token: str) -> list[str]:
    """Return the remote registration command lines for AWS-RunShellScript.

    Security handling of the token (per the #1433 preflight and #1222 guardrail):

    - Shell tracing is disabled (`set +x`) so nothing is echoed to the SSM output
      stream, and a trap removes both temp files on any exit so the token file
      never lingers on the host.
    - The token is written to a root-owned 0600 temp file and read *inside*
      `expect`; it is never a `config.sh` (or `expect`) command-line argument, so
      it cannot be read from `/proc/<pid>/cmdline` during registration.
    - `config.sh` reads its registration-token prompt through a console-only
      masked reader — it fails with "Cannot read keys ... console input has been
      redirected" when stdin is a pipe/file — so registration runs it under a PTY
      via `expect`, which waits for the token prompt before sending the token read
      from the file. Every other prompt is suppressed by explicit flags. This
      keeps the token off argv without resorting to `--unattended --token`, which
      would place the token on `config.sh`'s command line (forbidden by #1433).

    The token still rides inside the SSM command body (the accepted send-command
    residual), but never in Terraform, user data, a persistent secret store, or
    operator logs (the JSON blob is masked whole by the run_cmd redactor).
    `.runner` / `.credentials` are the only long-lived result.
    """
    # config.sh gets no --token: expect sends the token over the PTY at the
    # prompt. Tcl `$token`/`$argv`/`$result` stay literal; only the target values
    # are interpolated. `$argv` is the token-file path, not the token itself.
    config_args = (
        f"--url {target.repo_url} --name {target.runner_name} "
        f"--labels {target.all_labels} --work {target.work_folder} "
        "--runnergroup Default --replace"
    )
    expect_script = f"""set timeout 300
set fh [open [lindex $argv 0] r]
set token [string trim [read $fh]]
close $fh
spawn -noecho sudo -u ec2-user ./config.sh {config_args}
expect {{
    -re {{(?i)token}} {{ send -- "$token\\r" }}
    timeout {{ send_user "expect: timed out waiting for the token prompt\\n"; exit 2 }}
    eof {{ send_user "expect: config.sh exited before the token prompt\\n"; exit 3 }}
}}
expect eof
catch wait result
exit [lindex $result 3]"""
    return [
        "set -euo pipefail",
        "set +x",
        f"cd {RUNNER_HOME}",
        "umask 077",
        'TOKFILE="$(mktemp /root/.ghrunner-reg.XXXXXX)"',
        'EXPECTFILE="$(mktemp /root/.ghrunner-exp.XXXXXX)"',
        # Remove both temp files on any exit so the token file never lingers.
        'trap \'rm -f "$TOKFILE" "$EXPECTFILE"\' EXIT',
        # Quoted heredoc delimiters: contents are written literally, not expanded.
        "cat > \"$TOKFILE\" <<'GHTOKEN'",
        token,
        "GHTOKEN",
        "cat > \"$EXPECTFILE\" <<'GHEXPECT'",
        *expect_script.split("\n"),
        "GHEXPECT",
        # expect argv is the script path + the token-file path; the token itself
        # is never an argument (it is read from the file inside expect).
        'expect "$EXPECTFILE" "$TOKFILE"',
        "sudo ./svc.sh install ec2-user",
        "sudo ./svc.sh start",
    ]


def _registration_parameters(target: RunnerTarget, token: str) -> str:
    """Return the SSM --parameters value as one JSON argv element.

    JSON (not shorthand `commands=[...]`) so the token-bearing body is a single
    argv element beginning with `{`, which run_cmd's redactor masks in full.
    """
    return json.dumps({"commands": _registration_script(target, token)})


def register_runner(config: RunnerConfig, target: RunnerTarget, *, dry_run: bool = False) -> str | None:
    """Register one runner over SSM. Returns the SSM command id (None in dry-run)."""
    if dry_run:
        info(
            f"[DRY-RUN] Would register {target.runner_name} on {target.instance_id} "
            "(no token minted, no SSM command sent)"
        )
        return None

    token = mint_registration_token(config)
    parameters = _registration_parameters(target, token)
    result = run_cmd(
        [
            "aws",
            "ssm",
            "send-command",
            "--region",
            target.region,
            "--instance-ids",
            target.instance_id,
            "--document-name",
            "AWS-RunShellScript",
            "--parameters",
            parameters,
            "--query",
            "Command.CommandId",
            "--output",
            "text",
        ],
        capture=True,
        profile=config.aws_profile,
    )
    command_id = (result.stdout or "").strip() if result else ""
    if not command_id or command_id == "None":
        error(f"SSM did not return a command id while registering {target.runner_name}")
        raise SystemExit(1)
    info(f"Registration command {command_id} sent to {target.runner_name} ({target.instance_id})")
    return command_id


def wait_for_ssm_command(command_id: str, target: RunnerTarget, config: RunnerConfig) -> str:
    """Wait for an SSM command to reach a terminal state; return its status.

    Only the Status field is queried (never StandardOutputContent), so no command
    output is pulled back locally.
    """
    run_cmd(
        [
            "aws",
            "ssm",
            "wait",
            "command-executed",
            "--command-id",
            command_id,
            "--instance-id",
            target.instance_id,
            "--region",
            target.region,
        ],
        check=False,
        profile=config.aws_profile,
    )
    status_result = run_cmd(
        [
            "aws",
            "ssm",
            "get-command-invocation",
            "--command-id",
            command_id,
            "--instance-id",
            target.instance_id,
            "--region",
            target.region,
            "--query",
            "Status",
            "--output",
            "text",
        ],
        capture=True,
        check=False,
        profile=config.aws_profile,
    )
    status = (status_result.stdout or "").strip() if status_result else ""
    if status == "Success":
        success(f"Runner {target.runner_name} registered (SSM {status})")
    else:
        warn(f"Runner {target.runner_name}: SSM registration status {status or 'unknown'}")
    return status


def verify_runners(
    config: RunnerConfig,
    expected_names: list[str],
    *,
    dry_run: bool = False,
) -> dict[str, str]:
    """Verify runners are online via the GitHub runners API (no web console).

    Returns {name: status} for expected runners present in the API response.
    """
    if dry_run:
        info("[DRY-RUN] Would verify runners are online via the GitHub runners API")
        return {}

    result = run_cmd(
        [
            "gh",
            "api",
            f"repos/{config.github_org}/{config.github_repo}/actions/runners",
            "--jq",
            ".runners",
        ],
        capture=True,
    )
    raw = (result.stdout or "").strip() if result else ""
    runners = json.loads(raw) if raw else []
    status_by_name = {r.get("name"): r.get("status") for r in runners}
    for name in expected_names:
        status = status_by_name.get(name)
        if status == "online":
            success(f"Runner {name} is online")
        else:
            warn(f"Runner {name} not online (status: {status or 'not found'})")
    return {name: status_by_name[name] for name in expected_names if name in status_by_name}


def _registration_failures(
    ssm_status_by_name: dict[str, str],
    verified: dict[str, str],
    expected_names: list[str],
) -> list[str]:
    """Return human-readable problems for runners that failed to register/come online.

    A runner is only healthy when its SSM registration command reached `Success`
    AND the GitHub API reports it `online`. Anything else is a failure the caller
    must fail closed on, so `deploy.py runners` / `full` never report success while
    AWS deploy workflows remain blocked on `runs-on: self-hosted`.
    """
    problems: list[str] = []
    for name in expected_names:
        status = ssm_status_by_name.get(name)
        if status != "Success":
            problems.append(f"{name}: SSM registration status {status or 'unknown'}")
        elif verified.get(name) != "online":
            problems.append(f"{name}: not online (status: {verified.get(name) or 'not found'})")
    return problems


def _runner_tf_dir() -> Path:
    """Absolute path to the runner Terraform root."""
    return get_repo_root() / "platform" / "terraform" / "global" / "github-runner"


def _resolve_runner_state_bucket(bucket_name: str | None) -> str:
    """Resolve the Terraform state bucket from the arg or TF_INFRA_STATE_BUCKET."""
    if bucket_name:
        return bucket_name
    return os.environ.get("TF_INFRA_STATE_BUCKET", "").strip()


def _runner_backend_config_path(env: str, bucket: str) -> Path:
    """Per-instance backend config path for the runner stack (reuses the renderer)."""
    instance_dir = tb.instance_dir_from_env() or (Path.home() / ".shifter" / f"{env}-{bucket}")
    backend_dir = tb.resolve_instance_backend_dir(env=env, bucket=bucket, instance_dir=instance_dir)
    return tb.backend_config_for_stack(backend_dir, "global/github-runner", env)


def _terraform_output_targets(config: RunnerConfig) -> list[RunnerTarget]:
    """Read runner_instance_ids / runner_names from terraform output into targets."""
    result = run_cmd(["terraform", "output", "-json"], capture=True, check=False)
    raw = (result.stdout or "").strip() if result else ""
    if not raw:
        return []
    outputs = json.loads(raw)
    ids = outputs.get("runner_instance_ids", {}).get("value", []) or []
    names = outputs.get("runner_names", {}).get("value", []) or []
    repo_url = f"https://github.com/{config.github_org}/{config.github_repo}"
    return [
        RunnerTarget(
            instance_id=instance_id,
            runner_name=name,
            repo_url=repo_url,
            region=config.region,
            extra_labels=[config.env],
        )
        for instance_id, name in zip(ids, names, strict=False)
    ]


def apply_runner_terraform(
    config: RunnerConfig,
    *,
    dry_run: bool = False,
    create_network: bool = True,
    bucket_name: str | None = None,
    runner_count: int | None = None,
) -> list[RunnerTarget]:
    """Init/plan/apply the runner Terraform root; return provisioned targets.

    Never passes a registration token to Terraform (tokens are minted per-runner
    at registration time, not at apply time). When create_network is set, provisions
    the dedicated ADR-004-R20-compliant runner VPC via the runner root.

    The runner lands in the account the deployment targets: AWS_PROFILE is pinned
    to config.aws_profile for the Terraform run (mirroring terraform_deploy), so
    the fleet is created in the same account `--profile` authenticates to, not
    whatever ambient credentials happen to be set.
    """
    bucket = _resolve_runner_state_bucket(bucket_name)
    if not bucket and not dry_run:
        error("Set TF_INFRA_STATE_BUCKET or pass the bootstrap bucket name before applying the runner root")
        raise SystemExit(1)
    backend_config = _runner_backend_config_path(config.env, bucket or "<state-bucket>")

    var_flags = [f"-var=create_runner_network={'true' if create_network else 'false'}"]
    if runner_count is not None:
        var_flags.append(f"-var=runner_count={runner_count}")

    init_cmd = ["terraform", "init", "-reconfigure", f"-backend-config={backend_config}"]
    plan_cmd = ["terraform", "plan", "-out=tfplan", f"-var-file={config.env}.tfvars", *var_flags]
    apply_cmd = ["terraform", "apply", "tfplan"]

    if dry_run:
        for cmd in (init_cmd, plan_cmd, apply_cmd):
            run_cmd(cmd, dry_run=True)
        return []

    # Pin the target account for Terraform (only affects this process + children).
    os.environ["AWS_PROFILE"] = config.aws_profile

    tf_dir = _runner_tf_dir()
    if not tf_dir.exists():
        error(f"Runner Terraform root not found: {tf_dir}")
        raise SystemExit(1)

    original_dir = os.getcwd()
    os.chdir(tf_dir)
    try:
        run_cmd(init_cmd)
        run_cmd(plan_cmd)
        run_cmd(apply_cmd)
        return _terraform_output_targets(config)
    finally:
        os.chdir(original_dir)


def provision_and_register_runners(
    config: RunnerConfig,
    *,
    dry_run: bool = False,
    create_network: bool = True,
    use_existing_network: bool = False,
    bucket_name: str | None = None,
    runner_count: int | None = None,
) -> dict[str, object]:
    """Apply the runner root, register each runner over SSM, and verify via the API.

    This is the automated path for `deploy.py runners` and `full` (issue #1433):
    Terraform provisions hosts + (optionally) the dedicated runner VPC, then each
    runner is registered with a per-runner token delivered over SSM and verified
    online through the GitHub runners API — no manual web-console step.
    """
    header("Automated GitHub Runner Provisioning & Registration")

    targets = apply_runner_terraform(
        config,
        dry_run=dry_run,
        create_network=create_network and not use_existing_network,
        bucket_name=bucket_name,
        runner_count=runner_count,
    )

    if dry_run:
        info("[DRY-RUN] Would register each provisioned runner over SSM and verify via the GitHub API")
        return {"targets": [], "verified": {}}

    if not targets:
        error("No runner instances found in Terraform outputs; runner provisioning did not produce a fleet")
        raise SystemExit(1)

    ssm_status_by_name: dict[str, str] = {}
    for target in targets:
        subheader(f"Registering {target.runner_name}")
        command_id = register_runner(config, target)
        if command_id:
            ssm_status_by_name[target.runner_name] = wait_for_ssm_command(command_id, target, config)

    expected = [t.runner_name for t in targets]
    verified = verify_runners(config, expected)

    # Fail closed: a dispatched SSM command is not a registered, online runner.
    problems = _registration_failures(ssm_status_by_name, verified, expected)
    if problems:
        for problem in problems:
            error(problem)
        error("Runner provisioning did not complete cleanly; AWS deploy workflows remain blocked")
        raise SystemExit(1)

    success(f"Provisioned and registered {len(targets)} runner(s)")
    return {"targets": expected, "verified": verified}
