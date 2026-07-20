"""GCP-native GitHub Actions runner provisioning and registration (issue #1546).

The GCP counterpart to ``runner.py`` (AWS/SSM). Terraform
(``platform/terraform/gcp/global/github-runner``) owns the GCE instance, a
dedicated custom VPC with Cloud NAT, an IAP-only firewall, and a
least-privilege service account; this module applies that root and registers
each runner over ``gcloud compute ssh --tunnel-through-iap`` -- there is no SSM
on GCP and none is needed.

Registration security (per the #1546 preflight, ADR-008): a single-use GitHub
registration token is minted per runner via ``gh api`` (held in memory only)
and delivered to the host over the SSH **stdin** stream via
:func:`bootstrap_core.run_cmd_secret_stdin` into a root-only temp file. It is
kept off the operator's local argv/logs, Terraform state, instance metadata,
and Secret Manager. The runner's ``config.sh`` requires ``--token`` for
non-interactive registration (its ``Console.ReadKey`` prompt fails on redirected
stdin; no ``--token-file``/env channel), so the token is referenced as
``--token "$(cat "$TOKFILE")"`` and appears only momentarily in the isolated,
single-tenant runner VM's process args during registration, then the temp file
is removed and the single-use token expires (accepted bounded residual; see
ADR-008-R8 and follow-up to remove it entirely). The runner registers with
``--no-default-labels`` and a custom label (default: the environment name, e.g.
``gcp-dev``) so it cannot pick up bare ``runs-on: self-hosted`` jobs before
per-account routing exists (ADR-003-R5). The automated path fails closed unless
each runner registered cleanly AND the GitHub API reports it online with the
expected label.

Ground Control identity uses the operator's default gcloud/ADC (no service
account key); there is no ``--profile`` equivalent.
"""

import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path

from bootstrap_core import (
    error,
    get_repo_root,
    header,
    info,
    run_cmd,
    run_cmd_secret_stdin,
    subheader,
    success,
    warn,
)

# Token minting is cloud-agnostic policy (a repo registration token via `gh api`,
# held in memory only); reuse it rather than duplicating the AWS implementation.
from runner import mint_registration_token

# The runner binary/service live under a dedicated unprivileged user's home,
# created by the GCE startup script. Registration cds here before config.sh.
RUNNER_USER = "runner"
RUNNER_HOME = f"/home/{RUNNER_USER}/actions-runner"
DEFAULT_RUNNER_WORK_FOLDER = "shifter"

# IAP SSH readiness polling bounds (a RUNNING instance is not registration-ready).
_SSH_READY_ATTEMPTS = 30
_SSH_READY_DELAY_SECONDS = 10

# Online-verification polling bounds. A runner reports "offline" for a few
# seconds between `svc.sh start` and its first connection to GitHub, so a single
# post-registration check races the service coming up; poll until online+labeled
# or the bound is hit (then fail closed).
_ONLINE_ATTEMPTS = 20
_ONLINE_DELAY_SECONDS = 6

# One runner's status as read from the GitHub runners API: {"status": str,
# "labels": list[str]}. Aliased so signatures stay concrete (no bare dict).
RunnerStatus = dict[str, object]

# Startup-script completion marker. Root-owned and world-readable, OUTSIDE the
# runner user's home: the readiness probe runs as the operator's OS Login
# identity (not root, not the runner user) and cannot traverse ~runner, so a
# marker there would be unreadable. MUST match the path the GCE startup script
# (platform/terraform/gcp/global/github-runner/startup-script.sh.tftpl) writes.
_RUNNER_READY_MARKER = "/var/lib/shifter-gcp-runner-ready"


@dataclass
class GcpRunnerConfig:
    """Configuration for a GCP self-hosted runner fleet.

    ``labels`` is the custom, provider/environment-specific label the runner
    registers with (``--no-default-labels``). It defaults to the environment
    name so a GCP-dev runner carries ``gcp-dev`` and never the default
    ``self-hosted`` label that AWS deploy/CI jobs still select.
    """

    env: str
    project_id: str
    region: str
    zone: str
    github_org: str
    github_repo: str
    labels: str


@dataclass
class GcpRunnerTarget:
    """One GCE runner to register.

    Transport data is GCP-specific (project/zone/instance name over IAP), the
    #1546 extensibility seam: another project/zone or a routed label set changes
    the target mapping, not the token handoff or the Terraform root.
    """

    instance_name: str
    runner_name: str
    repo_url: str
    project_id: str
    zone: str
    labels: str
    work_folder: str = DEFAULT_RUNNER_WORK_FOLDER


def get_gcp_runner_config(
    env: str,
    project_id: str,
    region: str,
    zone: str,
    github_org: str,
    github_repo: str,
    labels: str | None = None,
) -> GcpRunnerConfig:
    """Create a GcpRunnerConfig; the runner label defaults to the environment name."""
    return GcpRunnerConfig(
        env=env,
        project_id=project_id,
        region=region,
        zone=zone,
        github_org=github_org,
        github_repo=github_repo,
        labels=labels or env,
    )


def _verify_prerequisites() -> None:
    """Fail closed before any mutation unless gh auth + gcloud ADC are present.

    The runner path needs GitHub auth to mint per-runner tokens and gcloud
    Application Default Credentials to apply Terraform and open IAP sessions.
    This is intentionally narrower than the platform ``preflight_gate`` (which
    validates a whole environment deploy): a runner standup should not require
    the platform's secret/config surface.
    """
    gh = run_cmd(["gh", "auth", "status"], check=False, capture=True)
    if not gh or gh.returncode != 0:
        error("GitHub CLI is not authenticated (`gh auth status`); cannot mint a runner registration token")
        raise SystemExit(1)
    adc = run_cmd(["gcloud", "auth", "application-default", "print-access-token"], check=False, capture=True)
    if not adc or adc.returncode != 0:
        error("No gcloud Application Default Credentials; run `gcloud auth application-default login`")
        raise SystemExit(1)


def _ssh_argv(target: GcpRunnerTarget) -> list[str]:
    """Base ``gcloud compute ssh`` argv: IAP-tunneled, private, OS Login identity."""
    return [
        "gcloud",
        "compute",
        "ssh",
        target.instance_name,
        "--tunnel-through-iap",
        "--project",
        target.project_id,
        "--zone",
        target.zone,
        "--quiet",
    ]


# Safe grammars for the values interpolated into the privileged remote shell
# command. Anything outside these (spaces, quotes, $, ;, &, |, backticks, ...)
# is rejected so a crafted runner name / label / work folder / repo URL cannot
# break out of the config.sh argument and execute arbitrary commands as root on
# the runner VM (defense in depth beyond the values being config-derived).
_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")  # runner name, work folder
_SAFE_LABELS_RE = re.compile(r"^[A-Za-z0-9._,-]+$")  # comma-joined label set
_SAFE_REPO_URL_RE = re.compile(r"^https://[A-Za-z0-9._~:/?#@!$&'()*+,;=%-]+$")


def _validate_registration_fields(target: GcpRunnerTarget) -> None:
    """Reject registration inputs that could inject into the root remote shell."""
    checks = (
        ("runner_name", target.runner_name, _SAFE_NAME_RE),
        ("work_folder", target.work_folder, _SAFE_NAME_RE),
        ("labels", target.labels, _SAFE_LABELS_RE),
        ("repo_url", target.repo_url, _SAFE_REPO_URL_RE),
    )
    for field, value, pattern in checks:
        if not value or not pattern.match(value):
            raise ValueError(
                f"unsafe {field} for runner registration: {value!r}; "
                "shell metacharacters are not permitted (command-injection guard)"
            )


def _registration_remote_command(target: GcpRunnerTarget) -> str:
    """Return the token-free remote command run over ``gcloud compute ssh``.

    No token literal is part of this string. The token arrives on the SSH stdin
    stream and is captured into a root-owned 0600 temp file (``$TOKFILE``), then
    referenced with ``--token "$(cat "$TOKFILE")"`` and the file is deleted.

    Why not stdin-to-``config.sh`` (the AWS/#1433 technique)? The runner's .NET
    ``config.sh`` reads the token via ``Console.ReadKey``, which fails on
    redirected stdin ("Cannot read keys when ... console input has been
    redirected"). Non-interactive registration therefore *requires*
    ``--unattended --token <value>``; the runner supports no ``--token-file`` or
    env-var alternative (verified via ``config.sh --help``). The token is kept
    out of Terraform state, instance metadata, Secret Manager, the operator's
    local argv/logs, and any persistent store; the only residual is a momentary
    remote ``/proc/<pid>/cmdline`` entry on the dedicated, private,
    single-tenant runner VM while ``config.sh`` runs (~seconds), after which the
    temp file is removed and the single-use token expires. See ADR-008-R8 and the
    #1546 preflight note (which assumed stdin-to-config would work).

    Runs under ``sudo`` so the privileged shell owns the temp file (readable by
    the ``$(cat ...)`` substitution) and ``svc.sh install`` can create the unit.
    """
    _validate_registration_fields(target)
    inner = "; ".join(
        [
            "set -eu",
            "set +x",
            f"cd {RUNNER_HOME}",
            "umask 077",
            # Idempotent re-run: tolerate a prior install/config. `svc.sh install`
            # fails if the unit exists, and `config.sh --replace` only replaces
            # the GitHub-side runner -- it refuses when a LOCAL .runner config
            # already exists ("already configured; run config.sh remove first").
            # So stop+uninstall the service and clear the local config first
            # (|| true so a first run with neither does not abort under set -e).
            "./svc.sh stop || true",
            "./svc.sh uninstall || true",
            f"sudo -u {RUNNER_USER} ./config.sh remove --local || true",
            'TOKFILE="$(mktemp)"',
            'cat > "$TOKFILE"',
            (
                f"sudo -u {RUNNER_USER} ./config.sh --unattended --url {target.repo_url} "
                f"--name {target.runner_name} --labels {target.labels} --no-default-labels "
                f'--work {target.work_folder} --runnergroup Default --replace --token "$(cat "$TOKFILE")"'
            ),
            'rm -f "$TOKFILE"',
            f"./svc.sh install {RUNNER_USER}",
            "./svc.sh start",
        ]
    )
    return f"sudo bash -c '{inner}'"


def register_runner(config: GcpRunnerConfig, target: GcpRunnerTarget, *, dry_run: bool = False) -> int | None:
    """Register one runner over IAP SSH; return the handoff exit code (None in dry-run)."""
    if dry_run:
        info(
            f"[DRY-RUN] Would register {target.runner_name} on {target.instance_name} "
            "(no token minted, no SSH session opened)"
        )
        return None

    token = mint_registration_token(config)
    remote = _registration_remote_command(target)
    argv = [*_ssh_argv(target), "--command", remote]
    # The token is the stdin payload only; the argv (including the remote command)
    # carries no secret and is logged through the run_cmd redactor.
    rc = run_cmd_secret_stdin(argv, secret_stdin=f"{token}\n")
    if rc != 0:
        warn(f"Runner {target.runner_name}: registration handoff exited {rc}")
    else:
        success(f"Runner {target.runner_name} registration handoff completed")
    return rc


def wait_for_runner_ssh(target: GcpRunnerTarget) -> None:
    """Poll for registration readiness with a bounded timeout; fail closed otherwise.

    A RUNNING GCE instance -- and even a reachable SSH session -- is not
    registration readiness: the startup script installs the runner asynchronously
    and SSH comes up well before it finishes. The probe therefore waits for the
    startup script's completion marker (``~/.runner-ready``), so config.sh is
    never run before the runner is installed. Uses a static, non-secret remote
    command (never the token).
    """
    probe = [*_ssh_argv(target), "--command", f"test -f {_RUNNER_READY_MARKER}"]
    for attempt in range(1, _SSH_READY_ATTEMPTS + 1):
        result = run_cmd(probe, check=False, capture=True)
        if result and result.returncode == 0:
            return
        if attempt < _SSH_READY_ATTEMPTS:
            time.sleep(_SSH_READY_DELAY_SECONDS)
    error(f"Runner host {target.instance_name} did not finish provisioning (no ~/.runner-ready) in time")
    raise SystemExit(1)


def _parse_runner_status_map(raw: str) -> dict[str, RunnerStatus]:
    """Parse the ``gh api .../actions/runners`` payload into {name: {status, labels}}."""
    runners = json.loads(raw) if raw else []
    return {
        r.get("name"): {
            "status": r.get("status"),
            "labels": [lbl.get("name") for lbl in r.get("labels", [])],
        }
        for r in runners
    }


def _runner_online_with_label(detail: RunnerStatus | None, label: str) -> bool:
    """True iff the runner exists, is online, and carries the expected label."""
    return bool(detail) and detail.get("status") == "online" and label in detail.get("labels", [])


def verify_runners(
    config: GcpRunnerConfig,
    expected_names: list[str],
    *,
    dry_run: bool = False,
) -> dict[str, RunnerStatus]:
    """Verify runners via the GitHub runners API; return {name: {status, labels}}.

    Unlike the AWS path, GCP verification also reads each runner's labels: a
    runner that is online but missing the expected custom label is a failure
    (the label is what keeps it isolated from AWS ``self-hosted`` jobs).
    """
    if dry_run:
        info("[DRY-RUN] Would verify runners are online with the expected label via the GitHub runners API")
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
    by_name = _parse_runner_status_map(raw)
    for name in expected_names:
        detail = by_name.get(name)
        if _runner_online_with_label(detail, config.labels):
            success(f"Runner {name} is online with label '{config.labels}'")
        else:
            warn(f"Runner {name} not verified (status: {(detail or {}).get('status') or 'not found'})")
    return {name: by_name[name] for name in expected_names if name in by_name}


def _registration_failures(
    reg_exit_by_name: dict[str, int | None],
    verified: dict[str, RunnerStatus],
    expected_names: list[str],
    expected_label: str,
) -> list[str]:
    """Return problems for runners that did not register/come-online/carry the label.

    A runner is healthy only when its registration handoff exited 0 AND the
    GitHub API reports it online AND it carries the expected custom label.
    Anything else fails the command so a GCP tenant never reports success while
    its CI has no usable runner.
    """
    problems: list[str] = []
    for name in expected_names:
        rc = reg_exit_by_name.get(name)
        if rc != 0:
            problems.append(f"{name}: registration handoff exited {rc if rc is not None else 'unknown'}")
            continue
        detail = verified.get(name)
        if not detail:
            problems.append(f"{name}: not found in the GitHub runners API")
        elif detail.get("status") != "online":
            problems.append(f"{name}: not online (status: {detail.get('status') or 'unknown'})")
        elif expected_label not in detail.get("labels", []):
            problems.append(f"{name}: missing expected label '{expected_label}' (labels: {detail.get('labels')})")
    return problems


def _runner_tf_dir() -> Path:
    """Absolute path to the GCP runner Terraform root (separate from the platform root)."""
    return get_repo_root() / "platform" / "terraform" / "gcp" / "global" / "github-runner"


def _state_bucket(config: GcpRunnerConfig) -> str:
    """Resolve the GCS Terraform state bucket (per-project, dedicated runner prefix)."""
    return f"{config.project_id}-terraform-state"


def _terraform_output_targets(config: GcpRunnerConfig) -> list[GcpRunnerTarget]:
    """Read runner_instance_names / runner_names from terraform output into targets."""
    result = run_cmd(["terraform", "output", "-json"], capture=True, check=False)
    raw = (result.stdout or "").strip() if result else ""
    if not raw:
        return []
    outputs = json.loads(raw)
    names = outputs.get("runner_instance_names", {}).get("value", []) or []
    runner_names = outputs.get("runner_names", {}).get("value", []) or []
    repo_url = f"https://github.com/{config.github_org}/{config.github_repo}"
    return [
        GcpRunnerTarget(
            instance_name=instance_name,
            runner_name=runner_name,
            repo_url=repo_url,
            project_id=config.project_id,
            zone=config.zone,
            labels=config.labels,
        )
        for instance_name, runner_name in zip(names, runner_names, strict=False)
    ]


def apply_runner_terraform(
    config: GcpRunnerConfig,
    *,
    dry_run: bool = False,
    runner_count: int | None = None,
) -> list[GcpRunnerTarget]:
    """Init/plan/apply the GCP runner Terraform root; return provisioned targets.

    Terraform receives the project id and infrastructure inputs only -- never a
    registration token (tokens are minted per runner at registration time). The
    GCS backend bucket is derived from the project id and supplied at init time,
    so no live project id is committed to the repo. The dedicated runner network
    is always created (no opt-out; ADR-008-R8).
    """
    bucket = _state_bucket(config)
    init_cmd = [
        "terraform",
        "init",
        "-reconfigure",
        f"-backend-config=bucket={bucket}",
        "-backend-config=prefix=github-runner",
    ]
    var_flags = [f"-var=project_id={config.project_id}"]
    if runner_count is not None:
        var_flags.append(f"-var=runner_count={runner_count}")
    plan_cmd = ["terraform", "plan", "-out=tfplan", f"-var-file={config.env}.tfvars", *var_flags]
    apply_cmd = ["terraform", "apply", "tfplan"]

    if dry_run:
        for cmd in (init_cmd, plan_cmd, apply_cmd):
            run_cmd(cmd, dry_run=True)
        return []

    tf_dir = _runner_tf_dir()
    if not tf_dir.exists():
        error(f"GCP runner Terraform root not found: {tf_dir}")
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


def provision_and_register_gcp_runners(
    config: GcpRunnerConfig,
    *,
    dry_run: bool = False,
    runner_count: int | None = None,
) -> dict[str, object]:
    """Apply the GCP runner root, register each runner over IAP SSH, verify via the API.

    The automated path for ``deploy.py runners --cloud gcp``: Terraform
    provisions the GCE fleet plus the mandatory dedicated runner VPC (ADR-008-R8,
    no opt-out), then each runner is registered with a per-runner token delivered
    over the SSH stdin stream and verified online + labeled through the GitHub
    runners API -- no SSM, no manual step, and fail-closed on anything short of a
    healthy fleet.
    """
    header("Automated GCP GitHub Runner Provisioning & Registration")

    if not dry_run:
        _verify_prerequisites()

    targets = apply_runner_terraform(config, dry_run=dry_run, runner_count=runner_count)

    if dry_run:
        info("[DRY-RUN] Would register each runner over gcloud compute ssh (IAP) and verify online + labeled")
        return {"targets": [], "verified": {}}

    if not targets:
        error("No runner instances found in Terraform outputs; GCP runner provisioning produced no fleet")
        raise SystemExit(1)

    reg_exit_by_name: dict[str, int | None] = {}
    for target in targets:
        subheader(f"Registering {target.runner_name}")
        wait_for_runner_ssh(target)
        reg_exit_by_name[target.runner_name] = register_runner(config, target)

    expected = [t.runner_name for t in targets]

    # Poll: a runner reports offline for a few seconds after `svc.sh start`, so a
    # single check races the service connecting to GitHub. Re-check until every
    # runner is online + labeled or the bound is hit.
    problems: list[str] = []
    for attempt in range(1, _ONLINE_ATTEMPTS + 1):
        verified = verify_runners(config, expected)
        problems = _registration_failures(reg_exit_by_name, verified, expected, config.labels)
        if not problems:
            break
        if attempt < _ONLINE_ATTEMPTS:
            time.sleep(_ONLINE_DELAY_SECONDS)

    # Fail closed: a dispatched registration is not an online, correctly labeled runner.
    if problems:
        for problem in problems:
            error(problem)
        error("GCP runner provisioning did not complete cleanly; the GCP tenant CI has no usable runners")
        raise SystemExit(1)

    success(f"Provisioned and registered {len(targets)} GCP runner(s)")
    return {"targets": expected, "verified": verified}
